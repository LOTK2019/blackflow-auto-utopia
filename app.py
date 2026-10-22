r"""运行方式：.venv\Scripts\python.exe app.py"""
import argparse
import json
import queue
import traceback
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
from blackflow.config import Config, ROOT, REWARD_TARGETS, BUNDLED_MAA
from blackflow.errors import describe_error
from blackflow.discovery import discover
from blackflow.runner import Runner
from blackflow.adb import ADB, save_image
from blackflow.vision import Vision, ideal_from_text
from blackflow.ui_layout import ScrollFrame, enable_dpi_awareness, initial_geometry, work_area
from blackflow.strategy import PREPARE_METHODS
from blackflow.rewards import reward_plan, REWARD_DESCRIPTIONS, DEFAULT_REWARD_ORDER
from blackflow.animals import ANIMAL_TYPES, ANIMAL_EFFECTS


class App:
    def __init__(self, root):
        self.root, self.cfg = root, Config.load()
        self.runner = None
        self.bus = queue.Queue()
        self.thread = None
        self.vars = {}
        self.fields = {}
        self.last_frame = None
        self._layout_job = None
        self._preview_job = None
        self._mode = None
        self.scale = max(.75, root.winfo_fpixels("1i") / 96)
        root.title("黑流树海 · 自动实托邦")
        w, h, x, y, min_w, min_h = initial_geometry(work_area(root), self.scale)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(min_w, min_h)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#141d24")
        style.configure("TLabel", background="#141d24", foreground="#dce9e9", font=("Microsoft YaHei UI", 10))
        style.configure("TLabelframe", background="#141d24", foreground="#6dd5bb")
        style.configure("TLabelframe.Label", background="#141d24", foreground="#6dd5bb", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("TButton", padding=7, font=("Microsoft YaHei UI", 10))
        style.configure("TCheckbutton", background="#141d24", foreground="#dce9e9")
        main = ttk.Frame(root, padding=12)
        self.main_frame = main
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        title = ttk.Label(main, text="黑流树海 / 自动实托邦", font=("Microsoft YaHei UI", 20, "bold"))
        self.title_label = title
        title.grid(row=0, column=0, sticky="ew")
        self.wrap_label(title)
        subtitle = ttk.Label(main, text="准备局三层烧水 → 文明开化正式局 → 一层有邦即停；无邦重新烧水")
        self.subtitle = subtitle
        subtitle.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        self.wrap_label(subtitle)
        self.body = ttk.Frame(main)
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.rowconfigure(1, weight=1)
        self.tab_bar = ttk.Frame(self.body)
        self.tab = tk.StringVar(value="config")
        for column, (label, value) in enumerate((("开局配置", "config"), ("截图与日志", "monitor"))):
            ttk.Radiobutton(self.tab_bar, text=label, value=value, variable=self.tab,
                            style="Toolbutton", command=self.show_tab).grid(row=0, column=column, sticky="ew", padx=2)
            self.tab_bar.columnconfigure(column, weight=1)
        self.form_scroller = ScrollFrame(self.body)
        self.monitor = ttk.Frame(self.body)
        left, right = self.form_scroller.content, self.monitor
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=2)
        right.rowconfigure(2, weight=3)
        conn = ttk.LabelFrame(left, text="模拟器连接 · MuMu / 雷电", padding=10)
        conn.pack(fill="x", pady=(0, 10))
        self.field(conn, "adb_path", "ADB 路径", self.cfg.adb_path)
        self.field(conn, "address", "ADB 地址", self.cfg.address)
        ttk.Button(conn, text="自动发现 MuMu", command=self.detect).grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)
        self.note(conn, "地址可手填，例如 127.0.0.1:16384；填 auto 自动连接", 3)
        formal = ttk.LabelFrame(left, text="正式局 · 固定文明开化分队", padding=10)
        formal.pack(fill="x", pady=(0, 10))
        self.field(formal, "difficulty", "保密等级", str(self.cfg.difficulty))
        self.field(formal, "roles", "开局组合", self.cfg.roles, ["灵活部署", "先手必胜", "稳扎稳打", "取长补短", "坚不可摧", "随心所欲"])
        self.field(formal, "six_star", "首选六星", self.cfg.six_star)
        self.field(formal, "four_1", "指定四星 1", self.cfg.four_stars[0])
        self.field(formal, "four_2", "指定四星 2", self.cfg.four_stars[1])
        self.field(formal, "fallback", "备选六星", "、".join(self.cfg.fallback_six_stars))
        for row, (key, label) in enumerate([
            ("use_support", "六星优先使用助战"),
            ("use_nonfriend_support", "允许非好友助战"),
            ("allow_other_six_star", "允许回退到其他同职业六星"),
        ], start=7):
            self.vars[key] = tk.BooleanVar(value=getattr(self.cfg, key))
            ttk.Checkbutton(formal, text=label, variable=self.vars[key]).grid(row=row, columnspan=2, sticky="w", pady=2)
        self.note(formal, "四星找不到就停止。奖励按下方优先级和开关处理。", 10)
        reward_box = ttk.LabelFrame(left,text='开局奖励优先级 · 从上到下',padding=10)
        reward_box.pack(fill='x',pady=(0,10))
        reward_box.columnconfigure(0,weight=1)
        self.reward_order, strict = reward_plan(self.cfg)
        self.reward_list = tk.Listbox(reward_box,height=6,width=1,exportselection=False,
            bg='#0c1218',fg='#dce9e9',selectbackground='#246e65',font=('Microsoft YaHei UI',10))
        self.reward_list.grid(row=0,column=0,sticky='ew')
        reward_scroll = ttk.Scrollbar(reward_box,orient='vertical',command=self.reward_list.yview)
        reward_scroll.grid(row=0,column=1,sticky='ns')
        self.reward_list.configure(yscrollcommand=reward_scroll.set)
        self.reward_detail = tk.StringVar()
        detail = ttk.Label(reward_box,textvariable=self.reward_detail)
        detail.grid(row=1,column=0,columnspan=2,sticky='ew',pady=4)
        self.wrap_label(detail)
        self.reward_list.bind('<<ListboxSelect>>',lambda event:self.describe_reward())
        buttons = ttk.Frame(reward_box)
        buttons.grid(row=2,column=0,columnspan=2,sticky='ew')
        for col,(label,command) in enumerate((('上移',lambda:self.move_reward(-1)),('下移',lambda:self.move_reward(1)),
                                             ('恢复默认',self.reset_rewards))):
            ttk.Button(buttons,text=label,command=command).grid(row=0,column=col,sticky='ew',padx=2)
            buttons.columnconfigure(col,weight=1)
        self.vars['require_first_reward'] = tk.BooleanVar(value=strict)
        ttk.Checkbutton(reward_box,text='必须使用第一项（未出现就重新烧水）',
            variable=self.vars['require_first_reward']).grid(row=3,column=0,columnspan=2,sticky='w',pady=4)
        self.refresh_rewards()
        node_box = ttk.LabelFrame(left, text='第一层有效节点筛选', padding=10)
        node_box.pack(fill='x', pady=(0,10))
        self.vars['node_filter_enabled'] = tk.BooleanVar(value=self.cfg.node_filter_enabled)
        ttk.Checkbutton(node_box,text='启用有效节点数量要求',variable=self.vars['node_filter_enabled']).grid(row=0,column=0,columnspan=2,sticky='w')
        self.field(node_box,'min_effective_nodes','最低节点数',str(self.cfg.min_effective_nodes))
        self.note(node_box,'默认关闭；排除空地，未达标重新烧水。统计不确定时先重扫。',2)
        animal_box=ttk.LabelFrame(left,text='可选 · 种植数量要求（0 表示不要求）',padding=10)
        animal_box.pack(fill='x',pady=(0,10))
        for key,name in (('cat','猫'),('dog','狗'),('cerberus','三头犬')):
            self.field(animal_box,'count_'+key,name,str(self.cfg.animal_counts[name]))
        self.note(animal_box,'不看收获顺序；多出的动物允许。默认全部为0，没出动物也不重烧。羽蛇效果在奖励列表中筛选。',3)
        self.note(animal_box,'猫：初始源石锭+5；狗：希望+1；三头犬：通过两层后增加奖励选择次数。',4)
        prep = ttk.LabelFrame(left, text="准备局", padding=10)
        prep.pack(fill="x")
        self.field(prep, "prepare_squad", "准备分队", self.cfg.prepare_squad, ["堡垒战术分队", "特勤分队"])
        self.field(prep, "prepare_roles", "准备组合", self.cfg.prepare_roles, ["坚不可摧", "稳扎稳打"])
        self.field(prep,'prepare_method','准备方式',self.cfg.prepare_method,list(PREPARE_METHODS))
        self.note(prep, "黄商店种植：优先寻找秘境行商并尝试种植，通过两层；动物数量为0时不要求收获。也可选择绿商店投资。", 3)
        self.note(prep, "持续循环，找到实托邦并满足已启用的筛选，或手动停止时结束", 4)
        self.status = tk.StringVar(value="等待开始 · 请先进入黑流树海主题主界面")
        status_label = ttk.Label(right, textvariable=self.status, font=("Microsoft YaHei UI", 12, "bold"))
        status_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.wrap_label(status_label)
        self.preview_canvas = tk.Canvas(right, bg="#0c1218", highlightthickness=0, width=1, height=1)
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.queue_preview)
        log_frame = ttk.Frame(right)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.logs = tk.Text(log_frame, height=1, width=1, bg="#0c1218", fg="#bed7cf", insertbackground="white", font=("Consolas", 9), wrap="word", state="disabled")
        self.logs.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.logs.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.logs.configure(yscrollcommand=log_scroll.set)
        self.controls = ttk.Frame(main)
        self.controls.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.start_button = ttk.Button(self.controls, text="开始自动烧水 / 筛选", command=self.start)
        self.control_buttons = [self.start_button,
            ttk.Button(self.controls, text="立即停止", command=self.stop),
            ttk.Button(self.controls, text="仅连接 / 截图诊断", command=self.diagnose),
            ttk.Button(self.controls, text="保存配置", command=self.save)]
        root.bind("<Configure>", self.queue_layout, add="+")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after_idle(self.reflow)
        root.after(100, self.drain)

    def field(self, box, key, label, value, choices=None):
        row = len(box.grid_slaves(column=0))
        line = ttk.Frame(box)
        line.grid(row=row, column=0, columnspan=2, sticky="ew", pady=3)
        line.columnconfigure(1, weight=1)
        caption = ttk.Label(line, text=label)
        self.vars[key] = tk.StringVar(value=value)
        widget = ttk.Combobox(line, textvariable=self.vars[key], values=choices, width=1) if choices else ttk.Entry(line, textvariable=self.vars[key], width=1)
        self.fields[key] = widget
        def arrange(event):
            stacked = event.width < 360 * self.scale
            caption.grid(row=0, column=0, columnspan=2 if stacked else 1, sticky="w", padx=(0, 8), pady=(0, 2) if stacked else 0)
            widget.grid(row=1 if stacked else 0, column=0 if stacked else 1, columnspan=2 if stacked else 1, sticky="ew")
        line.bind("<Configure>", arrange)
        widget.bind("<FocusIn>", lambda event: self.form_scroller.see(event.widget), add="+")
        box.columnconfigure(1, weight=1)
        return widget

    def refresh_rewards(self, selected=0):
        self.reward_list.delete(0,'end')
        for index,name in enumerate(self.reward_order,1):
            self.reward_list.insert('end',f'{index}. {name}')
        self.reward_list.selection_set(selected)
        self.reward_list.see(selected)
        self.describe_reward()

    def describe_reward(self):
        selected=self.reward_list.curselection()
        if selected:
            self.reward_detail.set(REWARD_DESCRIPTIONS[self.reward_order[selected[0]]])

    def move_reward(self, direction):
        selection=self.reward_list.curselection()
        if not selection:return
        index=selection[0];new=index+direction
        if 0<=new<len(self.reward_order):
            self.reward_order[index],self.reward_order[new]=self.reward_order[new],self.reward_order[index]
            self.refresh_rewards(new)

    def reset_rewards(self):
        self.reward_order=list(DEFAULT_REWARD_ORDER)
        self.refresh_rewards()

    @staticmethod
    def wrap_label(label):
        label.configure(wraplength=300)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(80, event.width)))

    def note(self, box, text, row):
        label = ttk.Label(box, text=text)
        label.grid(row=row, column=0, columnspan=2, sticky="ew", pady=3)
        self.wrap_label(label)

    def queue_layout(self, event):
        if event.widget is self.root:
            if self._layout_job is not None:
                self.root.after_cancel(self._layout_job)
            self._layout_job = self.root.after(60, self.reflow)

    def reflow(self):
        self._layout_job = None
        width = self.main_frame.winfo_width()
        mode = "wide" if width >= 1000 * self.scale else "compact"
        if mode != self._mode:
            self._mode = mode
            self.show_tab()
        # 按按钮实际字体宽度决定列数，避免高 DPI 下不必要地排成四行。
        needed = max(button.winfo_reqwidth() for button in self.control_buttons) + 12
        count = 4 if width >= needed * 4 else (2 if width >= needed * 2 else 1)
        if self.root.winfo_height() < 600 * self.scale:
            self.subtitle.grid_remove()
        else:
            self.subtitle.grid()
        self.title_label.configure(font=("Microsoft YaHei UI", 16 if width < 700 * self.scale else 20, "bold"))
        for col in range(4):
            self.controls.columnconfigure(col, weight=1 if col < count else 0, uniform="actions" if col < count else "")
        for index, button in enumerate(self.control_buttons):
            button.grid(row=index // count, column=index % count, sticky="ew", padx=3, pady=3)

    def show_tab(self):
        wide = self._mode == "wide"
        self.body.columnconfigure(0, weight=1, uniform="panels" if wide else "")
        self.body.columnconfigure(1, weight=1 if wide else 0, uniform="panels" if wide else "")
        self.form_scroller.grid_remove()
        self.monitor.grid_remove()
        if wide:
            self.tab_bar.grid_remove()
            self.form_scroller.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
            self.monitor.grid(row=1, column=1, sticky="nsew")
        else:
            self.tab_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            panel = self.form_scroller if self.tab.get() == "config" else self.monitor
            panel.grid(row=1, column=0, sticky="nsew", padx=0)
        self.queue_preview()

    def queue_preview(self, event=None):
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(60, self.draw_preview)

    def draw_preview(self):
        self._preview_job = None
        canvas = self.preview_canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.delete("all")
        if width < 2 or height < 2:
            return
        if self.last_frame is None:
            canvas.create_text(width / 2, height / 2, text="截图预览", fill="#bed7cf")
            return
        source = self.last_frame
        ratio = min(width / source.width, height / source.height)
        size = max(1, int(source.width * ratio)), max(1, int(source.height * ratio))
        self.photo = ImageTk.PhotoImage(source.resize(size, Image.Resampling.LANCZOS))
        canvas.create_image(width / 2, height / 2, image=self.photo, anchor="center")

    def read(self):
        import re
        c = Config(**{**self.cfg.__dict__})
        for key in ("adb_path", "address", "roles", "six_star", "prepare_squad", "prepare_roles", "prepare_method"):
            setattr(c, key, self.vars[key].get().strip())
        if BUNDLED_MAA:
            c.maa_dir = str(BUNDLED_MAA)
        for key in ("difficulty",):
            setattr(c, key, int(self.vars[key].get()))
        for key in ("use_support", "use_nonfriend_support", "allow_other_six_star"):
            setattr(c, key, self.vars[key].get())
        c.node_filter_enabled = self.vars['node_filter_enabled'].get()
        c.reward_priority = list(self.reward_order)
        c.require_first_reward = self.vars['require_first_reward'].get()
        c.reward_target = '默认排序'
        c.animal_counts = {name:int(self.vars['count_'+key].get()) for key,name in (('cat','猫'),('dog','狗'),('cerberus','三头犬'))}
        if c.node_filter_enabled:
            c.min_effective_nodes = int(self.vars['min_effective_nodes'].get())
        c.four_stars = [self.vars[k].get().strip() for k in ("four_1", "four_2")]
        c.fallback_six_stars = [n.strip() for n in re.split(r"[,，、;；]", self.vars["fallback"].get()) if n.strip()]
        return c

    def save(self):
        try:
            self.cfg = self.read()
            self.cfg.validate()
            self.cfg.save()
            self.bus.put(("log", "配置已保存"))
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))

    def background(self, fn):
        if self.thread and self.thread.is_alive():
            messagebox.showinfo("任务进行中", "请先停止当前任务")
            return

        def task():
            try:
                fn()
            except Exception as exc:
                with (ROOT / "错误详情.log").open("a", encoding="utf-8") as detail:
                    traceback.print_exc(file=detail)
                self.bus.put(("log", describe_error(exc) + f"；完整错误：{ROOT / '错误详情.log'}"))
                self.bus.put(("status", "已停止：" + describe_error(exc)))
            finally:
                self.bus.put(("idle", None))

        self.start_button.configure(state="disabled")
        self.thread = threading.Thread(target=task, daemon=True)
        self.thread.start()

    def detect(self):
        path = self.vars["adb_path"].get()

        def job():
            adb, addresses = discover(path)
            self.bus.put(("detected", (adb, addresses)))

        self.background(job)

    def diagnose(self):
        try:
            config = self.read()
            config.validate(check_strategy=False)
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        def job():
            self.runner = Runner(config, lambda t: self.bus.put(("log", t)), lambda i: self.bus.put(("image", i)))
            frame = self.runner.connect()
            self.runner.require_theme(frame)
            self.bus.put(("status", "连接与截图正常，已确认黑流树海主题主界面"))

        self.background(job)
        self.tab.set("monitor")
        self.show_tab()

    def start(self):
        try:
            config = self.read()
            config.validate()
            config.save()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        def job():
            self.runner = Runner(config, lambda t: self.bus.put(("log", t)), lambda i: self.bus.put(("image", i)))
            self.runner.run()

        self.background(job)
        self.tab.set("monitor")
        self.show_tab()

    def stop(self):
        if self.runner:
            self.runner.stop_now()
        self.status.set("正在停止，请等待当前输入结束")

    def close(self):
        self.stop()
        if self.thread and self.thread.is_alive():
            self.root.after(300, self.close)
        else:
            self.root.destroy()

    def drain(self):
        try:
            while True:
                kind, value = self.bus.get_nowait()
                if kind == "log":
                    self.logs.configure(state="normal")
                    self.logs.insert("end", str(value) + "\n")
                    self.logs.see("end")
                    self.logs.configure(state="disabled")
                    self.status.set(str(value))
                elif kind == "status":
                    self.status.set(value)
                elif kind == "image":
                    self.last_frame = Image.fromarray(value[:, :, ::-1])
                    self.queue_preview()
                elif kind == "idle":
                    self.start_button.configure(state="normal")
                elif kind == "detected":
                    adb, addresses = value
                    self.vars["adb_path"].set(adb)
                    if len(addresses) == 1:
                        self.vars["address"].set(addresses[0])
                        self.status.set("已发现 MuMu：" + addresses[0])
                    elif addresses:
                        self.status.set("多个实例，请手填所需地址：" + "、".join(addresses))
                    else:
                        self.status.set("未发现运行的 MuMu 实例，请启动模拟器或手填 ADB 地址")
        except queue.Empty:
            pass
        self.root.after(100, self.drain)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true", help="只连接、截图并输出 OCR，不点击游戏")
    parser.add_argument("--run", action="store_true", help="使用 config.json 执行完整循环")
    parser.add_argument("--phase", choices=["prepare", "formal", "abandon"], help="开发联调：只执行一个阶段")
    args = parser.parse_args()
    if args.diagnose or args.run or args.phase:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
        c = Config.load()
        runner = Runner(c)
        if args.run:
            runner.run()
        elif args.phase:
            c.validate()
            runner.connect()
            print(runner.maa(args.phase))
        else:
            frame = runner.connect()
            data = runner.vision.texts(frame)
            print(json.dumps({"ocr": data, "ideal": ideal_from_text(data)}, ensure_ascii=False, indent=2))
        return
    enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
