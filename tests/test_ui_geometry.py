import unittest
from blackflow.ui_layout import initial_geometry


class InitialWindowTests(unittest.TestCase):
    def test_window_and_minimum_stay_inside_work_area_at_different_dpi(self):
        for area in ((0, 0, 1280, 680), (0, 40, 1366, 728), (0, 0, 1920, 1040),
                     (-1920, 0, 1920, 1040), (0, 0, 800, 560)):
            for scale in (1, 1.25, 1.5, 2):
                w, h, x, y, min_w, min_h = initial_geometry(area, scale)
                with self.subTest(area=area, scale=scale):
                    self.assertGreaterEqual(x, area[0])
                    self.assertGreaterEqual(y, area[1])
                    self.assertLessEqual(x + w, area[0] + area[2])
                    self.assertLessEqual(y + h, area[1] + area[3])
                    self.assertGreaterEqual(w, min_w)
                    self.assertGreaterEqual(h, min_h)
                    self.assertLess(w, area[2])
                    self.assertLess(h, area[3])


if __name__ == '__main__':
    unittest.main()
