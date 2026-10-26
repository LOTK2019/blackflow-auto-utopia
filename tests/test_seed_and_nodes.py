from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from blackflow.config import Config
from blackflow.maa_worker import make_overlay
from blackflow.nodes import effective_nodes, reconcile_node_maps
from blackflow.runner import Runner
from blackflow.strategy import SEED_PROFILE, COUNT_PROFILE, optional_seed_completion, seed_action_point_rules


def snapshot(types, **extra):
    return {'floor':1,'floor_from_ocr':True,'node_count':len(types),
            'nodes':[{'row':0,'column':i,'type':t,'identity_state':'classified'} for i,t in enumerate(types)], **extra}


class NodeCountTests(unittest.TestCase):
    def reported_jitter(self):
        data=json.loads((Path(__file__).parent/'fixtures/node-count-jitter.json').read_text(encoding='utf-8'))
        templates=json.loads((Path(Config.load().maa_dir)/'resource/roguelike/BlackFlow/map_templates.json').read_text(encoding='utf-8'))['templates']
        return data['observations'],templates

    def test_real_jitter_recovers_eight_nodes_without_treating_unknown_as_empty(self):
        groups,templates=self.reported_jitter()
        self.assertIsNone(reconcile_node_maps(groups[:2],templates))
        result=reconcile_node_maps(groups[:3],templates)
        self.assertEqual((result['effective'],result['empty'],result['total']),(8,3,11))
        self.assertEqual(result['ignored_unclassified_positions'],[(0,4)])
        self.assertTrue(all(n['observations']>=2 for n in result['node_votes']))

    def test_single_worker_cannot_supply_two_votes(self):
        groups,templates=self.reported_jitter()
        self.assertIsNone(reconcile_node_maps([groups[1]*4],templates))

    def test_unrecognized_real_node_and_binary_conflicts_still_stop(self):
        groups,templates=self.reported_jitter()
        # 留一份完整锚点，但真实节点其余轮都未知，不能借模板猜类型。
        for group in (groups[0],groups[2],groups[3]):
            for s in group:
                n=next(n for n in s['nodes'] if (n['row'],n['column'])==(1,2))
                n.update(type='unclassified',identity_state='unclassified')
        self.assertIsNone(reconcile_node_maps(groups,templates))
        groups,templates=self.reported_jitter()
        for s in groups[3]:
            n=next(n for n in s['nodes'] if (n['row'],n['column'])==(1,2))
            n.update(type='empty',identity_state='classified')
        self.assertIsNone(reconcile_node_maps(groups,templates))

    def test_unknown_topology_does_not_drop_unclassified_positions(self):
        groups,templates=self.reported_jitter()
        self.assertIsNone(reconcile_node_maps(groups,[]))
        for group in groups:
            for s in group:
                s['current_node']=s['nodes'][0]['id']
        self.assertIsNone(reconcile_node_maps(groups,templates))

    def test_runner_replays_real_failed_session_with_no_game_input(self):
        groups,_=self.reported_jitter()
        r=Runner(Config.load(),log=lambda _:None);r.config.min_effective_nodes=8;r.capture=Mock();r.adb=Mock()
        r.maa=Mock(side_effect=[{'node_maps':g} for g in groups])
        self.assertEqual(r.count_effective_nodes(),8)
        self.assertEqual(r.maa.call_count,3)
        r.adb.tap.assert_not_called()

    def test_unknown_battle_can_only_reject_below_conservative_upper_bound(self):
        groups=json.loads((Path(__file__).parent/'fixtures/node-count-unknown-battle.json').read_text(encoding='utf-8'))['observations']
        _,templates=self.reported_jitter()
        self.assertIsNone(reconcile_node_maps(groups,templates))
        upper=reconcile_node_maps(groups,templates,minimum=9)
        self.assertEqual(upper['effective'],8)
        self.assertTrue(upper['effective_is_upper_bound'])
        self.assertIsNone(reconcile_node_maps(groups,templates,minimum=8))
        self.assertIsNone(reconcile_node_maps([groups[1]],templates,minimum=9))
        self.assertIsNone(reconcile_node_maps(groups,[],minimum=9))
        r=Runner(Config.load(),log=lambda _:None);r.config.min_effective_nodes=9
        r.capture=Mock();r.adb=Mock();r.maa=Mock(side_effect=[{'node_maps':g} for g in groups])
        self.assertEqual(r.count_effective_nodes(),8)
        r.adb.tap.assert_not_called()

    def test_counts_every_nonempty_node_including_hidden_nodes(self):
        data=snapshot(['empty','shop','scrap_shop','incident','hide_invisible','final','empty'])
        result=effective_nodes(data)
        self.assertEqual((result['effective'],result['empty'],result['total']),(5,2,7))

    def test_incomplete_or_unclassified_map_is_not_a_low_count(self):
        for data in (snapshot(['empty'],node_count=2),snapshot(['unclassified']),
                     snapshot(['shop'],floor=2),snapshot(['shop'],floor_from_ocr=False)):
            with self.assertRaises(ValueError):effective_nodes(data)
        data=snapshot(['shop','shop']);data['nodes'][1]['column']=0
        with self.assertRaises(ValueError):effective_nodes(data)

    def test_node_filter_defaults_off_and_seed_preparation_defaults_on(self):
        c=Config()
        self.assertFalse(c.node_filter_enabled)
        self.assertEqual(c.prepare_method,'黄商店种植')

    def test_recount_recovers_then_requires_two_consistent_independent_maps(self):
        r=Runner(Config.load(),log=lambda _:None);r.capture=Mock();r.adb=Mock()
        r.maa=Mock(side_effect=[{'node_maps':[]},{'node_maps':[snapshot(['shop','empty'])]},
                                {'node_maps':[snapshot(['shop','empty'])]}])
        self.assertEqual(r.count_effective_nodes(),1)
        self.assertEqual(r.maa.call_count,3)
        r.adb.tap.assert_not_called()

    def test_disagreement_does_not_silently_reject_run(self):
        r=Runner(Config.load(),log=lambda _:None);r.capture=Mock();r.adb=Mock()
        r.maa=Mock(side_effect=[{'node_maps':[snapshot(['shop']*n)]} for n in (2,3,2,3)])
        with self.assertRaisesRegex(RuntimeError,'保留正式局'):r.count_effective_nodes()


class SeedStrategyTests(unittest.TestCase):
    def test_shortcut_encounter_uses_safe_exit_in_both_preparation_profiles(self):
        for method in ('黄商店种植','绿商店投资'):
            c=Config.load();c.prepare_method=method
            with tempfile.TemporaryDirectory() as folder:
                make_overlay(c,'prepare',Path(folder))
                strategy=json.loads((Path(folder)/'resource/roguelike/BlackFlow/strategy.json').read_text(encoding='utf-8'))
            profile_id='burn' if method=='黄商店种植' else 'burn_with_investment'
            profile=next(p for p in strategy['profiles'] if p['id']==profile_id)
            modules=[m for m in strategy['modules'] if m['id'] in profile['modules']]
            rules=[r for m in modules for r in m.get('encounter_rules',[]) if r.get('event_name')=='三重身']
            self.assertEqual(len(rules),1)
            rule=rules[0]
            # 报告里第一项跨层，第二项保持当前楼层；不依赖显示次序。
            options=['接受它的提议','自己找路—']
            for displayed in (options,list(reversed(options))):
                matches=[t for t in displayed if any(text in t for text in rule['option_text'])]
                self.assertEqual(matches,['自己找路—'])
            self.assertFalse(rule['allow_fallback'])

    def ap_forbids(self,points,edges,floor=3,movement='walk',exit=False):
        facts={'action_points':points,'current_floor':floor,'candidate.move_edges':edges,
               'candidate.movement':movement,'candidate.exit':exit}
        def matches(tree):
            if 'all' in tree:return all(matches(x) for x in tree['all'])
            if 'any' in tree:return any(matches(x) for x in tree['any'])
            a,b=facts[tree['fact']],tree['value']
            return {'eq':lambda:a==b,'ne':lambda:a!=b,'ge':lambda:a>=b,'le':lambda:a<=b}[tree['op']]()
        return any(matches(r['when']) and matches(r['candidate_if']) for r in seed_action_point_rules())

    def test_real_chase_causing_move_is_forbidden_before_commit(self):
        events=json.loads((Path(__file__).parent/'fixtures/third-floor-zero-ap.json').read_text(encoding='utf-8'))
        decision=events[-1]['data']['details']
        self.assertTrue(self.ap_forbids(decision['action_points_before'],decision['path_edge_count'],decision['floor']))
        for rule in seed_action_point_rules():
            self.assertEqual((rule['kind'],rule['tier']),('forbid','legality'))

    def test_never_spend_last_point_even_for_shop_and_reserve_escape_before_floor3(self):
        self.assertTrue(self.ap_forbids(1,1))
        self.assertTrue(self.ap_forbids(1,0,movement='rogue_6_scrap_M_11'))
        self.assertFalse(self.ap_forbids(2,1))
        self.assertTrue(self.ap_forbids(3,2,floor=2))
        self.assertFalse(self.ap_forbids(3,2,floor=2,exit=True))
        self.assertTrue(self.ap_forbids(2,0,floor=2,movement='rogue_6_scrap_M_11'))
        self.assertFalse(self.ap_forbids(2,0,floor=2,movement='rogue_6_scrap_M_11',exit=True))
    def test_only_confirmed_third_floor_safe_route_exhaustion_is_normal_completion(self):
        result={'outcome':'planning_failed','termination_reason':'no eligible safe candidate','succeeded':False}
        summary={'floor':3,'floor_from_ocr':True,'unclassified_count':0}
        self.assertTrue(optional_seed_completion(result,summary)['succeeded'])
        for bad in ({**summary,'floor':2},{**summary,'floor_from_ocr':False}):
            self.assertFalse(optional_seed_completion(result,bad)['succeeded'])
        self.assertFalse(optional_seed_completion({**result,'outcome':'map_rebuild_failed'},summary)['succeeded'])
    def overlay(self,phase):
        with tempfile.TemporaryDirectory() as folder:
            make_overlay(Config.load(),phase,Path(folder))
            base=Path(folder)/'resource'
            tasks=json.loads((base/'tasks/tasks.json').read_text(encoding='utf-8'))
            p=base/'roguelike/BlackFlow/strategy.json'
            return tasks,json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

    def test_seed_mode_does_not_require_harvest_by_default(self):
        _,s=self.overlay('prepare')
        p=next(p for p in s['profiles'] if p['id']==SEED_PROFILE)
        self.assertNotIn('burn_investment_shop',p['modules'])
        success=next(r for r in p['terminal_rules'] if r['succeeded'])
        self.assertEqual(success['when']['all'][0],{'fact':'current_floor','op':'ge','value':3})
        self.assertEqual(success['when']['all'][1],{'fact':'cultivation_completed','op':'eq','value':True})
        route=next(m for m in s['modules'] if m['id']=='utopia_seed_route')
        self.assertFalse(route['shopping_rules'])
        flight=next(m for m in s['modules'] if m['id']=='utopia_seed_flight')
        self.assertFalse(flight['rules'])
        self.assertTrue(flight['granted_scraps'])

    def test_unspecified_animals_still_search_yellow_before_leaving(self):
        _,s=self.overlay('prepare')
        route=next(m for m in s['modules'] if m['id']=='utopia_seed_route')
        self.assertEqual({m['id'] for m in route['milestones']},{'baby_explore_hidden','baby_visit_incident'})
        self.assertNotIn('utopia_seed_second_floor_without_yellow',{r['id'] for r in route['rules']})
        self.assertIn('utopia_seed_save_flight',{r['id'] for r in route['rules']})
        self.assertNotIn('baby_delay_exit_before_floor3',{r['id'] for r in route['rules']})
        by_id={r['id']:r for r in route['rules']}
        self.assertEqual(by_id['utopia_seed_direct_yellow']['kind'],'prefer')
        self.assertEqual(by_id['utopia_seed_direct_yellow']['tier'],'resource_reserve')
        self.assertLess(by_id['utopia_seed_direct_yellow']['rank'],by_id['utopia_seed_save_flight']['rank'])
        self.assertEqual(by_id['utopia_seed_keep_last_exit_flight']['kind'],'forbid')
        self.assertEqual(by_id['utopia_seed_no_battle']['candidate_if'],{'fact':'candidate.combat','op':'eq','value':True})
        reserve=next(r for r in route['reserves'] if r['id']=='baby_keep_cultivation_movement')
        self.assertIn({'fact':'candidate.exit','op':'eq','value':True},reserve['release_if']['any'])
        cultivate=next(m for m in s['modules'] if m['id']=='utopia_seed_cultivate')
        final=next(m for m in cultivate['milestones'] if m['id']=='baby_cultivate_scrap_shop_final')
        self.assertEqual(final['on_miss'],'ignore')

    def test_real_visible_shop_detours_rank_shop_above_light_and_incident(self):
        _,strategy=self.overlay('prepare')
        route=next(m for m in strategy['modules'] if m['id']=='utopia_seed_route')
        common=next(m for m in strategy['modules'] if m['id']=='common_navigation')
        # 两个真实回执均已把黄店列为 eligible runner-up。这里只重放
        # 安全过滤后的偏好排序，不伪造地图/路线可行性求解。
        receipts=json.loads((Path(__file__).parent/'fixtures/visible-yellow-detours.json').read_text(encoding='utf-8'))
        def matches(tree,facts):
            if 'all' in tree:return all(matches(t,facts) for t in tree['all'])
            if 'any' in tree:return any(matches(t,facts) for t in tree['any'])
            a,b=facts.get(tree['fact']),tree['value']
            if a is None:return False
            return {'eq':lambda:a==b,'ne':lambda:a!=b,'ge':lambda:a>=b,'le':lambda:a<=b}[tree['op']]()
        # 与已核对的原生选择器一致：strategy_constraint 的 prefer 不计分；
        # ResourceReserve 的 prefer 在发展收益之前按 rank/id 比较。
        def score(candidate,receipt,rules):
            facts={'current_floor':2,'cultivation_completed':False,'scrap_shop_available':True,
                   'candidate.node_type':candidate['node_type'],'candidate.movement':candidate['movement'],
                   'candidate.exit':False,'candidate.light_reveal_count':3 if candidate['node_type']=='light' else 0}
            ranks={'resource_reserve':0,'development':1,'risk':2,'tie_break':3}
            active=[r for r in rules if r['kind']=='prefer' and r['tier'] in ranks and matches(r.get('when',{'all':[]}),facts)]
            active.sort(key=lambda r:(ranks[r['tier']],r.get('rank',0),r['id']))
            return tuple(0 if matches(r['candidate_if'],facts) else 1 for r in active)
        for receipt in receipts:
            shop=next(r for r in receipt['runners_up'] if r['node_type']=='scrap_shop')
            chosen={'node_type':receipt['node_type'],'movement':receipt['movement']}
            yellow={'node_type':'scrap_shop','movement':shop['action_id'].split(':',1)[0]}
            rules=common.get('rules',[])+route['rules']
            self.assertLess(score(yellow,receipt,rules),score(chosen,receipt,rules))
            broken=deepcopy(rules)
            next(r for r in broken if r['id']=='utopia_seed_direct_yellow')['tier']='strategy_constraint'
            self.assertLess(score(chosen,receipt,broken),score(yellow,receipt,broken))

    def test_flight_is_reserved_for_yellow_shop_and_exit_not_exploration(self):
        _,s=self.overlay('prepare')
        route=next(m for m in s['modules'] if m['id']=='utopia_seed_route')
        rule=next(r for r in route['rules'] if r['id']=='utopia_seed_fly_shop_or_exit_only')
        self.assertEqual((rule['kind'],rule['tier']),('forbid','legality'))
        self.assertIn({'fact':'candidate.node_type','op':'ne','value':'scrap_shop'},rule['candidate_if']['all'])
        self.assertIn({'fact':'candidate.exit','op':'eq','value':False},rule['candidate_if']['all'])
        leave=next(r for r in route['rules'] if r['id']=='utopia_seed_leave_after_plant')
        self.assertEqual(leave['tier'],'resource_reserve')
        self.assertLess(leave['rank'],0)

    def test_map_inspection_has_no_start_recruit_or_abandon_entry_and_forbids_moves(self):
        tasks,s=self.overlay('map')
        self.assertEqual(tasks['BlackFlow@Roguelike@Begin']['next'],['BlackFlow@Roguelike@NextLevel'])
        p=next(p for p in s['profiles'] if p['id']==COUNT_PROFILE)
        self.assertEqual(p['failure_action'],'stop_run')
        rule=next(m for m in s['modules'] if m['id']=='utopia_no_movement')['rules'][0]
        self.assertEqual(rule['kind'],'forbid')
        self.assertEqual({c['value'] for c in rule['candidate_if']['any']},{True,False})


class NodeLoopTests(unittest.TestCase):
    def runner(self):
        r=Runner(Config.load(),log=lambda _:None);r.config.node_filter_enabled=True;r.config.min_effective_nodes=10
        r.acquire_lock=Mock(return_value=Mock());r.require_theme=Mock();r.connect=Mock();r.capture=Mock();r.adb=Mock()
        r.vision=Mock();r.vision.match.return_value=None;r.maa=Mock(return_value={})
        r.confirm_map_difficulty=Mock();r.inspect_ideal=Mock(return_value=('present','test'))
        return r

    def test_insufficient_nodes_requires_new_preparation(self):
        r=self.runner();r.count_effective_nodes=Mock(side_effect=[9,10])
        self.assertEqual(r.run(),'found')
        self.assertEqual([c.args[0] for c in r.maa.call_args_list],['prepare','abandon','formal','abandon','prepare','abandon','formal'])
        self.assertEqual(r.inspect_ideal.call_count,1)

    def test_unconfirmed_nodes_preserve_run(self):
        r=self.runner();r.count_effective_nodes=Mock(side_effect=RuntimeError('unknown nodes'))
        with self.assertRaises(RuntimeError):r.run()
        self.assertEqual([c.args[0] for c in r.maa.call_args_list],['prepare','abandon','formal'])

    def test_no_harvest_never_opens_formal_run(self):
        r=self.runner();r.config.node_filter_enabled=False
        r.maa.side_effect=[{'prepare_rejected':True},{},{},{},{}]
        self.assertEqual(r.run(),'found')
        self.assertEqual([c.args[0] for c in r.maa.call_args_list],['prepare','abandon','prepare','abandon','formal'])
