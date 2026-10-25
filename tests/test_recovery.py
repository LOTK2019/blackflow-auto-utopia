import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from blackflow.adb import Stopped
from blackflow.config import Config
from blackflow.recovery import read_with_recovery, ReadPolicy, ReadExhausted
from blackflow.maa_worker import make_overlay
from blackflow.runner import Runner


class ReadRecoveryTests(unittest.TestCase):
    def read(self, values, confirmations=None):
        observe = Mock(side_effect=[(v,{}) for v in values])
        records, wait = [], Mock()
        result = read_with_recovery('test', observe, wait=wait,
            policy=ReadPolicy(attempts=len(values)), confirmations=confirmations, record=records.append)
        return result, records, wait

    def test_unknown_and_conflict_reset_confirmation_count(self):
        value, records, wait = self.read([16,None,10,16,16])
        self.assertEqual(value,16)
        self.assertEqual([r['consecutive'] for r in records],[1,0,1,1,2])
        self.assertEqual(wait.call_count,4)

    def test_unknown_is_never_absent_and_false_requires_stability(self):
        with self.assertRaises(ReadExhausted):
            self.read([None]*5)
        result, records, _ = self.read([False,None,False,False])
        self.assertIs(result,False)
        self.assertEqual(len(records),4)

    def test_frame_error_retries_with_new_observation(self):
        observe=Mock(side_effect=[RuntimeError('empty screenshot'),(True,{}),(True,{})])
        self.assertIs(read_with_recovery('test',observe,wait=Mock()),True)
        self.assertEqual(observe.call_count,3)

    def test_stop_is_not_swallowed_or_delayed(self):
        observe=Mock(side_effect=Stopped())
        with self.assertRaises(Stopped):
            read_with_recovery('test',observe,wait=Mock())
        self.assertEqual(observe.call_count,1)
        observe=Mock(return_value=(None,{}))
        with self.assertRaises(Stopped):
            read_with_recovery('test',observe,wait=Mock(side_effect=Stopped()))
        self.assertEqual(observe.call_count,1)

    def test_programming_error_is_not_suppressed(self):
        with self.assertRaises(ValueError):
            read_with_recovery('test',Mock(side_effect=ValueError('invalid config')),wait=Mock())

    def test_absence_needs_four_consecutive_frames_even_after_unknown(self):
        values=['absent','absent',None,'absent','absent','absent','absent']
        result, records, _=self.read(values,lambda v:4 if v=='absent' else 2)
        self.assertEqual(result,'absent')
        self.assertEqual(len(records),7)


class NativeRecoveryTests(unittest.TestCase):
    def overlay(self,phase):
        with tempfile.TemporaryDirectory() as folder:
            make_overlay(Config.load(),phase,Path(folder))
            return json.loads((Path(folder)/'resource/tasks/tasks.json').read_text(encoding='utf-8'))

    def test_native_recovery_is_bounded_and_does_not_reenter_recruit_plugin(self):
        tasks=self.overlay('prepare')
        r='AutoUtopia@Recovery'
        self.assertEqual(tasks[r+'Event']['next'],['BlackFlow@Roguelike@StageEncounterJudgeOption'])
        self.assertEqual(tasks[r+'Event']['maxTimes'],3)
        self.assertEqual(tasks[r+'Wait']['maxTimes'],6)
        self.assertEqual(tasks[r+'Wait']['exceededNext'],[r+'Exhausted'])
        self.assertEqual(tasks[r+'Exhausted']['next'],['Stop'])
        self.assertEqual(tasks['BlackFlow@StartExplore@Roguelike@RecruitSkip']['template'],'RecruitSkip.png')
        self.assertEqual(tasks['BlackFlow@StartExplore@Roguelike@ChooseOperConfirmToGiveUp']['template'],
                         'Roguelike@StageEncounterGiveUpRecruitConfirm.png')
        for key in (r+'Recruit',r+'RecruitRead',r+'Floor',r+'Wait'):
            for target in tasks[key]['next']:
                self.assertNotEqual(target,'BlackFlow@StartExplore@Roguelike@ChooseOper')
                self.assertNotIn('Abandon',target)
                self.assertNotIn('StartExploreCD',target)

    def test_formal_recovery_never_enters_events_or_changes_squad(self):
        tasks=self.overlay('formal')
        self.assertNotIn('AutoUtopia@RecoveryEvent',tasks)
        self.assertNotIn('BlackFlow@Roguelike@ExitThenAbandon-Enter',tasks)
        self.assertEqual(tasks['BlackFlow@Roguelike@NextLevel']['next'],['Stop'])
        animation=tasks['BlackFlow@StartExplore@Roguelike@RecruitWithoutButton']
        self.assertIn('BlackFlow@Roguelike@NextLevel',animation['next'])
        self.assertFalse(any('Stop' in n or '#next' in n for n in animation['next']))

    def test_reported_six_star_display_has_bounded_guarded_resume(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/recruit-wang-animation.json').read_text(encoding='utf-8'))
        for phase in ('prepare','formal'):
            tasks=self.overlay(phase)
            r='AutoUtopia@Recovery'; name=r+'RecruitAnimation'
            action=tasks[name]
            self.assertIn(name,tasks[r+'Wait']['next'])
            self.assertEqual(action['maxTimes'],3)
            self.assertEqual(action['exceededNext'],[r+'Exhausted'])
            self.assertTrue(action['fullMatch'])
            x,y,w,h=action['roi']
            hits=[v for v in fixture['ocr'] if v['text'] in action['text'] and
                  x<=v['box'][0] and v['box'][2]<=x+w and y<=v['box'][1] and v['box'][3]<=y+h]
            self.assertEqual([v['text'] for v in hits],['SPECIALIST'])
            self.assertEqual(action['specificRect'],[1180,15,85,60])
            self.assertNotIn('BlackFlow@StartExplore@Roguelike@ChooseOper',action['next'])
            self.assertEqual(tasks['BlackFlow@StartExplore@Roguelike@RecruitWithoutButton']['specificRect'],
                             action['specificRect'])

    def test_explicit_abandon_phase_does_not_get_recovery_loops(self):
        self.assertFalse(any(k.startswith('AutoUtopia@Recovery') for k in self.overlay('abandon')))

    def test_start_loading_timeout_waits_without_resubmitting_start(self):
        p='BlackFlow@Roguelike@'; r='AutoUtopia@Recovery'
        for phase in ('prepare','formal'):
            tasks=self.overlay(phase)
            self.assertEqual(tasks[p+'StartExplore']['onErrorNext'],[r+'StartWait'])
            wait=tasks[r+'StartWait']
            self.assertEqual(wait['action'],'DoNothing')
            self.assertEqual(wait['maxTimes'],30)
            self.assertEqual(wait['exceededNext'],[r+'Exhausted'])
            self.assertIn(p+'Squad-EnterPoint',wait['next'])
            self.assertNotIn(p+'StartExplore',wait['next'])
            self.assertNotIn(p+'StartExplore-EnterCheck',wait['next'])

    def test_post_exit_loading_failure_recovers_without_native_abandon(self):
        # 032-prepare: CloseEventAfterEncounter -> Stages 识别失败，原生
        # onErrorNext 直接进入 ExitThenAbandon，导致二层就清掉探索。
        p='BlackFlow@Roguelike@'; r='AutoUtopia@Recovery'
        for phase in ('prepare','formal'):
            tasks=self.overlay(phase)
            self.assertEqual(tasks[p+'Stages']['onErrorNext'],[r+'Wait'])
            pending=list(tasks[p+'Stages']['onErrorNext']); visited=set()
            while pending:
                name=pending.pop()
                self.assertNotIn('Abandon',name)
                if name in visited or not name.startswith(r):continue
                visited.add(name)
                node=tasks[name]
                pending.extend(node.get('next',[])+node.get('exceededNext',[])+node.get('onErrorNext',[]))
            if phase=='prepare':
                for suffix in ('MapReady','MapZoomOut'):
                    self.assertIn(r+suffix,tasks[r+'Wait']['next'])
                    self.assertEqual(tasks[r+suffix]['action'],'DoNothing')
                    self.assertEqual(tasks[r+suffix]['maxTimes'],3)
            else:
                self.assertNotIn(r+'MapReady',tasks)
                self.assertNotIn(r+'MapZoomOut',tasks)


class RunnerRecoveryTests(unittest.TestCase):
    def runner(self):
        r=Runner(Config.load(),log=lambda _:None)
        r.capture=Mock(return_value='frame')
        r.adb=Mock()
        r.vision=Mock()
        return r

    def test_difficulty_recovers_transient_unreadable_and_wrong_single_frame(self):
        r=self.runner()
        r.vision.map_difficulty.side_effect=[(None,[]),(10,[]),(16,[]),(16,[])]
        r.confirm_map_difficulty()
        self.assertEqual(r.capture.call_count,4)

    def test_theme_retries_using_fresh_frames_without_clicking(self):
        r=self.runner()
        r.vision.match.side_effect=[None,None,None,True]
        r.vision.texts.return_value=[]
        r.vision.find.return_value=None
        r.require_theme('initial-frame')
        self.assertEqual(r.capture.call_count,1)
        r.adb.tap.assert_not_called()
        r.adb.swipe.assert_not_called()

    def test_ideal_unknown_then_recovers_without_being_treated_as_absent(self):
        r=self.runner()
        r.vision.texts.return_value=[]
        with patch('blackflow.runner.header_ideal',side_effect=[('unknown',{}),('present',{}),('present',{})]):
            self.assertEqual(r.inspect_ideal()[0],'present')
        self.assertEqual(r.capture.call_count,3)
        r.adb.tap.assert_not_called()
