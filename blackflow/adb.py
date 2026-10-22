import subprocess
import threading
import tempfile
import uuid
from pathlib import Path
import cv2
import numpy as np


class Stopped(Exception):
    pass


class ADB:
    """所有输入只发往 Android，不接触 Windows 鼠标和键盘。"""

    def __init__(self, executable, address, stop=None):
        self.executable, self.address = executable, address
        self.stop = stop or threading.Event()
        self.size = None

    def command(self, *args, timeout=20):
        if self.stop.is_set():
            raise Stopped()
        proc = subprocess.run([self.executable, "-s", self.address, *map(str, args)], capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
        return proc.stdout

    def connect(self):
        proc = subprocess.run([self.executable, "connect", self.address], capture_output=True, timeout=15,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.command("shell", "echo", "connected")
        return proc.stdout.decode("utf-8", errors="replace")

    def screenshot(self):
        errors = []
        raw = None
        # 有些模拟器的 ADB exec-out 会成功退出却返回空数据；重试后改走文件拉取。
        for attempt in range(3):
            method = "exec-out" if attempt < 2 else "设备文件 + pull"
            try:
                data = (self.command("exec-out", "screencap", "-p") if attempt < 2 else self._screenshot_file())
                raw = decode_image(data, f"ADB 截图（{method}）")
                break
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{method}: {exc}")
                if attempt < 2:
                    self.wait(.5)
        if raw is None:
            raise RuntimeError(f"无法取得模拟器截图（设备 {self.address}）。请检查 ADB 地址是否指向正在运行的游戏实例，"
                               "并尝试使用模拟器自带的 adb.exe。详情：" + "；".join(errors))
        h, w = raw.shape[:2]
        if abs(w / h - 16 / 9) > .025:
            raise RuntimeError(f"需要 16:9 横屏，当前为 {w}×{h}")
        if raw.std() < 2:
            raise RuntimeError("截图为黑屏，请等待模拟器 / 游戏启动完成")
        self.size = (w, h)
        return cv2.resize(raw, (1280, 720), interpolation=cv2.INTER_AREA)

    def _screenshot_file(self):
        remote = f"/data/local/tmp/blackflow-{uuid.uuid4().hex}.png"
        try:
            self.command("shell", "screencap", "-p", remote)
            with tempfile.TemporaryDirectory(prefix="blackflow-shot-") as folder:
                local = Path(folder) / "screen.png"
                self.command("pull", remote, str(local))
                if not local.is_file():
                    raise RuntimeError("ADB pull 未生成截图文件")
                return local.read_bytes()
        finally:
            try:
                self.command("shell", "rm", "-f", remote)
            except (RuntimeError, OSError, subprocess.TimeoutExpired, Stopped):
                pass

    def tap(self, x, y):
        if self.size is None:
            self.screenshot()
        w, h = self.size
        self.command("shell", "input", "tap", round(x * w / 1280), round(y * h / 720))

    def swipe(self, x1, y1, x2, y2, duration=450):
        if self.size is None:
            self.screenshot()
        w, h = self.size
        self.command("shell", "input", "swipe", round(x1 * w / 1280), round(y1 * h / 720),
                     round(x2 * w / 1280), round(y2 * h / 720), duration)

    def wait(self, seconds):
        if self.stop.wait(seconds):
            raise Stopped()


def decode_image(data, source):
    if not data:
        raise RuntimeError(f"{source}返回了空图片数据（0 字节）")
    try:
        raw = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise RuntimeError(f"{source}无法解码（{len(data)} 字节）") from exc
    if raw is None:
        raise RuntimeError(f"{source}不是有效图片（{len(data)} 字节）")
    return raw


def load_image(path):
    path = Path(path)
    return decode_image(path.read_bytes(), f"图片文件 {path}")


def save_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cv2.imencode(".png", image)[1].tobytes())
