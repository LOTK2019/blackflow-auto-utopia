import json
import re
from pathlib import Path
import cv2
import numpy as np
from .adb import load_image


def normalize(text):
    return re.sub(r"[\s·：:，,。‘’“”\"()（）ⅠⅡⅢ]", "", text)


class Vision:
    def __init__(self, maa_dir):
        self.resource = Path(maa_dir) / "resource"
        self.templates = {p.name: p for p in (self.resource / "template").rglob("*.png")}
        self.tasks = {}
        for p in (self.resource / "tasks").rglob("*.json"):
            try:
                self.tasks.update(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, UnicodeError):
                continue
        self._cache = {}
        self._ocr = None

    def task(self, name, seen=None):
        seen = set() if seen is None else set(seen)
        if name in seen:
            return {}
        seen.add(name)
        own = self.tasks.get(name, {})
        base = own.get("baseTask")
        if not base and "@" in name:
            base = name.split("@", 1)[1]
        return {**(self.task(base, seen) if base else {}), **own}

    def match(self, frame, task_name, threshold=None):
        task = self.task(task_name)
        templates = task.get("template", task_name + ".png")
        if isinstance(templates, str):
            templates = [templates]
        x, y, w, h = task.get("roi", [0, 0, 1280, 720])
        crop = frame[y:y+h, x:x+w]
        best = None
        for name in templates:
            path = self.templates.get(name)
            if not path or name == "empty.png":
                continue
            if name not in self._cache:
                self._cache[name] = load_image(path)
            templ = self._cache[name]
            if templ is None or crop.shape[0] < templ.shape[0] or crop.shape[1] < templ.shape[1]:
                continue
            result = cv2.matchTemplate(crop, templ, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(result)
            if score >= (threshold or task.get("templThreshold", .85)) and (best is None or score > best[2]):
                best = (x + loc[0] + templ.shape[1] / 2, y + loc[1] + templ.shape[0] / 2, score)
        return best

    def texts(self, frame, roi=None):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        x, y, w, h = roi or (0, 0, 1280, 720)
        result, _ = self._ocr(frame[y:y+h, x:x+w])
        return [{"text": t, "score": float(s), "x": float(np.mean(np.array(box)[:, 0])) + x,
                 "y": float(np.mean(np.array(box)[:, 1])) + y,
                 "box": [float(np.min(np.array(box)[:, 0])) + x, float(np.min(np.array(box)[:, 1])) + y,
                         float(np.max(np.array(box)[:, 0])) + x, float(np.max(np.array(box)[:, 1])) + y]}
                for box, t, s in (result or [])]

    @staticmethod
    def find(texts, word, exact=False):
        wanted = normalize(word)
        return next((t for t in texts if t["score"] >= .65 and
                     (normalize(t["text"]) == wanted if exact else wanted in normalize(t["text"]))), None)

    def map_difficulty(self, frame):
        # 地图左下角独立的难度徽记；放大后 OCR，避免读到旁边的收藏品数量。
        crop = cv2.resize(frame[680:720, 0:42], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        texts = self.texts(crop, (0, 0, crop.shape[1], crop.shape[0]))
        values = {int(t["text"]) for t in texts if t["score"] >= .8 and re.fullmatch(r"\d{1,2}", t["text"])}
        return (next(iter(values)) if len(values) == 1 else None), texts


IDEALS = ("黑流地脉", "倾斜沙丘", "去温栏", "微型胶囊", "储藏室", "易碎同盟", "停止点", "希望的沃土", "弥散虚雾", "美丽新大地")


def ideal_from_text(texts):
    """有明确名称 / 状态文字才判定；普通地图上没读到名字不等于无邦。"""
    joined = "|".join(normalize(t["text"]) for t in texts if t["score"] >= .7)
    for name in IDEALS:
        if name in joined:
            return "present", name
    if any(word in joined for word in ("无实托邦", "未发现实托邦", "未生成实托邦", "无理想域", "暂无实托邦")):
        return "absent", "明确的无实托邦状态文字"
    if "实托邦" in joined:
        return "present", "实托邦（名称未识别）"
    return "unknown", "未取得明确的实托邦状态"


IDEAL_ROI = (480, 0, 350, 78)


FLOORS = ("玻利瓦尔肤层", "甜美的伤口", "血色空脉", "受害者腐殖", "卡德霍之颅", "未萌生的摇篮", "盲目者所见")


def header_ideal(frame, texts, baseline=None, first_floor_only=True):
    """以楼层标题为锚点，检查其左侧通用图标槽，不依赖某一种实托邦的图案。"""
    title = next((t for t in texts if t["score"] >= .8 and
                  any(n in normalize(t["text"]) for n in FLOORS) and "box" in t), None)
    if title is None:
        return "unknown", {"reason": "未识别楼层标题"}
    if first_floor_only and "玻利瓦尔肤" not in normalize(title["text"]):
        return "unknown", {"reason": "当前不是第一层"}
    left = int(title["box"][0])
    if not 530 <= left <= 710 or title["box"][1] > 30:
        return "unknown", {"reason": "标题位置与已验证布局不同"}
    bounds = [left - 82, 0, left - 6, 64]
    x1, y1, x2, y2 = bounds
    crop = frame[y1:y2, x1:x2]
    # 各类图案不同，但都有位于标题左侧的独立徽记。小粒子不算完整徽记。
    bright = (crop.max(axis=2) > 155).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    symbols = [s for s in stats[1:] if s[cv2.CC_STAT_AREA] >= 16 and s[cv2.CC_STAT_WIDTH] >= 5 and s[cv2.CC_STAT_HEIGHT] >= 6]
    detail = {"title": title["text"], "title_left": left, "icon_box": bounds,
              "bright_pixels": int(bright.sum()), "symbols": len(symbols)}
    if symbols and bright.sum() >= 35:
        return "present", detail
    # 无邦样本的标题在 x≈573；有邦会为左侧图标让出空间。
    # 标题移位或任何可疑图案都不能作为无邦证据。
    if not first_floor_only and abs(title["x"] - 640) <= 12 and bright.sum() <= 3:
        return "absent", detail
    if baseline is not None and abs(title["x"] - 640) <= 12 and bright.sum() <= 3 and baseline.shape == crop.shape:
        delta = float(np.mean(cv2.absdiff(cv2.GaussianBlur(crop, (13, 13), 0), cv2.GaussianBlur(baseline, (13, 13), 0))))
        detail["baseline_difference"] = delta
        if delta < 14:
            return "absent", detail
    return "unknown", detail
