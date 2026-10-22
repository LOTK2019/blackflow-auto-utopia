"""自适应窗口与可滚动配置容器，不涉及游戏操作。"""
import os
import tkinter as tk
from tkinter import ttk


def enable_dpi_awareness():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass  # 打包清单已声明 DPI 感知时，Windows 会拒绝重复设置。


def work_area(root):
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def initial_geometry(area, scale=1):
    x, y, width, height = area
    margin = min(24, max(8, width // 40), max(8, height // 40))
    max_w, max_h = max(1, width - margin * 2), max(1, height - margin * 2)
    min_w, min_h = min(round(560 * scale), max_w), min(round(420 * scale), max_h)
    w = max(min_w, min(round(1180 * scale), round(width * .9), max_w))
    h = max(min_h, min(round(840 * scale), round(height * .88), max_h))
    return w, h, x + (width - w) // 2, y + (height - h) // 2, min_w, min_h


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg="#141d24", highlightthickness=0, width=1, height=1)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._region)
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=max(1, event.width))

    def _region(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, event):
        widget = event.widget
        while hasattr(widget, "master"):
            if widget is self:
                if self.content.winfo_height() > self.canvas.winfo_height():
                    self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return "break"
            widget = widget.master

    def see(self, widget):
        self.update_idletasks()
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        bottom = top + widget.winfo_height()
        current = self.canvas.canvasy(0)
        viewport = self.canvas.winfo_height()
        total = max(1, self.content.winfo_height())
        if top < current:
            self.canvas.yview_moveto(max(0, top - 8) / total)
        elif bottom > current + viewport:
            self.canvas.yview_moveto(max(0, bottom - viewport + 8) / total)
