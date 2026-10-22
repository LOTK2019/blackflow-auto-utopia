import json
import queue
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from blackflow.runner import Runner
from blackflow.adb import Stopped


class ErrorReportTests(unittest.TestCase):
    def runner(self, folder):
        runner=object.__new__(Runner)
        runner.session=Path(folder);runner.phase='文明开化正式局';runner.cycle=3
        runner.stop=threading.Event();runner.adb=Mock();runner.log=Mock()
        runner.last_frame=None;runner.last_frame_at=None
        runner._reported_exception=None;runner._error_report=None
        return runner

    def test_fresh_error_screen_and_original_trace_saved_once(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder)
            runner.adb.screenshot.return_value=np.full((720,1280,3),97,dtype=np.uint8)
            try:
                raise RuntimeError('LastReward-EnterPoint 卡住')
            except RuntimeError as exc:
                path=runner.save_error_report(exc)
                self.assertEqual(path,runner.save_error_report(exc))
            report=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(report['screenshot_source'],'fresh')
            self.assertIn('LastReward-EnterPoint',report['traceback'])
            self.assertTrue((path.parent/report['screenshot']).is_file())
            runner.adb.screenshot.assert_called_once()

    def test_failed_capture_uses_explicitly_old_frame_and_keeps_original_error(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder);runner.adb.screenshot.side_effect=RuntimeError('ADB disconnected')
            runner.last_frame=np.zeros((720,1280,3),dtype=np.uint8);runner.last_frame_at='earlier'
            path=runner.save_error_report(ValueError('原始奖励异常'))
            report=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(report['screenshot_source'],'last_known')
            self.assertEqual(report['captured_at'],'earlier')
            self.assertIn('ADB disconnected',report['screenshot_error'])
            self.assertIn('原始奖励异常',report['message'])

    def test_capture_failure_without_cached_frame_still_writes_report(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder);runner.adb.screenshot.side_effect=OSError('offline')
            path=runner.save_error_report(RuntimeError('招募失败'))
            report=json.loads(path.read_text(encoding='utf-8'))
            self.assertIsNone(report['screenshot'])
            self.assertIn('offline',report['screenshot_error'])

    def test_image_write_failure_is_recorded_and_does_not_replace_original(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder);runner.adb.screenshot.return_value=np.zeros((2,2,3),dtype=np.uint8)
            with patch('blackflow.runner.save_image',side_effect=OSError('cannot save image')):
                path=runner.save_error_report(RuntimeError('原始错误'))
            report=json.loads(path.read_text(encoding='utf-8'))
            self.assertIn('原始错误',report['message'])
            self.assertIn('cannot save image',report['screenshot_error'])

    def test_stopped_device_is_not_queried(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder);runner.stop.set()
            runner.save_error_report(RuntimeError('停止期间的错误'))
            runner.adb.screenshot.assert_not_called()

    def test_run_error_survives_error_state_write_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder);runner.config=Mock()
            original=ValueError('original validation failure')
            runner.config.validate.side_effect=original
            runner.acquire_lock=Mock(return_value=Mock())
            runner.set_phase=Mock(side_effect=OSError('state disk failure'))
            runner.adb.screenshot.return_value=np.zeros((2,2,3),dtype=np.uint8)
            with self.assertRaises(ValueError) as raised:
                runner.run()
            self.assertIs(raised.exception,original)
            self.assertEqual(len(list((Path(folder)/'errors').glob('*.json'))),1)

    def test_gui_diagnostic_exception_also_saves_error_screen(self):
        import app
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder);runner.adb.screenshot.return_value=np.zeros((2,2,3),dtype=np.uint8)
            ui=object.__new__(app.App);ui.thread=None;ui.bus=queue.Queue();ui.start_button=Mock()
            def failed_diagnosis():
                ui.runner=runner
                raise RuntimeError('not on theme page')
            with patch('app.ROOT',Path(folder)):
                ui.background(failed_diagnosis)
                ui.thread.join(timeout=10)
            self.assertFalse(ui.thread.is_alive())
            self.assertEqual(len(list((Path(folder)/'errors').glob('*.png'))),1)
            self.assertTrue((Path(folder)/'错误详情.log').is_file())

    def test_manual_stop_is_not_saved_or_displayed_as_an_error(self):
        import app
        with tempfile.TemporaryDirectory() as folder:
            runner=self.runner(folder)
            self.assertIsNone(runner.save_error_report(Stopped()))
            ui=object.__new__(app.App);ui.thread=None;ui.bus=queue.Queue();ui.start_button=Mock()
            def stopped_diagnosis():
                ui.runner=runner
                raise Stopped()
            with patch('app.ROOT',Path(folder)):
                ui.background(stopped_diagnosis)
                ui.thread.join(timeout=10)
            self.assertFalse((Path(folder)/'errors').exists())
            self.assertFalse((Path(folder)/'错误详情.log').exists())
            runner.adb.screenshot.assert_not_called()
