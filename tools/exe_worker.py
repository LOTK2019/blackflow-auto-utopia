"""控制台子进程入口，由界面隐藏启动并通过管道通信。"""
import ctypes
import json
import os
from pathlib import Path
import sys
from blackflow.config import Config, ROOT, read_blackflow_strategy
from blackflow.maa_worker import emit, run
from blackflow.errors import error_event


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if sys.argv[1] in ("--check-core", "--check-engine"):
            config = Config.load()
            with os.add_dll_directory(config.maa_dir):
                core = ctypes.WinDLL(str(Path(config.maa_dir) / "MaaCore.dll"))
                core.AsstGetVersion.restype = ctypes.c_char_p
                emit("version", version=core.AsstGetVersion().decode())
                if sys.argv[1] == "--check-engine":
                    read_blackflow_strategy(config.maa_dir)
                    user_dir = ROOT / "runtime/engine-check"
                    user_dir.mkdir(parents=True, exist_ok=True)
                    for name in ("AsstSetUserDir", "AsstLoadResource"):
                        method = getattr(core, name)
                        method.argtypes, method.restype = [ctypes.c_char_p], ctypes.c_bool
                    if not core.AsstSetUserDir(str(user_dir).encode()) or not core.AsstLoadResource(config.maa_dir.encode()):
                        raise RuntimeError("内置 MAA 资源加载失败")
                    emit("done", phase="engine-check", engine=config.maa_dir, resources_loaded=True)
        else:
            config = Config(**json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
            run(config, sys.argv[1])
    except Exception as exc:
        emit("error", **error_event(exc))
        raise SystemExit(1)
