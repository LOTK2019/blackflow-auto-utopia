"""识别恢复：重复观察有预算，不重复提交无法确认结果的游戏动作。"""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time



@dataclass(frozen=True)
class ReadPolicy:
    attempts: int = 8
    interval: float = .5
    confirmations: int = 2


class ReadExhausted(RuntimeError):
    pass


def read_with_recovery(name, observe, *, wait, policy=ReadPolicy(),
                       confirmations=None, record=lambda data: None, log=lambda text: None):
    """observe 每次取新截图，返回(value, details)，None 表示未知。

    仅连续一致的有效观察计为成功；未知、异常和冲突均清除连续计数。
    重试截图传输/解码错误，不吞配置错误、程序错误或停止信号。
    """
    from .adb import Stopped  # 原生 worker 只使用任务覆盖，不能加载 Python OpenCV DLL。
    started = time.monotonic()
    previous, count = None, 0
    for attempt in range(policy.attempts):
        if attempt:
            wait(policy.interval * min(1 + attempt // 3, 2))
        observed_at = time.monotonic()
        try:
            value, details = observe(attempt)
        except Stopped:
            raise
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            value, details = None, {"error": str(exc)}
        count = count + 1 if value is not None and value == previous else (1 if value is not None else 0)
        previous = value
        required = confirmations(value) if confirmations and value is not None else policy.confirmations
        record({"operation": name, "attempt": attempt + 1, "value": value,
                "consecutive": count, "required": required, "details": details,
                "observation_seconds":round(time.monotonic()-observed_at,3),
                "elapsed_seconds":round(time.monotonic()-started,3)})
        if value is not None and count >= required:
            return value
        log(f"{name}：重新观察 {attempt + 1}/{policy.attempts}（连续确认 {count}/{required}）")
    raise ReadExhausted(f"{name}：{policy.attempts} 次观察仍未稳定确认，保留现场")


def install_native_recovery(tasks, maa_dir, phase):
    """在同一原生任务/会话内恢复，保留烧水进度、干员顺位与难度证据。"""
    if phase not in ('prepare', 'formal'):
        return
    p, r = 'BlackFlow@Roguelike@', 'AutoUtopia@Recovery'
    # MAA 解析 overlay 时会继承已有任务字段；对需保留 next/reduce 的任务显式合并。
    raw = {}
    for path in (Path(maa_dir)/'resource/tasks').rglob('*.json'):
        raw.update(json.loads(path.read_text(encoding='utf-8')))

    def patch(name, **values):
        tasks[name] = {**tasks.get(name, {}), **values}

    # 开始探索后网络加载可能超过原生的约30秒扫描预算。只等待并识别
    # 已到达的页面，不在提交反馈期间再次点击开始或重新选择难度。
    tasks[r+'StartWait'] = {
        'algorithm':'JustReturn','action':'DoNothing','preDelay':2000,
        'maxTimes':30,'exceededNext':[r+'Exhausted'],
        'next':[p+'Squad-EnterPoint',p+'InitialDrop',p+'ChooseDifficulty',r+'StartWait']}
    for name in (p+'StartExplore',p+'StartExplore-EnterCheck'):
        patch(name,onErrorNext=[r+'StartWait'])

    # 招募完整沿用MAA原生链路；通用恢复仅重读楼层/事件，不点击未知招募页。
    targets = [r+'Floor']
    if phase == 'prepare':
        targets.insert(0, r+'Event')
        # 尽头事件退出后可能仍在加载。Stages 原生错误分支直接放弃，
        # 要先重读楼层/地图；地图明确就绪后才返回原来的调度器。
        for suffix, base in (('MapReady','Stages-MapReady'), ('MapZoomOut','Stages-ZoomOut')):
            tasks[r+suffix] = {
                'baseTask':p+base, 'action':'DoNothing', 'maxTimes':3,
                'exceededNext':[r+'Exhausted'], 'next':[p+'Stages'],
                'onErrorNext':[r+'Wait']}
            targets.append(r+suffix)
        tasks[r+'Event'] = {
            'baseTask': p+'StageEncounterOcr', 'action':'DoNothing', 'preDelay':800,
            'maxTimes':3, 'exceededNext':[r+'Exhausted'],
            'next':[p+'StageEncounterJudgeOption'], 'onErrorNext':[r+'Wait']}
        # 严格选项没扫到也先回到重扫，而不是结束准备局。
        tasks[p+'ExitThenAbandon-Enter'] = {
            'algorithm':'JustReturn','action':'DoNothing','next':[r+'Wait']}
    tasks[r+'Floor'] = {
        'baseTask':p+'NextLevel', 'action':'DoNothing', 'maxTimes':3,
        'exceededNext':[r+'Exhausted'], 'next':[p+'NextLevel'],
        'onErrorNext':[r+'Wait']}
    tasks[r+'Wait'] = {
        'algorithm':'JustReturn','action':'DoNothing','preDelay':1200,
        'maxTimes':6,'exceededNext':[r+'Exhausted'], 'next':[*targets,r+'Wait']}
    tasks[r+'Exhausted'] = {'algorithm':'JustReturn','action':'DoNothing','next':['Stop']}
    patch(p+'RecoveryFailed', next=[r+'Wait'])
    patch(p+'Stages', onErrorNext=[r+'Wait'])
    patch(p+'StageEncounterJudgeOption', onErrorNext=[r+'Wait'])
    if phase == 'prepare':
        # 恢复预算属于每次事件/楼层，不能因移除招募恢复而丢掉跨层重置。
        resets = [r+'Wait*6',r+'Floor*3',r+'Event*3',r+'MapReady*3',r+'MapZoomOut*3']
        for name in (p+'StageEncounterReward', p+'NextLevel'):
            original=tasks.get(name,{}).get('reduceOtherTimes',raw.get(name,{}).get('reduceOtherTimes',[]))
            patch(name,reduceOtherTimes=[*original,*resets])
