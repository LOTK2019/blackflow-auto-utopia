"""将已验证的原版 MAA 核心和资源准备到 vendor/maa；不复制 GUI、账号配置或日志。"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil

NATIVE_DLLS = ("MaaCore.dll", "MaaUtils.dll", "opencv_world4_maa.dll", "fastdeploy_ppocr_maa.dll",
               "onnxruntime_maa.dll", "DirectML.dll")


def stage(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError("引擎来源与目标不能相同")
    for name in NATIVE_DLLS:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    with os.add_dll_directory(str(source)):
        core = ctypes.WinDLL(str(source / "MaaCore.dll"))
        core.AsstGetVersion.restype = ctypes.c_char_p
        version = core.AsstGetVersion().decode()
    commits = {'v6.20.0':'a0f9ebfaabfaba3fc4dd7cc12dbfa323b45c9e39',
               'v6.20.1':'d94dd007aca3b519395fb1f0aee26c7bd5ba5d5f'}
    if version not in commits:
        raise ValueError(f"此发布脚本仅支持已固定来源的引擎，来源实际为 {version}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in NATIVE_DLLS:
        shutil.copy2(source / name, destination / name)
    shutil.copytree(source / "resource", destination / "resource", dirs_exist_ok=True)
    manifest = {"version": version, "source_tag": version,
                "source_commit": commits[version],
                "source_url": f"https://github.com/MaaAssistantArknights/MaaAssistantArknights/tree/{version}",
                "sha256": {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in NATIVE_DLLS}}
    (destination / "engine.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"version": version, "destination": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--destination", default="vendor/maa")
    args = parser.parse_args()
    stage(args.source, args.destination)
