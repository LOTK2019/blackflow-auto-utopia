import tempfile,unittest
from pathlib import Path
from blackflow.config import Config
from blackflow.recruitment import NativeRecruitAudit
class NativeRecruitAuditTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)/'asst.log';self.p.write_bytes(b'old data\n');self.c=Config.load();self.c.six_star='望';self.c.four_stars=['褐果','布丁'];self.c.allow_other_six_star=False;self.a=NativeRecruitAudit(self.p,self.c,'formal')
 def append(self,s):
  with self.p.open('ab') as f:f.write(s.encode('utf-8'))
 def choose(self,n):self.append(f'[INF] asst::RoguelikeRecruitTaskPlugin::select_oper | Choose oper: {n} ( elite 1 level 80 )\n')
 def test_valid_results_advance_independent_slots(self):
  for n in ['望','褐果','布丁']:self.choose(n);self.a.complete()
  self.assertEqual(self.a.snapshot()['selected'],['望','褐果','布丁']);self.assertEqual(self.a.index,3)
 def test_missing_four_star_stops_before_default_fallback(self):
  self.choose('望');self.a.complete();self.append('asst::RoguelikeRecruitTaskPlugin::recruit_appointed_char | Cannot find oper `褐果`\n')
  with self.assertRaisesRegex(RuntimeError,'未找到指定干员褐果'):self.a.poll()
 def test_wrong_native_selection_is_rejected_without_ocr(self):
  self.choose('卡达')
  with self.assertRaisesRegex(RuntimeError,'实际选择卡达'):self.a.poll()
 def test_no_log_evidence_is_not_success(self):
  with self.assertRaisesRegex(RuntimeError,'未提供可核对'):self.a.complete()
 def test_partial_utf8_log_lines_wait_for_newline(self):
  self.append('asst::RoguelikeRecruitTaskPlugin::select_oper | Choose oper: 望');self.a.poll();self.assertEqual(self.a.selected,[])
  self.append(' ( elite 1 level 80 )\n');self.a.complete();self.assertEqual(self.a.selected,['望'])
 def test_old_log_entries_are_not_reused(self):
  self.assertEqual(self.a.selected,[])
  with self.assertRaises(RuntimeError):self.a.complete()
if __name__=='__main__':unittest.main()
