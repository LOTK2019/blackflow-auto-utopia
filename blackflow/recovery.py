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

    targets = [r+'Recruit', r+'Floor']
    if phase == 'prepare':
        targets.insert(0, r+'Event')
        tasks[r+'Event'] = {
            'baseTask': p+'StageEncounterOcr', 'action':'DoNothing', 'preDelay':800,
            'maxTimes':3, 'exceededNext':[r+'Exhausted'],
            'next':[p+'StageEncounterJudgeOption'], 'onErrorNext':[r+'Wait']}
        # 严格选项没扫到也先回到重扫，而不是结束准备局。
        tasks[p+'ExitThenAbandon-Enter'] = {
            'algorithm':'JustReturn','action':'DoNothing','next':[r+'Wait']}
    tasks[r+'Recruit'] = {
        'baseTask':'BlackFlow@StartExplore@Roguelike@ChooseOperConfirm',
        'action':'DoNothing', 'preDelay':800, 'maxTimes':3,
        'exceededNext':[r+'Exhausted'],
        'next':['BlackFlow@StartExplore@Roguelike@ChooseOperConfirm'],
        'onErrorNext':[r+'Wait']}
    tasks[r+'Floor'] = {
        'baseTask':p+'NextLevel', 'action':'DoNothing', 'maxTimes':3,
        'exceededNext':[r+'Exhausted'], 'next':[p+'NextLevel'],
        'onErrorNext':[r+'Wait']}
    tasks[r+'Wait'] = {
        'algorithm':'JustReturn','action':'DoNothing','preDelay':1200,
        'maxTimes':6,'exceededNext':[r+'Exhausted'], 'next':[*targets,r+'Wait']}
    tasks[r+'Exhausted'] = {'algorithm':'JustReturn','action':'DoNothing','next':['Stop']}
    # 正式局 NextLevel.next 是 Stop。不能在招募动画页展开 NextLevel#next，
    # 否则尚未识别到地图就会执行无条件 Stop（长招募动画尤其容易触发）。
    tasks['BlackFlow@StartExplore@Roguelike@RecruitWithoutButton'] = {
        'algorithm':'JustReturn','action':'ClickRect','specificRect':[615,330,50,60],
        'postDelay':600,'maxTimes':20,'exceededNext':[r+'Wait'],
        'next':['BlackFlow@StartExplore@Roguelike@RecruitOther',p+'EnterAfterRecruit',
                p+'NextLevel','BlackFlow@StartExplore@Roguelike@RecruitWithoutButton']}
    # 干员插件只运行一次。确认名字暂未读到时，重读同一详情面板，
    # 不重进 ChooseOper（它会递增原生的招募顺位）。
    recruit_confirm = 'BlackFlow@StartExplore@Roguelike@ChooseOperConfirm'
    recruit_choices = [recruit_confirm,
                       'BlackFlow@StartExplore@Roguelike@ChooseOperConfirmToGiveUp',
                       r+'RecruitRead']
    patch('BlackFlow@StartExplore@Roguelike@ChooseOper', next=recruit_choices)
    tasks[r+'RecruitRead'] = {
        'algorithm':'JustReturn','action':'DoNothing','preDelay':1200,
        'maxTimes':3,'next':recruit_choices,'exceededNext':[r+'Wait']}
    # 任何恢复分支都不会直接重开一局、放弃、随机选择、重新执行完整招募插件。
    patch(p+'RecoveryFailed', next=[r+'Wait'])
    for name in (p+'StageEncounterJudgeOption', 'BlackFlow@StartExplore@Roguelike@ChooseOper'):
        patch(name, onErrorNext=[r+'Wait'])
    # 正常页之间的短暂动画、确认文字漏识别交给原有 ProcessTask 重读，再进统一恢复。
    resets = [r+'Wait*6', r+'Recruit*3', r+'RecruitRead*3', r+'Floor*3']
    if phase == 'prepare':
        resets.append(r+'Event*3')
    for name in (p+'StageEncounterReward', p+'NextLevel', p+'EnterAfterRecruit'):
        original = tasks.get(name, {}).get('reduceOtherTimes', raw.get(name, {}).get('reduceOtherTimes', []))
        patch(name, reduceOtherTimes=[*original,*resets])
    # 一张券已处理且进入招募动画/放弃确认后，下一张券有独立的重读预算。
    for name in ('BlackFlow@StartExplore@Roguelike@RecruitSkip',
                 'BlackFlow@StartExplore@Roguelike@ChooseOperConfirmToGiveUp'):
        # 这些主题变体原本由 MAA 动态生成。首次写入覆盖时必须显式继承；
        # 否则它会寻找不存在的“完整任务名.png”，破坏原来的放弃/动画分支。
        base = name.removeprefix('BlackFlow@')
        original = raw.get(base,{})
        values = {'baseTask':base,
                  'reduceOtherTimes':[*original.get('reduceOtherTimes',[]),r+'RecruitRead*3',r+'Recruit*3']}
        if 'next' in original:
            values['next'] = ['BlackFlow@'+n if n.startswith(('StartExplore@','Roguelike@')) else n for n in original['next']]
        values['template'] = 'RecruitSkip.png' if name.endswith('RecruitSkip') else 'Roguelike@StageEncounterGiveUpRecruitConfirm.png'
        patch(name, **values)
