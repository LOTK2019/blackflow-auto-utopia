"""窗口版入口；命令行诊断输出写入当前用户数据目录。"""
import json
import sys
import traceback
from blackflow.config import ROOT


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = (ROOT / "运行日志.txt").open("a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout
    try:
        import app
        if "--image-check" in sys.argv:
            from blackflow.config import Config
            from blackflow.runner import Runner
            from blackflow.adb import load_image
            image_path = sys.argv[sys.argv.index("--image-check") + 1]
            runner = Runner(Config.load())
            frame = load_image(image_path)
            runner.adb.screenshot = lambda: frame
            runner.confirm_map_difficulty()
            result, description = runner.inspect_ideal()
            (ROOT / "图片检查.json").write_text(json.dumps({"source": "recorded-screenshot", "ocr": "ok",
                "difficulty": runner.config.difficulty, "ideal": result, "description": description},
                ensure_ascii=False, indent=2), encoding="utf-8")
        elif "--ui-check" in sys.argv:
            import tkinter as tk
            from blackflow.config import Config, APP_ROOT, BUNDLED_MAA
            root = tk.Tk()
            root.withdraw()
            ui = app.App(root)
            root.update()
            root.destroy()
            (ROOT / "界面检查.json").write_text(json.dumps({"ui": "ok", "data_dir": str(ROOT),
                "install_dir": str(APP_ROOT), "engine": str(BUNDLED_MAA),
                "adb": Config.load().adb_path}, ensure_ascii=False, indent=2), encoding="utf-8")
        elif "--package-check" in sys.argv:
            import tkinter as tk
            from blackflow.config import Config
            from blackflow.runner import Runner
            config = Config.load()
            config.validate()
            root = tk.Tk()
            root.withdraw()
            ui = app.App(root)
            root.update()
            runner = Runner(config)
            frame = runner.connect()  # 只截图，绝不点击或放弃当前探索。
            result, description = runner.inspect_ideal()
            root.destroy()
            (ROOT / "打包检查.json").write_text(json.dumps({"ui": "ok", "adb": "ok", "ocr": "ok",
                "ideal": result, "description": description}, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            app.main()
    except Exception:
        traceback.print_exc()
        if any(flag in sys.argv for flag in ('--diagnose','--run','--phase','--ui-check','--image-check','--package-check')):
            # 无控制台版本的命令行诊断必须非零退出，不能卡在 bootloader
            # 的未处理异常弹窗；原异常及错误现场已经保存在用户数据目录。
            raise SystemExit(1)
        raise
