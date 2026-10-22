import json
from pathlib import Path
import tempfile
import unittest

from blackflow.animals import animals_satisfy, animals_from_ocr
from blackflow.config import Config
from blackflow.maa_worker import make_overlay
from blackflow.rewards import DEFAULT_REWARD_ORDER, SERPENT_REWARDS, reward_plan


class AnimalCountTests(unittest.TestCase):
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

    def test_all_twelve_options_and_user_reorder(self):
        c=Config.load();c.reward_target='默认排序'
        c.reward_priority=list(reversed(DEFAULT_REWARD_ORDER));c.require_first_reward=False
        tasks=self.tasks(c)
        order=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(len(order),18)  # 六种普通奖励各有模板和文字两种识别。
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
        tasks=self.tasks(c)
        entry=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(entry[0],'BlackFlow@Roguelike@LastReward6')
        commit=tasks[entry[0]]['next'][0]
        next_selection=tasks[commit]['next'][-1]
        decision=tasks[next_selection]['next'][0]
        self.assertEqual(len(tasks[decision]['next']),18)
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

    def test_text_fallback_keeps_priority_and_blue_confirmation_has_text_fallback(self):
        c=Config.load();c.reward_target='默认排序';c.require_first_reward=False
        tasks=self.tasks(c)
        choices=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(choices[:4],['BlackFlow@Roguelike@LastReward6',
            'AutoUtopia@RewardText空间租赁','BlackFlow@Roguelike@LastReward2',
            'AutoUtopia@RewardText林间代步'])
        for reward in SERPENT_REWARDS:
            task=tasks['AutoUtopia@Reward'+reward.removeprefix('襁褓')]
            self.assertIn('AutoUtopia@RewardCommitText',task['next'])
        confirm=tasks['AutoUtopia@RewardCommitText']
        self.assertEqual(confirm['text'],['你确定要这么做'])
        self.assertEqual(confirm['action'],'ClickSelf')

    def test_strict_normal_target_tries_its_text_before_rejecting(self):
        c=Config.load();c.require_first_reward=True;c.reward_target='默认排序'
        tasks=self.tasks(c)
        entry=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next']
        self.assertEqual(entry[:2],['BlackFlow@Roguelike@LastReward6','AutoUtopia@RewardText空间租赁'])
        self.assertNotIn('空间租赁',tasks['AutoUtopia@RewardMissingBlue']['text'])

    def test_blue_first_target_uses_ocr_and_legacy_setting_stays_compatible(self):
        c=Config.load();c.reward_priority=['襁褓天马',*[n for n in DEFAULT_REWARD_ORDER if n!='襁褓天马']]
        c.require_first_reward=True;c.reward_target='默认排序'
        tasks=self.tasks(c);target=tasks['BlackFlow@Roguelike@LastReward-Strategy']['next'][0]
        self.assertEqual(tasks[target]['text'],['天马'])
        c.reward_target='林间代步（加工品）'
        order,strict=reward_plan(c)
        self.assertTrue(strict);self.assertEqual(order[0],'林间代步')
