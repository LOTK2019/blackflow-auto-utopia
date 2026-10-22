import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from blackflow.adb import ADB, Stopped, decode_image, load_image


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.adb = ADB("adb.exe", "127.0.0.1:16384")
        self.adb.wait = Mock()
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:, 640:] = 180
        self.png = cv2.imencode(".png", frame)[1].tobytes()

    def test_empty_then_retry_succeeds(self):
        self.adb.command = Mock(side_effect=[b"", self.png])
        self.assertEqual(self.adb.screenshot().shape, (720, 1280, 3))
        self.assertEqual(self.adb.command.call_count, 2)

    def test_empty_exec_out_falls_back_to_pull(self):
        def command(*args):
            if args[0] == "pull":
                Path(args[2]).write_bytes(self.png)
            return b""
        self.adb.command = Mock(side_effect=command)
        self.assertEqual(self.adb.screenshot().shape, (720, 1280, 3))
        self.assertTrue(any(call.args[0] == "pull" for call in self.adb.command.call_args_list))
        self.assertTrue(any(call.args[:3] == ("shell", "rm", "-f") for call in self.adb.command.call_args_list))

    def test_all_methods_empty_report_device_and_cause(self):
        self.adb.command = Mock(return_value=b"")
        with self.assertRaisesRegex(RuntimeError, "127.0.0.1:16384.*0 字节"):
            self.adb.screenshot()

    def test_corrupt_image_is_explained(self):
        with self.assertRaisesRegex(RuntimeError, "不是有效图片"):
            decode_image(b"not a screenshot", "测试截图")

    def test_empty_resource_reports_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.png"
            path.write_bytes(b"")
            with self.assertRaisesRegex(RuntimeError, "broken.png.*0 字节"):
                load_image(path)

    def test_stop_interrupts_retry(self):
        self.adb.command = Mock(side_effect=Stopped())
        with self.assertRaises(Stopped):
            self.adb.screenshot()
        self.assertEqual(self.adb.command.call_count, 1)


if __name__ == "__main__":
    unittest.main()
