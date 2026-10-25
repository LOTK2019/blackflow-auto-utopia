"""参考 MAA WinAdapter/MuMu12Extra 的进程、注册表和安装路径规则。

上游：https://github.com/MaaAssistantArknights/MaaAssistantArknights/tree/dev-v2/src/MaaWpfGui
只查询本机；不启动实例、不关闭ADB server，不扫描网络。
"""
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def run(*args, timeout=5):
    executable = Path(args[0])
    p = subprocess.run(list(map(str, args)), capture_output=True, timeout=timeout,
                       cwd=str(executable.parent),
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    output = (p.stdout + b'\n' + p.stderr).decode('utf-8-sig', errors='replace').strip()
    if p.returncode:
        raise RuntimeError(f'{executable.name} 返回 {p.returncode}：{output[:400]}')
    return p.stdout.decode('utf-8-sig', errors='replace').strip() or output


def _process_paths():
    """从运行进程反推路径；单个进程无权限时继续其他进程。"""
    if os.name != 'nt':
        return []
    import ctypes
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    result = []
    names = {'mumuplayer.exe', 'mumunxdevice.exe', 'mumunxmain.exe', 'mumumanager.exe', 'nemuheadless.exe'}
    try:
        entry = Entry(); entry.dwSize = ctypes.sizeof(Entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() in names:
                process = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        length = wintypes.DWORD(len(buffer))
                        if kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                            result.append(Path(buffer.value))
                    finally:
                        kernel.CloseHandle(process)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def _registry_paths():
    if os.name != 'nt':
        return []
    import winreg
    names = ('MuMuPlayer-15.0', 'MuMuPlayer-12.0', 'MuMuPlayer',
             'MuMuPlayerGlobal-15.0', 'MuMuPlayerGlobal-12.0', 'YXArkNights-12.0')
    paths = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for name in names:
                try:
                    with winreg.OpenKey(hive, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'+name,
                                        0, winreg.KEY_READ | view) as key:
                        for value in ('InstallLocation', 'DisplayIcon', 'UninstallString'):
                            try:
                                text = os.path.expandvars(str(winreg.QueryValueEx(key, value)[0])).strip()
                                if value != 'InstallLocation':
                                    match = re.match(r'^"([^"]+)"|^(.+?\.exe)(?:\s|,|$)', text, re.I)
                                    if not match:
                                        continue
                                    text = match.group(1) or match.group(2)
                                paths.append(Path(text.strip('"')))
                            except OSError:
                                continue
                except OSError:
                    continue
    return paths


def _locations(path):
    path = Path(path)
    folder = path.parent if path.suffix.lower() == '.exe' else path
    for base in (folder, *list(folder.parents)[:3]):
        for relative in ('adb.exe', 'nx_main/adb.exe', 'shell/adb.exe',
                         'vmonitor/bin/adb_server.exe', 'emulator/nemu/vmonitor/bin/adb_server.exe'):
            yield base / relative


def _adb_candidates(adb_path):
    paths = []
    provided = str(adb_path).strip().strip('"')
    if provided:
        provided_path = Path(os.path.expandvars(provided))
        if provided_path.name.lower() in ('adb.exe', 'adb_server.exe', 'hd-adb.exe', 'nox_adb.exe'):
            paths.append(provided_path)
        paths.extend(_locations(provided_path))
    for path in (*_process_paths(), *_registry_paths()):
        paths.extend(_locations(path))
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(env):
            for name in ('MuMu', 'MuMuPlayer', 'MuMuPlayer-12.0', 'MuMuPlayer-15.0', 'MuMuPlayerGlobal-12.0'):
                paths.extend(_locations(Path(os.environ[env])/'Netease'/name))
    seen = set()
    result = []
    for path in paths:
        key = str(path).lower()
        if key not in seen and path.is_file():
            seen.add(key); result.append(path.resolve())
    return result


def _json_output(text):
    decoder = json.JSONDecoder()
    for match in re.finditer(r'[\[{]', text):
        try:
            return decoder.raw_decode(text[match.start():])[0]
        except ValueError:
            continue
    raise ValueError('管理器没有返回有效 JSON')


def _instances(data):
    if isinstance(data, list):
        return [(str(item.get('index', i)), item) for i,item in enumerate(data) if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    if 'adb_port' in data or 'index' in data:
        return [(str(data.get('index', 0)), data)]
    for name in ('data', 'instances', 'players', 'result'):
        if isinstance(data.get(name), (list, dict)):
            return _instances(data[name])
    return [(str(k), v) for k,v in data.items() if isinstance(v, dict) and str(k).isdigit()]


def _endpoint(host, port):
    try:
        number = int(port)
    except (ValueError, TypeError):
        return None
    if not 1 <= number <= 65535:
        return None
    host = str(host or '127.0.0.1').lower()
    if host in ('0.0.0.0', 'localhost'):
        host = '127.0.0.1'
    return f'{host}:{number}' if host == '127.0.0.1' else None


def _manager_addresses(adb, log):
    result = []
    managers = [adb.parent/'MuMuManager.exe', adb.parent.parent/'nx_main/MuMuManager.exe',
                adb.parent.parent/'shell/MuMuManager.exe']
    for manager in dict.fromkeys(managers):
        if not manager.is_file():
            continue
        try:
            info = _instances(_json_output(run(manager, 'info', '-v', 'all')))
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            log('MuMu 管理器查询失败，继续配置/ADB回退：'+str(exc)); continue
        for idx, item in info:
            if item.get('is_android_started') is False:
                log(f'MuMu 实例 {idx} 安卓尚未启动'); continue
            endpoint = _endpoint(item.get('adb_host_ip'), item.get('adb_port'))
            if not endpoint:
                try:
                    detail = _json_output(run(manager, 'info', '-v', idx))
                    entries = _instances(detail)
                    detail = next((v for k,v in entries if k == idx), entries[0][1] if entries else detail)
                    if isinstance(detail, dict):
                        endpoint = _endpoint(detail.get('adb_host_ip'), detail.get('adb_port'))
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                    log(f'MuMu 实例 {idx} 查询失败：{exc}')
            if not endpoint:
                try:
                    output = run(manager, 'adb', '-v', idx)
                    match = re.search(r'(?:127\.0\.0\.1|localhost):(\d+)', output)
                    if match:
                        endpoint = _endpoint('127.0.0.1', match.group(1))
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass
            if endpoint:
                result.append(endpoint)
    return list(dict.fromkeys(result))


def _configured_addresses(adb, log):
    results = []
    for base in (adb.parent, *list(adb.parent.parents)[:3]):
        vms = base/'vms'
        if not vms.is_dir():
            continue
        for vm in vms.glob('*/*.nemu'):
            try:
                for rule in ET.parse(vm).iter('Forwarding'):
                    if rule.get('name', '').upper() == 'ADB_PORT':
                        results.append(_endpoint('127.0.0.1', rule.get('hostport')))
            except (OSError, ET.ParseError) as exc:
                log('MuMu 实例XML配置不可读：'+str(exc))
        for file in vms.glob('*/configs/vm_config.json'):
            try:
                data = json.loads(file.read_text(encoding='utf-8-sig'))
                results.append(_endpoint('127.0.0.1', data.get('vm', {}).get('nat', {}).get('port_forward', {}).get('adb', {}).get('host_port')))
            except (OSError, ValueError, AttributeError) as exc:
                log('MuMu 实例JSON配置不可读：'+str(exc))
    return list(dict.fromkeys(a for a in results if a))


def _devices(text):
    devices = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ('device', 'offline', 'unauthorized'):
            serial = parts[0]
            match = re.fullmatch(r'(?:127\.0\.0\.1|localhost):(\d+)', serial)
            if match:
                # serial必须与ADB原样一致，localhost不是已连接的127.0.0.1别名。
                if not _endpoint('127.0.0.1', match.group(1)):
                    continue
            if serial:
                devices[serial] = parts[1]
    return devices


def _discover(adb_path, log):
    candidates = _adb_candidates(adb_path)
    if not candidates:
        raise RuntimeError('未发现 ADB。请启动MuMu，或手填模拟器的 adb.exe（新版nx_main、旧版shell目录）；支持自定义安装路径')
    errors = []
    fallback = candidates[0]
    for adb in candidates:
        log('发现 ADB：'+str(adb))
        try:
            devices = _devices(run(adb, 'devices'))
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(str(exc)); log('ADB 查询失败，尝试其他安装：'+str(exc)); continue
        known = list(dict.fromkeys(_manager_addresses(adb, log)+_configured_addresses(adb, log)))
        targets = known or [a for a,state in devices.items() if state == 'device' and
                             (a.startswith(('127.0.0.1:', 'localhost:')) or re.fullmatch(r'emulator-\d+', a))]
        if not targets:
            targets = [f'127.0.0.1:{16384+32*i}' for i in range(7)] + ['127.0.0.1:7555']
        found = []
        for address in targets:
            try:
                if devices.get(address) != 'device':
                    if devices.get(address) == 'unauthorized':
                        log(f'{address} 未授权，请检查模拟器ADB设置'); continue
                    run(adb, 'connect', address, timeout=2)
                if run(adb, '-s', address, 'get-state', timeout=2).strip() == 'device':
                    found.append(address)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                log(f'{address} 不可连接：{exc}')
        if found:
            return str(adb), list(dict.fromkeys(found))
        fallback = adb
    if errors and len(errors) == len(candidates):
        raise RuntimeError('检测到ADB但全部执行失败：'+'；'.join(errors))
    log('未发现在线MuMu实例，请开启实例并启用本地ADB；本次未自动启动或重置模拟器')
    return str(fallback), []


def discover(adb_path, log=lambda _: None, report_path=None):
    report = {'input_adb': str(adb_path), 'messages': []}
    def record(message):
        report['messages'].append(message)
        log(message)
    try:
        adb, addresses = _discover(adb_path, record)
        report.update(adb=adb, addresses=addresses)
        return adb, addresses
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if report_path is not None:
            try:
                path = Path(report_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError as exc:
                log('保存连接诊断失败：'+str(exc))
