import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from blackflow.config import Config, ROOT
from blackflow.maa_worker import make_overlay
from blackflow.runner import Runner
from blackflow.vision import Vision, header_ideal, IDEAL_ROI


class ConfigurationTests(unittest.TestCase):
    def test_default_loadout(self):
        c = Config.load()
        c.validate()
        ops = c.operators()
        self.assertEqual(c.difficulty, 16)
        self.assertEqual([ops[n]["profession"] for n in [c.six_star, *c.four_stars]], ["SPECIAL", "PIONEER", "SUPPORT"])
        self.assertTrue(all(ops[n]["rarity"] == 6 and ops[n]["profession"] == "SPECIAL" for n in c.allowed_six()))

    def test_wrong_four_star_rejected(self):
        c = Config.load()
        c.four_stars[0] = "维什戴尔"
        with self.assertRaises(ValueError):
            c.validate()

    def test_formal_stops_on_map_and_guards_recruitment(self):
        with tempfile.TemporaryDirectory() as d:
            make_overlay(Config.load(), "formal", Path(d))
            tasks = json.loads((Path(d) / "resource/tasks/tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(tasks["BlackFlow@Roguelike@NextLevel"]["next"], ["Stop"])
            guard = tasks["BlackFlow@StartExplore@Roguelike@ChooseOperConfirm"]
            self.assertIn("冬时", guard["text"])
            self.assertIn("深海色", guard["text"])
            self.assertNotIn("桃金娘", guard["text"])
            self.assertEqual(guard["roi"], [0, 65, 250, 80])

    def test_difficulty_selection_reuses_maa_with_correct_list_coordinates(self):
        for phase, target in (("prepare", "保密等级"), ("formal", "16")):
            with tempfile.TemporaryDirectory() as d:
                make_overlay(Config.load(), phase, Path(d))
                tasks = json.loads((Path(d) / "resource/tasks/tasks.json").read_text(encoding="utf-8"))
                self.assertEqual(tasks["SwipeToTheDown"]["specificRect"], [480, 150, 80, 40])
                guard = tasks["AutoUtopia@DifficultyValueConfirm"]
                self.assertEqual(guard["text"], [target])
                self.assertTrue(guard["fullMatch"])
                self.assertEqual(guard["isAscii"], phase == "formal")
                self.assertEqual(tasks["BlackFlow@Roguelike@ChooseDifficulty"]["action"], "DoNothing")
                self.assertIn("AutoUtopia@DifficultyValueConfirm", tasks["BlackFlow@Roguelike@ChooseDifficulty"]["sub"])
                options = json.loads((Path(Config.load().maa_dir) / "resource/config.json").read_text(encoding="utf-8"))["options"]
                duration = tasks["SwipeToTheDown"]["specialParams"][0]
                self.assertAlmostEqual(duration * options.get("adbSwipeDurationMultiplier", 10), 450, delta=10)

    def test_preparation_invests_then_flies_to_exits(self):
        with tempfile.TemporaryDirectory() as d:
            c = Config.load()
            c.prepare_method = '绿商店投资'
            make_overlay(c, "prepare", Path(d))
            strategy = json.loads((Path(d) / "resource/roguelike/BlackFlow/strategy.json").read_text(encoding="utf-8"))
            profile = next(p for p in strategy["profiles"] if p["id"] == "burn_with_investment")
            self.assertTrue(all(r["next_action"] == "stop_run" for r in profile["terminal_rules"]))
            flight = next(m for m in strategy["modules"] if m["id"] == "mechanic_flight")
            self.assertTrue({"utopia_fly_to_green_shop", "utopia_fly_to_first_exit", "burn_require_flight_on_floor2"} <= {r["id"] for r in flight["rules"]})

    def test_required_capacity_reward_has_a_guarded_rejection(self):
        c = Config.load()
        c.reward_target = "空间租赁（背包+2）"
        with tempfile.TemporaryDirectory() as d:
            make_overlay(c, "formal", Path(d))
            tasks = json.loads((Path(d) / "resource/tasks/tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(tasks["BlackFlow@Roguelike@LastReward-Strategy"]["next"][0], "BlackFlow@Roguelike@LastReward6")
            self.assertNotIn("BlackFlow@Roguelike@LastReward6.png", tasks["AutoUtopia@RewardMissingNormal"]["template"])
            self.assertEqual(tasks["AutoUtopia@RewardRejected"]["action"], "DoNothing")
            self.assertEqual(tasks["AutoUtopia@RewardRejected"].get("preDelay",0), 0)


class IconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = Vision(Config.load().maa_dir)
        cls.baseline = cls.load(ROOT / "assets/no-ideal-icon-slot.png")

    @staticmethod
    def load(path):
        return cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)

    def sample(self, name):
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:78, 480:830] = self.load(ROOT / f"assets/fixtures/{name}.png")
        return frame, self.vision.texts(frame, IDEAL_ROI)

    def test_two_different_real_icons(self):
        for name in ("snow-header", "eye-header"):
            frame, texts = self.sample(name)
            self.assertEqual(header_ideal(frame, texts, first_floor_only=False)[0], "present", name)

    def test_user_no_icon_example(self):
        frame, texts = self.sample("empty-header")
        self.assertEqual(header_ideal(frame, texts, first_floor_only=False)[0], "absent")

    def test_live_first_floor_no_icon(self):
        frame, texts = self.sample("first-floor-empty-header")
        self.assertEqual(header_ideal(frame, texts, self.baseline)[0], "absent")

    def test_unknown_is_never_absent(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        self.assertEqual(header_ideal(frame, [], self.baseline)[0], "unknown")
        frame, texts = self.sample("eye-header")
        self.assertEqual(header_ideal(frame, texts, self.baseline)[0], "unknown")  # 不是一层

    def test_actual_n10_is_not_mistaken_for_configured_n16(self):
        for value in (10, 16):
            frame = np.zeros((720, 1280, 3), np.uint8)
            frame[680:720, 0:42] = self.load(ROOT / f"assets/fixtures/difficulty-{value}.png")
            self.assertEqual(self.vision.map_difficulty(frame)[0], value)


class LoopTests(unittest.TestCase):
    def make_runner(self, statuses):
        r = Runner(Config.load(), log=lambda _: None)
        r.acquire_lock = Mock(return_value=Mock())  # 单元测试不争用正在进行的账户实测。
        r.require_theme = lambda _: None
        r.connect = lambda: None
        r.capture = lambda _: None
        r.adb = Mock()
        r.vision = Mock()
        r.vision.match.return_value = None
        r.maa = Mock(return_value={})
        r.inspect_ideal = Mock(side_effect=[(s, s) for s in statuses])
        r.confirm_map_difficulty = Mock()
        return r

    def test_missing_ideal_requires_a_new_preparation(self):
        r = self.make_runner(["absent", "present"])
        self.assertEqual(r.run(), "found")
        self.assertEqual([c.args[0] for c in r.maa.call_args_list], ["prepare", "abandon", "formal", "abandon", "prepare", "abandon", "formal"])

    def test_unknown_preserves_formal_run(self):
        r = self.make_runner(["unknown"])
        with self.assertRaises(RuntimeError):
            r.run()
        self.assertEqual([c.args[0] for c in r.maa.call_args_list], ["prepare", "abandon", "formal"])

    def test_wrong_difficulty_never_counts_as_found_or_abandons(self):
        r = self.make_runner(["present"])
        r.confirm_map_difficulty.side_effect = RuntimeError("实际难度不是 N16")
        with self.assertRaisesRegex(RuntimeError, "N16"):
            r.run()
        r.inspect_ideal.assert_not_called()
        self.assertEqual([c.args[0] for c in r.maa.call_args_list], ["prepare", "abandon", "formal"])

    def test_map_difficulty_requires_two_actual_matching_frames(self):
        for readings in ((10, 10), (16, 10), (None, 16)):
            r = self.make_runner([])
            r.vision.map_difficulty.side_effect = [(n, []) for n in readings * 4]
            with self.assertRaisesRegex(RuntimeError, "实际难度核验失败"):
                Runner.confirm_map_difficulty(r)
        r = self.make_runner([])
        r.vision.map_difficulty.side_effect = [(16, []), (16, [])]
        Runner.confirm_map_difficulty(r)

    def test_reward_miss_restarts_preparation_before_any_map_check(self):
        r = self.make_runner(["present"])
        r.maa.side_effect = [{}, {}, {"reward_rejected": True}, {}, {}, {}, {}]
        self.assertEqual(r.run(), "found")
        self.assertEqual(r.inspect_ideal.call_count, 1)
        self.assertEqual([c.args[0] for c in r.maa.call_args_list], ["prepare", "abandon", "formal", "abandon", "prepare", "abandon", "formal"])

    def test_more_than_fifty_cycles_are_allowed(self):
        r = self.make_runner([*["absent"] * 55, "present"])
        self.assertEqual(r.run(), "found")
        self.assertEqual(r.cycle, 56)


if __name__ == "__main__":
    unittest.main()
