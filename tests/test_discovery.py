import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from blackflow.discovery import (discover, _adb_candidates, _manager_addresses,
                                _configured_addresses, _json_output, _instances, run)
from blackflow.config import Config


class MuMuDiscoveryTests(unittest.TestCase):
    def installation(self, root, layout='nx_main'):
        folder=Path(root)/'非默认位置 MuMu'/layout
        folder.mkdir(parents=True,exist_ok=True)
        adb=folder/'adb.exe'; adb.touch()
        return adb

    def candidates(self, provided='', processes=(), registry=()):
        with patch('blackflow.discovery._process_paths',return_value=processes), \
             patch('blackflow.discovery._registry_paths',return_value=registry), \
             patch.dict('os.environ',{},clear=True):
            return _adb_candidates(provided)

    def test_new_process_layout_and_legacy_shell_registry(self):
        with tempfile.TemporaryDirectory() as root:
            adb=self.installation(root)
            process=adb.parent.parent/'nx_device/15.0/shell/MuMuNxDevice.exe'
            self.assertEqual(self.candidates(processes=[process]),[adb.resolve()])
            old=self.installation(root,'shell')
            self.assertEqual(self.candidates(registry=[old.parent.parent]),[adb.resolve(),old.resolve()])

    def test_manual_quoted_path_folder_and_stale_path_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            adb=self.installation(root,'shell')
            self.assertEqual(self.candidates('"'+str(adb)+'"'),[adb.resolve()])
            self.assertEqual(self.candidates(str(adb.parent.parent)),[adb.resolve()])
            self.assertEqual(self.candidates('Z:/Removed/adb.exe',registry=[adb.parent.parent]),[adb.resolve()])

    def test_adb_server_executable_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            server=Path(root)/'adb_server.exe';server.touch()
            self.assertEqual(self.candidates(str(server)),[server.resolve()])

    def test_json_banner_list_and_single_instance_formats(self):
        self.assertEqual(_instances(_json_output('\ufeff提示\n{"data":[{"index":2,"adb_port":16448}]}\nOK')),
                         [('2',{'index':2,'adb_port':16448})])
        self.assertEqual(_instances({'0':{'adb_port':16384}}),[('0',{'adb_port':16384})])

    def test_manager_one_bad_instance_does_not_hide_later_instance(self):
        with tempfile.TemporaryDirectory() as root:
            adb=self.installation(root);(adb.parent/'MuMuManager.exe').touch()
            def command(*args,**kwargs):
                if args[-1]=='all':return json.dumps({'0':{},'1':{'adb_port':'16416'}})
                raise subprocess.TimeoutExpired(args,1)
            with patch('blackflow.discovery.run',side_effect=command):
                self.assertEqual(_manager_addresses(adb,lambda _:None),['127.0.0.1:16416'])

    def test_json_config_works_when_nemu_is_missing_or_broken(self):
        with tempfile.TemporaryDirectory() as root:
            adb=self.installation(root)
            vm=adb.parent.parent/'vms/实例-1';(vm/'configs').mkdir(parents=True)
            (vm/'broken.nemu').write_text('broken',encoding='utf-8')
            (vm/'configs/vm_config.json').write_text(json.dumps({'vm':{'nat':{'port_forward':{'adb':{'host_port':'16416'}}}}}),encoding='utf-8-sig')
            self.assertEqual(_configured_addresses(adb,lambda _:None),['127.0.0.1:16416'])

    def detection(self, devices, states, known=(), configured=(), adb_candidates=None):
        def command(*args,**kwargs):
            if args[-1]=='devices':return devices
            if 'connect' in args:return 'connected to '+args[-1]
            if args[-1]=='get-state':return states.get(args[-2],'offline')
            raise AssertionError(args)
        return (patch('blackflow.discovery._adb_candidates',return_value=adb_candidates or [Path('C:/MuMu/adb.exe')]),
                patch('blackflow.discovery._manager_addresses',return_value=list(known)),
                patch('blackflow.discovery._configured_addresses',return_value=list(configured)),
                patch('blackflow.discovery.run',side_effect=command))

    def detect(self,*args,**kwargs):
        a,b,c,d=self.detection(*args,**kwargs)
        with a,b,c,d:
            return discover('')

    def test_already_connected_local_device_does_not_need_config(self):
        self.assertEqual(self.detect('List of devices attached\n127.0.0.1:16416\tdevice\n',
                                     {'127.0.0.1:16416':'device'})[1],['127.0.0.1:16416'])

    def test_connected_localhost_serial_is_not_silently_renamed(self):
        self.assertEqual(self.detect('localhost:16416\tdevice',{'localhost:16416':'device'})[1],
                         ['localhost:16416'])

    def test_manager_connect_success_text_is_not_online_proof(self):
        self.assertEqual(self.detect('',{},known=['127.0.0.1:16384'])[1],[])

    def test_manager_and_config_endpoints_are_merged_and_deduplicated(self):
        addresses=['127.0.0.1:16384','127.0.0.1:16416']
        result=self.detect('',dict.fromkeys(addresses,'device'),known=addresses[:1],configured=addresses)
        self.assertEqual(result[1],addresses)

    def test_known_mumu_does_not_select_unrelated_device(self):
        result=self.detect('phone123\tdevice\n127.0.0.1:5555\tdevice',
                           {'phone123':'device','127.0.0.1:5555':'device'},known=['127.0.0.1:16384'])
        self.assertEqual(result[1],[])

    def test_offline_and_unauthorized_are_not_returned(self):
        result=self.detect('127.0.0.1:16384\toffline\n127.0.0.1:16416\tunauthorized',{},
                           known=['127.0.0.1:16384','127.0.0.1:16416'])
        self.assertEqual(result[1],[])

    def test_default_ports_can_find_unregistered_instance(self):
        self.assertEqual(self.detect('',{'127.0.0.1:16448':'device'})[1],['127.0.0.1:16448'])

    def test_two_connected_instances_are_returned_for_user_selection(self):
        self.assertEqual(self.detect('127.0.0.1:16384\tdevice\n127.0.0.1:16416\tdevice',
                                    {'127.0.0.1:16384':'device','127.0.0.1:16416':'device'})[1],
                         ['127.0.0.1:16384','127.0.0.1:16416'])

    def test_first_adb_failure_falls_back_and_report_survives(self):
        with tempfile.TemporaryDirectory() as root:
            report=Path(root)/'runtime/discovery.json'
            def command(*args,**kwargs):
                if str(args[0])=='bad.exe':raise OSError('cannot run')
                return '127.0.0.1:16384\tdevice' if args[-1]=='devices' else 'device'
            with patch('blackflow.discovery._adb_candidates',return_value=[Path('bad.exe'),Path('good.exe')]), \
                 patch('blackflow.discovery._manager_addresses',return_value=[]), \
                 patch('blackflow.discovery._configured_addresses',return_value=[]), \
                 patch('blackflow.discovery.run',side_effect=command):
                self.assertEqual(discover('',report_path=report)[0],'good.exe')
            self.assertTrue(json.loads(report.read_text(encoding='utf-8'))['messages'])

    def test_commands_use_manager_directory_hidden_window_and_timeout(self):
        fake=Mock(returncode=0,stdout=b'{"0":{}}',stderr=b'')
        with patch('blackflow.discovery.subprocess.run',return_value=fake) as command:
            self.assertEqual(run('C:/Custom/shell/MuMuManager.exe','info','-v','all'),'{"0":{}}')
        self.assertEqual(command.call_args.kwargs['cwd'],str(Path('C:/Custom/shell')))
        self.assertLessEqual(command.call_args.kwargs['timeout'],5)
        self.assertIn('creationflags',command.call_args.kwargs)

    def test_neutral_adb_path_can_reach_auto_discovery_validation(self):
        c=Config.load();c.address='auto';c.adb_path=''
        c.validate()
        c.address='127.0.0.1:16384'
        with self.assertRaisesRegex(ValueError,'找不到 ADB'):c.validate()
