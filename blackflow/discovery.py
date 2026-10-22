import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def run(*args):
    p = subprocess.run(list(map(str, args)), capture_output=True, timeout=8,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.stdout.decode("utf-8", errors="replace")


def discover(adb_path):
    """只查询 MuMu manager、已连接设备和本地实例配置，不扫描网络。"""
    adb = Path(adb_path)
    if not adb.is_file():
        options = [Path("D:/MuMuPlayer/nx_main/adb.exe"), Path("C:/Program Files/Netease/MuMuPlayer/nx_main/adb.exe")]
        adb = next((p for p in options if p.is_file()), adb)
    if not adb.is_file():
        raise RuntimeError("未发现 ADB，请手动选择 MuMu 的 adb.exe")
    addresses = []
    manager = adb.parent / "MuMuManager.exe"
    if manager.exists():
        try:
            info = json.loads(run(manager, "info", "-v", "all"))
            for idx, item in info.items():
                if not isinstance(item, dict) or not item.get("is_android_started"):
                    continue
                detail = json.loads(run(manager, "info", "-v", idx))
                if detail.get("adb_port"):
                    addresses.append(f"{detail.get('adb_host_ip', '127.0.0.1')}:{detail['adb_port']}")
        except (ValueError, subprocess.SubprocessError):
            pass
    configured = []
    for vm in (adb.parent.parent / "vms").glob("*/*.nemu"):
        try:
            for rule in ET.parse(vm).iter("Forwarding"):
                if rule.get("name") == "ADB_PORT":
                    configured.append(f"127.0.0.1:{rule.get('hostport')}")
        except ET.ParseError:
            continue
    for line in run(adb, "devices").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and parts[0] in configured:
            addresses.append(parts[0])
    if not addresses:
        for address in configured:
            try:
                if "connected to" in run(adb, "connect", address):
                    addresses.append(address)
            except subprocess.SubprocessError:
                continue
    return str(adb), list(dict.fromkeys(addresses))
