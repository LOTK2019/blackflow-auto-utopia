from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import itertools
import cv2
import numpy as np
from .adb import ADB, Stopped, save_image, load_image
from .config import ROOT, RESOURCE_ROOT, APP_ROOT
from .errors import describe_error, error_event
from .progress import WorkerProgress
from .recovery import ReadPolicy, ReadExhausted, read_with_recovery
from .nodes import effective_nodes, reconcile_node_maps
from .animals import animals_satisfy, harvest_animals_from_ocr, known_harvest_items
from .discovery import discover
from .vision import Vision, ideal_from_text, header_ideal, IDEAL_ROI


class Runner:
    def __init__(self, config, log=print, preview=lambda image: None):
        self.config, self.log, self.preview = config, log, preview
        self.stop = threading.Event()
        self.proc = None
        self.adb = ADB(config.adb_path, config.address, self.stop)
        self.vision = Vision(config.maa_dir)
        self.session = ROOT / "artifacts" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.session.mkdir(parents=True, exist_ok=True)
        self.phase = "idle"
        self.cycle = 0
        self.last_frame = None
        self.last_frame_at = None
        self._reported_exception = None
        self._error_report = None

    def set_phase(self, phase):
        self.phase = phase
        (self.session / "state.json").write_text(json.dumps({"phase": phase, "cycle": self.cycle,
            "updated_at": datetime.now().isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(phase)

    def stop_now(self):
        self.stop.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("stop\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass

    @staticmethod
    def terminate_worker(proc):
        if proc.poll() is not None:
            return
        if os.name == "nt":
            # Windows venv 启动器可能还有 Python 子进程，必须一起停止。
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.terminate()

    def capture(self, label):
        frame = self.adb.screenshot()
        save_image(self.session / f"{self.cycle:03d}-{label}.png", frame)
        self.last_frame, self.last_frame_at = frame.copy(), datetime.now().isoformat()
        self.preview(frame)
        return frame

    def save_error_report(self, exc):
        """尽力保存新鲜错误截图；取图失败不能掩盖原异常，缓存图明确标为旧图。"""
        if isinstance(exc,Stopped):
            return None
        if self._reported_exception is exc:
            return self._error_report
        folder = self.session / 'errors'
        folder.mkdir(parents=True, exist_ok=True)
        stem = f'{self.cycle:03d}-'+datetime.now().strftime('%H%M%S-%f')
        report = {**error_event(exc), 'phase':self.phase, 'cycle':self.cycle,
                  'occurred_at':datetime.now().isoformat(), 'screenshot':None}
        try:
            if self.stop.is_set():
                raise RuntimeError('已请求停止，未继续向设备请求截图')
            frame = self.adb.screenshot()
            path = folder / (stem+'-error.png')
            save_image(path,frame)
            report.update(screenshot=path.name,screenshot_source='fresh',
                          captured_at=datetime.now().isoformat())
        except Exception as shot_error:
            report['screenshot_error'] = describe_error(shot_error)
            if self.last_frame is not None:
                try:
                    path = folder / (stem+'-last-known.png')
                    save_image(path,self.last_frame)
                    report.update(screenshot=path.name,screenshot_source='last_known',
                                  captured_at=self.last_frame_at)
                except Exception as fallback_error:
                    report['fallback_error'] = describe_error(fallback_error)
        path = folder / (stem+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        self._reported_exception, self._error_report = exc,path
        self.log('错误现场记录：'+str(path))
        if report['screenshot']:
            self.log(('报错界面截图：' if report['screenshot_source']=='fresh' else '最后一次成功截图（非报错时实时画面）：')+str(folder/report['screenshot']))
        if report.get('screenshot_error'):
            self.log('错误现场截图失败：'+report['screenshot_error'])
        return path

    @staticmethod
    def acquire_lock():
        import msvcrt
        folder = ROOT / "runtime"
        folder.mkdir(exist_ok=True)
        handle = (folder / "automation.lock").open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            handle.close()
            raise RuntimeError("已有自动化循环在运行，请先停止它") from exc
        return handle

    def connect(self):
        self.config.adb_path = os.path.expandvars(self.config.adb_path.strip().strip('"'))
        self.adb.executable = self.config.adb_path
        if not self.config.address.strip() or self.config.address.strip().lower() == "auto":
            path, addresses = discover(self.config.adb_path, log=self.log, report_path=ROOT/'runtime/discovery.json')
            if len(addresses) != 1:
                raise RuntimeError(f"检测到 {len(addresses)} 个设备，请在界面手动选定 ADB 地址：{addresses}")
            self.config.adb_path, self.config.address = path, addresses[0]
            self.adb = ADB(path, addresses[0], self.stop)
        self.log(self.adb.connect().strip())
        return self.capture("connected")

    def require_theme(self, frame):
        def observe(attempt):
            current = frame if attempt == 0 else self.capture(f"theme-retry-{attempt}")
            if any(self.vision.match(current, "BlackFlow@Roguelike@" + n) for n in ("StartExplore", "Continue", "StartExploreCD")):
                return True, {"method":"template"}
            texts = self.vision.texts(current)
            found = self.vision.find(texts, "源流堆栈") and any(self.vision.find(texts, t) for t in ("探索", "保密等级"))
            return True if found else None, {"ocr":texts}
        try:
            self.recover_read("主题主界面", observe, policy=ReadPolicy(confirmations=1))
        except ReadExhausted as exc:
            raise RuntimeError("多次重读仍未确认主题主界面，请先进入黑流树海主题主界面；现场已保留") from exc

    def recover_read(self, name, observe, **kwargs):
        def record(data):
            with (self.session / f"{self.cycle:03d}-recovery.jsonl").open("a", encoding="utf-8") as trace:
                trace.write(json.dumps({"time":datetime.now().isoformat(), **data}, ensure_ascii=False) + "\n")
        return read_with_recovery(name, observe, wait=self.adb.wait, record=record, log=self.log, **kwargs)

    def maa(self, phase):
        if self.stop.is_set():
            raise Stopped()
        cfg_path = self.session / "run-config.json"
        cfg_path.write_text(json.dumps(asdict(self.config), ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "BLACKFLOW_MANAGED": "1"}
        # 独立解释器不能继承 Conda 的 DLL 搜索路径。
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if "miniconda" not in p.lower())
        python = ROOT / ".venv/Scripts/python.exe"
        command = ([str(APP_ROOT / "blackflow-worker.exe"), phase, str(cfg_path)] if getattr(sys, "frozen", False) else
                   [str(python if python.exists() else sys.executable), "-m", "blackflow.maa_worker", phase, str(cfg_path)])
        self.proc = subprocess.Popen(command,
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        messages = queue.Queue()
        proc = self.proc

        def reader():
            for line in proc.stdout:
                messages.put(line)
            messages.put(None)

        threading.Thread(target=reader, daemon=True).start()
        done = False
        progress = WorkerProgress()
        evidence = {"prepared": False, "prepare_rejected":False, "node_maps":[], "floor_one": False, "investment": False, "reward_rejected": False,
                    "difficulty_confirmed": False}
        deadline = time.monotonic() + self.config.phase_timeout + 60
        try:
            with (self.session / f"{self.cycle:03d}-{phase}.jsonl").open("w", encoding="utf-8") as trace:
                while True:
                    if self.stop.is_set():
                        self.stop_now()
                        try:
                            proc.wait(timeout=6)
                        except subprocess.TimeoutExpired:
                            self.terminate_worker(proc)
                        raise Stopped()
                    if time.monotonic() > deadline:
                        self.terminate_worker(proc)
                        raise RuntimeError("MAA 子进程超时；" + progress.summary())
                    try:
                        line = messages.get(timeout=.2)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    trace.write(line)
                    trace.flush()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    kind = event.get("kind")
                    if kind == "error":
                        if self.stop.is_set():
                            raise Stopped()
                        raise RuntimeError(event.get("message") or (event.get("error_type", "未知异常") + "：后台未提供说明，请查看阶段日志"))
                    if kind == "done":
                        done = True
                    if kind == "reward_rejected":
                        evidence["reward_rejected"] = True
                    if kind == 'node_maps':
                        evidence['node_maps'] = event.get('snapshots',[])
                    if kind == 'recruitment_audit':
                        evidence['recruited'] = event.get('selected',[])
                        evidence['recruitment_completed_slots'] = event.get('completed_slots',0)
                    if kind == "version":
                        self.log("MAA " + event["version"])
                    if kind == "phase_stats":
                        (self.session / f"{self.cycle:03d}-{phase}-stats.json").write_text(
                            json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
                        self.log(f"{phase}: 用时 {event['elapsed_seconds']:.1f} 秒，识别恢复 {event['recovery_attempts']} 次")
                    if kind != "callback":
                        continue
                    data, msg = event.get("data", {}), event.get("msg")
                    progress.observe(msg, data)
                    detail = data.get("details", {})
                    task, what = detail.get("task", ""), data.get("what", "")
                    if phase == 'prepare' and msg == 20001 and task.split('@')[-1] == 'CultivateEnter':
                        evidence['yellow_shop_visited']=True
                        self.log('已进入黄商店，开始原生出售、买种与培育流程')
                    if phase == 'prepare' and msg == 20001 and task.split('@')[-1] == 'HarvestRead':
                        market=json.loads((Path(self.config.maa_dir)/'resource/roguelike/BlackFlow/scrap_market.json').read_text(encoding='utf-8'))
                        known_items=known_harvest_items(market)
                        observations=[]
                        for sample in range(2):
                            frame=self.capture(f'harvest-{sample}')
                            texts=self.vision.texts(frame,(1,292,1277,99))
                            observations.append(harvest_animals_from_ocr(texts,known_items))
                            (self.session/f'{self.cycle:03d}-harvest-{sample}.json').write_text(
                                json.dumps({'ocr':texts,'animals':observations[-1]},ensure_ascii=False,indent=2),encoding='utf-8')
                            if sample==0:self.adb.wait(.2)
                        if observations[0] is not None and observations[0] == observations[1]:
                            evidence['harvest_animals']=list(observations[0])
                            self.log('独立确认收获动物：'+str(evidence['harvest_animals']))
                        elif self.config.require_animals:
                            raise RuntimeError('收获页动物数量未稳定确认，保留现场，未当作数量不够重烧')
                    if msg == 20001 and task:
                        if task.split('@')[-1].startswith('Recovery'):
                            self.log(f"{phase}: 页面识别恢复 · {task.rsplit('@',1)[-1]}（第{detail.get('exec_times',1)}次）")
                        if any(s in task for s in ("Recruit", "NextLevel", "LastReward", "Invest", "Abandon", "StartExploreCD", "StartExplore", "MovePreview", "SquadConfirm", "RolesConfirm")):
                            self.log(f"{phase}: {task}")
                    if msg == 20002 and task.endswith("NextLevel") and detail.get("result", {}).get("text") == "玻利瓦尔肤层":
                        evidence["floor_one"] = True
                    if msg == 20002 and task.endswith("DifficultyValueConfirm"):
                        actual = detail.get("result", {}).get("text", "")
                        if phase == "prepare" and actual == "保密等级":
                            actual = "0"  # 游戏 N0 使用文字标题，不绘制数字0。
                        expected = str(0 if phase == "prepare" else self.config.difficulty)
                        if actual != expected:
                            raise RuntimeError(f"难度确认不符：目标 N{expected}，实际识别 {actual}")
                        evidence["difficulty_confirmed"] = True
                        self.log(f"{phase}: MAA 已核对并选择 N{expected}")
                    if what == "BlackFlowStrategyResult":
                        evidence["prepared"] = detail.get("succeeded") is True and detail.get("outcome") == "burn_completed"
                        if phase == 'prepare' and evidence['prepared']:
                            evidence['animals'] = evidence.get('harvest_animals',detail.get('cultivated_animal_types',[]))
                            self.log('准备局种植结果：'+str(evidence['animals'])+'；' + ('按指定动物筛选' if self.config.require_animals else '未要求动物，不影响准备局合格'))
                            if self.config.require_animals and not animals_satisfy(evidence['animals'],self.config.desired_animals):
                                evidence['prepare_rejected']=True
                        if phase == 'prepare' and detail.get('optional_route_exhausted'):
                            evidence['prepare_rejected']=True
                            evidence['reject_reason']='本轮未能安全通过前两层，退出后重新准备'
                        elif phase == 'prepare' and detail.get('outcome') == 'utopia_seed_missed':
                            evidence['prepare_rejected'] = True
                        elif phase == 'map' and detail.get('profile') == 'utopia_inspect_map' and detail.get('outcome') == 'planning_failed':
                            pass  # 只读策略禁止全部移动后，规划失败是预期退出；仍须核对节点证据。
                        elif detail.get("succeeded") is False:
                            raise RuntimeError("准备局未完成：" + str(detail.get("termination_reason", detail)))
                    if phase == 'prepare' and what == 'BlackFlowRoutingDecision':
                        self.log(f"准备局第{detail.get('floor')}层：前往{detail.get('node_name') or detail.get('node_type')}，"
                                 f"移动方式 {detail.get('movement')}，预计剩余行动力 {detail.get('action_points_after')}")
                        if detail.get('node_type') == 'scrap_shop':
                            evidence['yellow_shop_planned']=True
                    if what == "RoguelikeEventSelected":
                        self.log(f"{phase}: {detail.get('name', '')} → {detail.get('option_text', '')}（兜底={detail.get('used_fallback', False)}）")
                    if "Investment" in what or "投资" in what:
                        evidence["investment"] = True
            code = proc.wait(timeout=10)
            if code or not done:
                raise RuntimeError(f"MAA 阶段未正常结束（退出码 {code}）")
            if phase in ("prepare", "formal") and not evidence["difficulty_confirmed"]:
                raise RuntimeError("缺少 MAA 难度确认记录，保留现场，不能视为有效局")
            if phase == "prepare" and not evidence["prepared"] and not evidence['prepare_rejected']:
                raise RuntimeError("没有收到三层烧水成功证据，不能开启正式局")
            if phase == "formal" and not evidence["floor_one"] and not evidence["reward_rejected"]:
                # 原生回调漏掉也不能直接当成没进地图，停下 worker 后独立重读。
                def observe_floor(attempt):
                    frame = self.capture(f"floor-retry-{attempt}")
                    texts = self.vision.texts(frame, IDEAL_ROI)
                    title = self.vision.find(texts, "玻利瓦尔肤层", exact=True)
                    # 同时确认底部地图 UI，避免把过场标题当成可操作地图。
                    ui = self.vision.texts(frame, (100,640,1180,80))
                    map_ready = any(self.vision.find(ui, word) for word in ("收藏品", "干员", "编队"))
                    return True if title and map_ready else None, {"ocr":texts,"map_ui":ui}
                self.recover_read("第一层地图", observe_floor)
                evidence["floor_one"] = True
            return evidence
        finally:
            if proc.poll() is None:
                try:
                    proc.stdin.write("stop\n")
                    proc.stdin.flush()
                    proc.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.terminate_worker(proc)
                    proc.wait(timeout=5)
            self.proc = None
            (self.session / f"{self.cycle:03d}-{phase}-progress.json").write_text(
                json.dumps(progress.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")

    def inspect_ideal(self):
        """由实测地图状态栏读取；unknown 永远不会触发放弃。"""
        baseline_path = RESOURCE_ROOT / "assets/no-ideal-icon-slot.png"
        baseline = load_image(baseline_path) if baseline_path.exists() else None
        def observe(attempt):
            frame = self.capture(f"ideal-{attempt}")
            texts = self.vision.texts(frame, IDEAL_ROI)
            result, details = header_ideal(frame, texts, baseline)
            (self.session / f"{self.cycle:03d}-ocr-{attempt}.json").write_text(json.dumps({"ocr": texts, "decision": result, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
            return result if result in ("present","absent") else None, {"ocr":texts, **details}
        try:
            result = self.recover_read("实托邦标识", observe, policy=ReadPolicy(attempts=12),
                                       confirmations=lambda value: 2 if value == "present" else 4)
        except ReadExhausted:
            return "unknown", "多次恢复后仍未确认实托邦状态，保留当前局"
        return result, "楼层名左侧的实托邦标识" if result == "present" else "一层标题已确认，图标槽连续四帧为空"

    def confirm_map_difficulty(self):
        seen = []
        def observe(attempt):
            frame = self.capture(f"difficulty-{attempt}")
            value, texts = self.vision.map_difficulty(frame)
            seen.append(value)
            (self.session / f"{self.cycle:03d}-difficulty-{attempt}.json").write_text(
                json.dumps({"expected": self.config.difficulty, "actual": value, "ocr": texts},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            return value, {"expected":self.config.difficulty,"ocr":texts}
        try:
            actual = self.recover_read("正式局地图难度", observe)
        except ReadExhausted as exc:
            raise RuntimeError(f"正式局实际难度核验失败：目标 N{self.config.difficulty}，读到 {seen}；恢复后仍不稳定，保留现场") from exc
        if actual != self.config.difficulty:
            raise RuntimeError(f"正式局实际难度核验失败：目标 N{self.config.difficulty}，读到 {seen}；保留现场，未作为有效局")
        self.log(f"正式局地图已连续两帧确认 N{self.config.difficulty}")

    def count_effective_nodes(self):
        previous = None
        observations = []
        template_file = Path(self.config.maa_dir) / 'resource/roguelike/BlackFlow/map_templates.json'
        templates = json.loads(template_file.read_text(encoding='utf-8')).get('templates', []) if template_file.is_file() else []
        # 分别重建地图；不同 worker 的新截图/快照确认一致才接受，不复用过期诊断文件。
        for attempt in range(4):
            if attempt:
                self.adb.wait(.5)
            self.capture(f'nodes-{attempt}')
            evidence = self.maa('map')
            observations.append(evidence['node_maps'])
            valid = []
            for snapshot in evidence['node_maps']:
                try:
                    valid.append(effective_nodes(snapshot))
                except ValueError as exc:
                    self.log('节点统计需重扫：'+str(exc))
            current = valid[-1] if valid else None
            consensus = reconcile_node_maps(observations, templates, minimum=self.config.min_effective_nodes)
            (self.session/f'{self.cycle:03d}-nodes-{attempt}.json').write_text(
                json.dumps({'maps':evidence['node_maps'],'accepted':current,'consensus':consensus},ensure_ascii=False,indent=2),encoding='utf-8')
            if consensus:
                if consensus.get('effective_is_upper_bound'):
                    self.log(f"第一层有效节点至多 {consensus['effective']}（已复核空地 {consensus['empty']}；未知节点全部按有效计算仍不达标）")
                    return consensus['effective']
                self.log(f"第一层有效节点 {consensus['effective']}（空地 {consensus['empty']}，总节点 {consensus['total']}；逐位置跨轮复核）")
                return consensus['effective']
            if current and previous and (current['effective'],current['empty'],current['types']) == (previous['effective'],previous['empty'],previous['types']):
                self.log(f"第一层有效节点 {current['effective']}（空地 {current['empty']}，总节点 {current['total']}）")
                return current['effective']
            previous = current
        raise RuntimeError('节点数量多次重扫仍未确认，保留正式局，未按数量不足丢弃')

    def run(self):
        lock = None
        try:
            lock = self.acquire_lock()
            self.config.validate()
            self.set_phase("连接模拟器 ADB")
            self.require_theme(self.connect())
            # 只在用户主动点击开始时处理主题页上的现有探索；不自动恢复中断任务。
            frame = self.adb.screenshot()
            if self.vision.match(frame, "BlackFlow@Roguelike@Continue"):
                self.set_phase("退出主题页上的现有探索")
                self.maa("abandon")
            for self.cycle in itertools.count(1):
                self.set_phase(f"第 {self.cycle} 轮：准备局，{self.config.prepare_method}后抵达第三层")
                prepared = self.maa("prepare")
                self.capture("prepare-complete")
                self.maa("abandon")  # 完成准备局结算，回到主题页。
                if prepared.get('prepare_rejected'):
                    self.log(prepared.get('reject_reason','本轮种植结果未满足已启用的动物数量要求，重新进行准备局'))
                    continue
                self.set_phase(f"第 {self.cycle} 轮：文明开化分队正式局")
                formal = self.maa("formal")
                if formal.get("reward_rejected"):
                    self.log("没有出现指定的开局奖励，退出正式局，重新进行准备局")
                    self.maa("abandon")
                    continue
                self.confirm_map_difficulty()
                if self.config.node_filter_enabled:
                    count = self.count_effective_nodes()
                    if count < self.config.min_effective_nodes:
                        self.log(f'有效节点 {count}，低于要求 {self.config.min_effective_nodes}，退出正式局并重新烧水')
                        self.maa('abandon')
                        continue
                self.set_phase(f"第 {self.cycle} 轮：检查第一层实托邦")
                status, name = self.inspect_ideal()
                if status == "present":
                    self.set_phase(f"找到实托邦：{name}。已停止，保留正式局")
                    return "found"
                if status == "unknown":
                    raise RuntimeError(name)
                self.log("确认无实托邦，退出正式局，下一轮重新烧水")
                self.maa("abandon")
        except Stopped:
            self.set_phase("已停止，保留现场；重新开始前请回到主题主界面")
            return "stopped"
        except Exception as exc:
            try:
                self.save_error_report(exc)
            except Exception as report_error:
                self.log('保存错误现场失败：'+describe_error(report_error))
            try:
                self.set_phase("错误停止：" + describe_error(exc))
            except Exception as state_error:
                self.log('写入错误状态失败：'+describe_error(state_error))
            raise
        finally:
            if lock is not None:
                lock.close()
