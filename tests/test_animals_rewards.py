import json
from pathlib import Path
import tempfile
import unittest

from blackflow.animals import animals_satisfy, animals_from_ocr, harvest_animals_from_ocr
from blackflow.config import Config
from blackflow.maa_worker import make_overlay
from blackflow.rewards import DEFAULT_REWARD_ORDER, SERPENT_REWARDS, reward_plan, required_rewards


class AnimalCountTests(unittest.TestCase):
    def test_report_with_only_naturals_is_confirmed_zero_animals(self):
        rows=json.loads((Path(__file__).parent/'fixtures/harvest-only-naturals.json').read_text(encoding='utf-8'))
        market=json.loads((Path(Config.load().maa_dir)/'resource/roguelike/BlackFlow/scrap_market.json').read_text(encoding='utf-8'))
        naturals={item['name'] for item in market['scraps'] if item.get('category')=='natural'}
        result=harvest_animals_from_ocr(rows,naturals)
        self.assertEqual(result,())
        self.assertFalse(animals_satisfy(result,['襁褓中的猫']))

    def test_mixed_harvest_preserves_counts_but_unknown_card_is_not_zero(self):
        natural={'text':'回声玉米','score':.99}
        cat={'text':'襁褓中的猫','score':.95}
        self.assertEqual(harvest_animals_from_ocr([natural,cat,cat],{'回声玉米'}),('swaddled_cat','swaddled_cat'))
        for rows in ([],[{'text':'4','score':.99}],
                     [natural,{'text':'未识别卡片','score':.99}],
                     [{'text':'回声玉米','score':.2}]):
            self.assertIsNone(harvest_animals_from_ocr(rows,{'回声玉米'}))

    def test_harvest_ocr_preserves_duplicate_cards_and_rejects_uncertain_text(self):
        rows=[{'text':s,'score':.95} for s in ('襁褓中的狗','襁褓中的猫','襁褓中的狗')]
        self.assertEqual(animals_from_ocr(rows),('swaddled_cat','swaddled_dog','swaddled_dog'))
        self.assertIsNone(animals_from_ocr([{'text':'襁褓中的猫','score':.2}]))
    def test_order_independent_superset_and_extra_serpent(self):
        self.assertTrue(animals_satisfy(['swaddled_dog','swaddled_feathered_serpent','swaddled_cat'],
                                       ['襁褓中的猫','襁褓中的狗']))

    def test_duplicate_requirement_checks_quantity(self):
        self.assertFalse(animals_satisfy(['swaddled_dog','swaddled_cat','swaddled_feathered_serpent'],
                                        ['襁褓中的狗','襁褓中的狗']))
        self.assertTrue(animals_satisfy(['swaddled_dog','swaddled_cat','swaddled_dog'],
                                       ['襁褓中的狗','襁褓中的狗']))

    def test_zero_counts_never_require_harvest(self):
        c=Config()
        self.assertFalse(c.require_animals)
        self.assertTrue(animals_satisfy([],c.desired_animals))
        c.animal_counts={'猫':1,'狗':1,'三头犬':0}
        self.assertTrue(c.require_animals)
        self.assertEqual(c.desired_animals,['襁褓中的猫','襁褓中的狗'])


class RewardPriorityTests(unittest.TestCase):
    def tasks(self,config):
        with tempfile.TemporaryDirectory() as folder:
            make_overlay(config,'formal',Path(folder))
            return json.loads((Path(folder)/'resource/tasks/tasks.json').read_text(encoding='utf-8'))

    def test_top_two_accepts_second_normal_or_blue_before_missing_probes(self):
        c=Config.load();c.reward_target='默认排序';c.require_first_reward=False
        c.required_reward_top_n=2
        c.reward_priority=['空间租赁','襁褓天马',*[n for n in DEFAULT_REWARD_ORDER if n not in ('空间租赁','襁褓天马')]]
        tasks=self.tasks(c);entry=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(entry[:2],['BlackFlow@Roguelike@LastReward6','AutoUtopia@Reward天马'])
        self.assertEqual(required_rewards(c),['空间租赁','襁褓天马'])
        for key in entry[2:]:
            probe=tasks[key]
            self.assertNotIn('BlackFlow@Roguelike@LastReward6.png',probe.get('template',[]))
            self.assertNotIn('天马',probe.get('text',[]))
        # 第二项命中也进入同一确认与后续普通排序，不再要求第一项。
        commit=tasks[entry[1]]['next'][0]
        next_page=tasks[commit]['next'][-1]
        decision=tasks[next_page]['next'][0]
        self.assertEqual(len(tasks[decision]['next']),12)
        self.assertNotIn('BlackFlow@Roguelike@LastReward-Strategy',tasks[next_page]['next'])

    def test_top_all_never_installs_empty_missing_matchers(self):
        c=Config.load();c.reward_target='默认排序';c.require_first_reward=False;c.required_reward_top_n=12
        tasks=self.tasks(c)
        self.assertEqual(len(tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']),12)
        self.assertNotIn('AutoUtopia@RewardMissingNormal',tasks)
        self.assertNotIn('AutoUtopia@RewardMissingBlue',tasks)

    def test_top_n_config_roundtrip_and_legacy_single_reward(self):
        c=Config.load();c.reward_target='默认排序';c.require_first_reward=False;c.required_reward_top_n=3
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';c.save(path);loaded=Config.load(path)
        self.assertEqual(required_rewards(loaded),c.reward_priority[:3])
        c.required_reward_top_n=0
        self.assertEqual(required_rewards(c),[])
        c.require_first_reward=True
        self.assertEqual(required_rewards(c),c.reward_priority[:1])
        c.required_reward_top_n=3;c.reward_target='空间租赁（背包+2）'
        self.assertEqual(required_rewards(c),['空间租赁'])

    def test_top_n_rejects_invalid_ranges_and_noninteger_values(self):
        for value in (-1,13,True,1.5,'2'):
            c=Config.load();c.required_reward_top_n=value
            with self.assertRaisesRegex(ValueError,'0～12'):c.validate()

    def test_all_twelve_options_and_user_reorder(self):
        c=Config.load();c.reward_target='默认排序'
        c.reward_priority=list(reversed(DEFAULT_REWARD_ORDER));c.require_first_reward=False
        tasks=self.tasks(c)
        order=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(len(order),12)
        self.assertEqual(order[0],'BlackFlow@Roguelike@LastReward3')
        for animal in SERPENT_REWARDS:
            self.assertIn('AutoUtopia@Reward'+animal.removeprefix('襁褓'),order)

    def test_reward_alias_templates_exist_in_bundled_resources(self):
        c=Config.load();tasks=self.tasks(c)
        existing={p.name for p in (Path(c.maa_dir)/'resource/template').rglob('*.png')}
        for name in ('RewardCommit','RewardClose','RewardRolesReady','RewardRecruitReady'):
            self.assertIn(tasks['AutoUtopia@'+name]['template'],existing)

    def test_strict_only_applies_to_initial_selection(self):
        c=Config.load();c.reward_target='默认排序';c.require_first_reward=True
        c.reward_priority=list(DEFAULT_REWARD_ORDER)
        tasks=self.tasks(c)
        entry=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(entry[0],'BlackFlow@Roguelike@LastReward6')
        commit=tasks[entry[0]]['next'][0]
        next_selection=tasks[commit]['next'][-1]
        decision=tasks[next_selection]['next'][0]
        self.assertEqual(len(tasks[decision]['next']),12)
        self.assertNotIn('BlackFlow@Roguelike@LastReward-Strategy',tasks[next_selection]['next'])
        self.assertTrue(tasks['AutoUtopia@RewardMissingNormal']['maxTimes']>1)

    def test_serpent_page_and_later_choices_do_not_require_normal_cards(self):
        tasks=self.tasks(Config.load())
        for name in ('BlackFlow@Roguelike@LastReward-EnterPoint','AutoUtopia@RewardNextSelection'):
            self.assertEqual(tasks[name]['algorithm'],'OcrDetect')
            self.assertEqual(tasks[name]['text'],['选择支援'])
        # 后续奖励页仍覆盖六种蓝卡，并且不会重新检查严格第一项。
        decision=tasks['AutoUtopia@RewardNextSelection']['next'][0]
        for reward in SERPENT_REWARDS:
            self.assertIn('AutoUtopia@Reward'+reward.removeprefix('襁褓'),tasks[decision]['next'])

    def test_native_normal_card_priority_and_blue_confirmation_text_fallback(self):
        c=Config.load();c.reward_target='默认排序';c.require_first_reward=False
        c.reward_priority=list(DEFAULT_REWARD_ORDER)
        tasks=self.tasks(c)
        choices=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(choices[:2],['BlackFlow@Roguelike@LastReward6','BlackFlow@Roguelike@LastReward2'])
        self.assertFalse(any('RewardText' in task for task in choices))
        for reward in SERPENT_REWARDS:
            task=tasks['AutoUtopia@Reward'+reward.removeprefix('襁褓')]
            self.assertIn('AutoUtopia@RewardCommitText',task['next'])
        confirm=tasks['AutoUtopia@RewardCommitText']
        self.assertEqual(confirm['text'],['你确定要这么做'])
        self.assertEqual(confirm['action'],'ClickSelf')

    def test_serpent_fourth_card_confirmation_is_inside_template_and_text_regions(self):
        case=json.loads((Path(__file__).parent/'fixtures/serpent-four-card-confirm.json').read_text(encoding='utf-8'))
        tasks=self.tasks(Config.load())
        normal=tasks['BlackFlow@Roguelike@LastReward2']['next']
        self.assertIn('AutoUtopia@RewardCommit',normal)
        self.assertIn('AutoUtopia@RewardCommitText',normal)
        x,y,w,h=tasks['AutoUtopia@RewardCommit']['roi']
        tx,ty,tw,th=case['confirmation_template_rect']
        self.assertTrue(x<=tx and y<=ty and tx+tw<=x+w and ty+th<=y+h)
        text=tasks['AutoUtopia@RewardCommitText']
        x,y,w,h=text['roi'];left,top,right,bottom=case['confirmation_text_box']
        self.assertTrue(x<=left and y<=top and right<=x+w and bottom<=y+h)
        dx,dy,rw,rh=text['rectMove'];click=(left+dx+rw/2,top+dy+rh/2)
        bx,by,br,bb=case['check_button_box']
        self.assertTrue(bx<=click[0]<=br and by<=click[1]<=bb)

    def test_selected_blue_card_is_skipped_without_resetting_priority(self):
        c=Config.load();c.require_first_reward=False;c.reward_target='默认排序'
        c.reward_priority=['襁褓天马',*filter(lambda name:name!='襁褓天马',DEFAULT_REWARD_ORDER)]
        tasks=self.tasks(c)
        entry=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        selected=tasks[entry[0]]
        self.assertEqual(selected['maxTimes'],1)
        self.assertEqual(selected['exceededNext'],entry[1:])
        self.assertNotIn(entry[0],selected['exceededNext'])

    def test_blue_first_target_uses_ocr_and_legacy_setting_stays_compatible(self):
        c=Config.load();c.reward_priority=['襁褓天马',*[n for n in DEFAULT_REWARD_ORDER if n!='襁褓天马']]
        c.require_first_reward=True;c.reward_target='默认排序'
        tasks=self.tasks(c);target=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next'][0]
        self.assertEqual(tasks[target]['text'],['天马'])
        c.reward_target='林间代步（加工品）'
        order,strict=reward_plan(c)
        self.assertTrue(strict);self.assertEqual(order[0],'林间代步')
