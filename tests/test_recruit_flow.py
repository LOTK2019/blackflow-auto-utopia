"""验证招募链路保留上游语义；实机重复测试单独记录，不用合成动画冒充。"""
import json,tempfile,unittest
from pathlib import Path
from blackflow.config import Config
from blackflow.maa_worker import make_overlay
from blackflow.vision import Vision
class RecruitmentFlowTests(unittest.TestCase):
 def overlay(self,phase='formal'):
  c=Config.load()
  with tempfile.TemporaryDirectory() as d:
   make_overlay(c,phase,Path(d));tasks=json.loads((Path(d)/'resource/tasks/tasks.json').read_text(encoding='utf-8'))
  return c,tasks
 def test_no_override_of_native_recruitment_tasks(self):
  for phase in ('formal','prepare'):
   _,tasks=self.overlay(phase)
   self.assertFalse(any(k.startswith('BlackFlow@StartExplore@Roguelike@') for k in tasks))
 def test_confirmation_uses_maa_template_not_second_name_ocr(self):
  c,tasks=self.overlay();v=Vision(c.maa_dir)
  name='BlackFlow@StartExplore@Roguelike@ChooseOperConfirm'
  self.assertNotIn(name,tasks)
  self.assertEqual(v.task(name)['action'],'ClickSelf')
  self.assertTrue(v.task(name)['template'].endswith('ChooseOperConfirm.png'))
 def test_map_stop_cannot_be_expanded_from_animation_next(self):
  c,tasks=self.overlay();v=Vision(c.maa_dir)
  name='BlackFlow@Roguelike@NextLevel'
  self.assertNotIn('Stop',v.task(name)['next'])
  self.assertEqual(tasks[name]['next'],['AutoUtopia@VerifiedMapStop'])
  guard=tasks['AutoUtopia@VerifiedMapStop']
  self.assertEqual(guard['baseTask'],name)
  self.assertEqual(guard['next'],['Stop'])
  self.assertNotEqual(guard.get('algorithm'),'JustReturn')
 def test_initial_voucher_gate_is_read_only_and_requires_all_roles(self):
  c,tasks=self.overlay();checks=tasks['BlackFlow@Roguelike@RolesConfirm']['sub']
  self.assertEqual([tasks[n]['text'] for n in checks],[['特种招募券'],['先锋招募券'],['辅助招募券']])
  for n in checks:
   self.assertEqual(tasks[n]['action'],'DoNothing')
   self.assertNotIn('onErrorNext',tasks[n])
 def test_no_animation_budget_or_english_title_recovery(self):
  for phase in ('formal','prepare'):
   _,tasks=self.overlay(phase)
   self.assertFalse(any(k.startswith('AutoUtopia@RecoveryRecruit') for k in tasks))
   self.assertFalse(any('Recruit' in n for n in tasks['AutoUtopia@RecoveryWait']['next']))
 def test_list_budget_remains_twenty_independent_of_native_animation(self):
  c,tasks=self.overlay();v=Vision(c.maa_dir)
  self.assertEqual(tasks['RoguelikeRecruitSwipeMaxTime']['maxTimes'],20)
  self.assertEqual(v.task('BlackFlow@StartExplore@Roguelike@RecruitWithoutButton')['maxTimes'],10)
if __name__=='__main__':unittest.main()
