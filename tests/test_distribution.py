import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from blackflow.config import Config, data_root, read_blackflow_strategy
from blackflow.errors import error_event
from blackflow.discovery import discover


class DistributionTests(unittest.TestCase):
    def test_release_defaults_have_no_authors_paths(self):
        self.assertEqual(Config().maa_dir, "")
        self.assertEqual(Config().adb_path, "")
        self.assertEqual(Config().address, "auto")

    def test_frozen_data_is_per_current_user(self):
        root = data_root(Path('Z:/ReadOnly/App'), True, {'LOCALAPPDATA': 'C:/Users/Other/AppData/Local'})
        self.assertEqual(root, Path('C:/Users/Other/AppData/Local/BlackFlowUtopia'))
        self.assertEqual(data_root(Path('Z:/source'), False, {}), Path('Z:/source'))

    def test_bundled_engine_overrides_external_version_and_is_not_saved_as_absolute_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'maa_dir': 'Z:/OldMAA'}), encoding='utf-8')
            engine = Path(folder) / 'internal/maa'
            with patch('blackflow.config.BUNDLED_MAA', engine):
                config = Config.load(path)
                self.assertEqual(config.maa_dir, str(engine))
                config.save(path)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['maa_dir'], '')

    def test_old_resources_report_missing_features_instead_of_empty_stop_iteration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'resource/roguelike/BlackFlow/strategy.json'
            path.parent.mkdir(parents=True)
            for strategy, expected in (({'profiles': [], 'modules': []}, 'burn_with_investment'),
                                       ({'profiles': [{'id': 'burn_with_investment'}], 'modules': []}, 'mechanic_flight')):
                path.write_text(json.dumps(strategy), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, expected):
                    read_blackflow_strategy(folder)

    def test_empty_exception_keeps_type_and_trace(self):
        try:
            raise StopIteration()
        except Exception as exc:
            event = error_event(exc)
        self.assertIn('StopIteration', event['message'])
        self.assertIn('StopIteration', event['traceback'])
        self.assertTrue(event['message'].strip())

    def test_missing_config_uses_neutral_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(Config.load(Path(folder) / 'absent.json').address, 'auto')

    def test_blank_adb_is_not_treated_as_an_executable_directory(self):
        with patch('blackflow.discovery.Path.is_file', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '未发现 ADB'):
                discover('')


if __name__ == '__main__':
    unittest.main()
