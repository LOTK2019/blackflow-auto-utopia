"""页面状态回归：模拟识别命中，不冒充动态皮肤真实图像/实机回放。"""
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from blackflow.config import Config
from blackflow.maa_worker import make_overlay
from blackflow.vision import Vision


class RecruitmentFlowTests(unittest.TestCase):
    p='BlackFlow@StartExplore@Roguelike@'
    animation=p+'RecruitWithoutButton'
    confirm=p+'ChooseOperConfirm'

    def setUp(self):
        self.c=Config.load()
        with tempfile.TemporaryDirectory() as folder:
            make_overlay(self.c,'formal',Path(folder))
            self.overlay=json.loads((Path(folder)/'resource/tasks/tasks.json').read_text(encoding='utf-8'))
        self.v=Vision(self.c.maa_dir)
        for name,value in self.overlay.items():
            self.v.tasks[name]={**self.v.tasks.get(name,{}),**value}

    def expand(self,names):
        result=[]
        for name in names:
            if name.startswith(('Roguelike@','StartExplore@')):name='BlackFlow@'+name
            if name.endswith('#next'):
                result.extend(self.expand(self.v.task(name[:-5]).get('next',[])))
            else:result.append(name)
        return result

    def matches(self,name,page):
        if name==self.confirm or name=='AutoUtopia@RecoveryRecruit':return page=='selected_target'
        if name.endswith('ChooseOperConfirmToGiveUp'):return page=='giveup'
        if name==self.p+'RecruitSkip':return page=='skip_button'
        if name==self.p+'RecruitOther':return page=='voucher'
        if name=='BlackFlow@Roguelike@EnterAfterRecruit':return page=='ready'
        if name.endswith(('NextLevel','RecoveryFloor')):return page=='map'
        if name=='AutoUtopia@RecoveryRecruitAnimation':return page=='display_class'
        return self.v.task(name).get('algorithm')=='JustReturn'

    def choose(self,names,page):
        return next((n for n in self.expand(names) if self.matches(n,page)),None)

    def test_plugin_already_confirmed_without_class_text_uses_native_successors(self):
        choices=self.overlay[self.p+'ChooseOper']['next']
        self.assertEqual(choices,[self.confirm,self.confirm+'#next'])
        self.assertEqual(self.choose(choices,'intro_without_text'),self.animation)
        # v0.1.3的三项覆盖只会进入等待，无法直接接住已提交后的动画。
        old=[self.confirm,self.p+'ChooseOperConfirmToGiveUp','AutoUtopia@RecoveryRecruitRead']
        self.assertEqual(self.choose(old,'intro_without_text'),'AutoUtopia@RecoveryRecruitRead')

    def test_next_voucher_and_map_win_before_any_skip_click(self):
        for page,expected in (('voucher',self.p+'RecruitOther'),
                              ('ready','BlackFlow@Roguelike@EnterAfterRecruit'),
                              ('map','BlackFlow@Roguelike@NextLevel')):
            for branch in (self.animation,'AutoUtopia@RecoveryRecruitAnimation'):
                self.assertEqual(self.choose(self.overlay[branch]['next'],page),expected)

    def test_long_animation_does_not_require_name_or_profession_ocr(self):
        # 合成28帧无文字状态；超过旧版20次预算，之后确实看到下一张券。
        count=0
        choices=self.overlay[self.p+'ChooseOper']['next']
        for _ in range(28):
            selected=self.choose(choices,'intro_without_text')
            self.assertEqual(selected,self.animation)
            count+=1
            self.assertLessEqual(count,self.overlay[selected]['maxTimes'])
            choices=self.overlay[selected]['next']
        self.assertEqual(self.choose(choices,'voucher'),self.p+'RecruitOther')

    def test_each_new_voucher_recovers_full_budget_not_only_original_ten(self):
        limit=self.overlay[self.animation]['maxTimes']
        flag=self.overlay[self.p+'ChooseOperFlag']
        self.assertIn(self.animation+f'*{limit}',flag['reduceOtherTimes'])
        counts=Counter({self.animation:limit})
        for entry in flag['reduceOtherTimes']:
            if '*' in entry:
                name,n=entry.rsplit('*',1)
                counts[name]=max(0,counts[name]-int(n))
        self.assertEqual(counts[self.animation],0)
        self.assertNotIn(self.animation+f'*{limit}',self.overlay['AutoUtopia@RecoveryWait'].get('reduceOtherTimes',[]))

    def test_name_guard_not_replaced_by_unconditional_confirmation(self):
        task=self.overlay[self.confirm]
        self.assertEqual(task['algorithm'],'OcrDetect')
        self.assertTrue(task['fullMatch'])
        self.assertEqual(task['text'],[*self.c.allowed_six(),*self.c.four_stars])
        self.assertNotEqual(self.choose(self.overlay[self.p+'ChooseOper']['next'],'wrong_selected_name'),self.confirm)
        for task_name in (self.animation,'AutoUtopia@RecoveryRecruitAnimation'):
            next_tasks=self.expand(self.overlay[task_name]['next'])
            self.assertFalse(any('Abandon' in n or n=='Stop' for n in next_tasks))
            self.assertNotIn(self.p+'ChooseOper',next_tasks)

    def test_completion_fallback_is_finite_and_still_uses_upstream_skip_rect(self):
        task=self.overlay[self.animation]
        self.assertEqual(task['specificRect'],[1180,15,85,60])
        self.assertEqual(task['maxTimes'],40)
        self.assertEqual(task['exceededNext'],['AutoUtopia@RecoveryWait'])
        self.assertEqual(self.overlay['AutoUtopia@RecoveryWait']['exceededNext'],['AutoUtopia@RecoveryExhausted'])
