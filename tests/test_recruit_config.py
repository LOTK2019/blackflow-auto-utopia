import unittest
from blackflow.config import Config
class RecruitmentConfigTests(unittest.TestCase):
 def test_rejects_wrong_vouchers_before_connect(self):
  c=Config.load();c.roles='灵活部署';c.four_stars=['褐果','布丁']
  with self.assertRaisesRegex(ValueError,'没有对应招募券.*褐果.*布丁'):c.validate()
 def test_accepts_matching_long_list_operators(self):
  c=Config.load();c.roles='坚不可摧';c.six_star='黍';c.four_stars=['褐果','布丁'];c.validate()
 def test_dynamic_specialists_keep_matching_vouchers(self):
  for n in ('望','予愿安洁莉娜'):
   c=Config.load();c.roles='灵活部署';c.six_star=n;c.four_stars=['冬时','深海色'];c.validate()
 def test_invalid_combination_is_rejected(self):
  c=Config.load();c.roles='不存在'
  with self.assertRaisesRegex(ValueError,'开局组合无效'):c.validate()
if __name__=='__main__':unittest.main()
