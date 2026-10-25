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

    recruit_skip = 'BlackFlow@StartExplore@Roguelike@RecruitSkip'
    recruit_other = 'BlackFlow@StartExplore@Roguelike@RecruitOther'
    # MAA的助战插件可能已提交确认。恢复入口也必须能接住跳过页/下一张券，
    # 不能只等待已经消失的选人详情页；这里都以实际页面识别为门控。
    targets = [r+'Recruit', recruit_skip, recruit_other, p+'EnterAfterRecruit',
               r+'RecruitAnimation', r+'Floor']
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
    tasks[r+'Recruit'] = {
        'baseTask':'BlackFlow@StartExplore@Roguelike@ChooseOperConfirm',
        'action':'DoNothing', 'preDelay':800, 'maxTimes':3,
        'exceededNext':[r+'Exhausted'],
        'next':['BlackFlow@StartExplore@Roguelike@ChooseOperConfirm'],
        'onErrorNext':[r+'Wait']}
    # 获得干员的立绘页没有确认/地图按钮。只在中央职业英文标题明确时
    # 使用原生右上角跳过位置；不重新执行会递增顺位的ChooseOper插件。
    animation = 'BlackFlow@StartExplore@Roguelike@RecruitWithoutButton'
    animation_budget = 40
    skip_rect = raw.get('StartExplore@Roguelike@RecruitWithoutButton', {}).get(
        'specificRect', [1180,15,85,60])
    tasks[r+'RecruitAnimation'] = {
        'algorithm':'OcrDetect', 'text':['SPECIALIST','VANGUARD','SUPPORTER','GUARD',
            'DEFENDER','MEDIC','CASTER','SNIPER'], 'fullMatch':True,
        'roi':[320,300,900,380], 'action':'ClickRect','specificRect':skip_rect,
        'postDelay':800, 'maxTimes':3, 'exceededNext':[r+'Exhausted'],
        'reduceOtherTimes':[animation+f'*{animation_budget}'],
        'next':[recruit_other,p+'EnterAfterRecruit',p+'NextLevel',recruit_skip,animation],
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
    tasks[animation] = {
        'algorithm':'JustReturn','action':'ClickRect','specificRect':skip_rect,
        'postDelay':600,'maxTimes':animation_budget,'exceededNext':[r+'Wait'],
        'next':[recruit_other,p+'EnterAfterRecruit',p+'NextLevel',recruit_skip,animation]}
    # 干员插件只运行一次。确认名字暂未读到时，重读同一详情面板，
    # 不重进 ChooseOper（它会递增原生的招募顺位）。
    recruit_confirm = 'BlackFlow@StartExplore@Roguelike@ChooseOperConfirm'
    recruit_choices = [recruit_confirm,
                       'BlackFlow@StartExplore@Roguelike@ChooseOperConfirmToGiveUp',
                       recruit_skip, recruit_other, p+'EnterAfterRecruit', p+'NextLevel', r+'RecruitAnimation',
                       r+'RecruitRead']
    # 恢复MAA原始的“确认或确认之后”双入口。助战插件内部已点确认，
    # 此时姓名详情已消失，必须展开确认后继（包含无按钮跳过），不能强制
    # 再等姓名OCR或职业英文。姓名门仍只控制真正的右下确认点击。
    patch('BlackFlow@StartExplore@Roguelike@ChooseOper',
          next=[recruit_confirm,recruit_confirm+'#next'])
    tasks[r+'RecruitRead'] = {
        'algorithm':'JustReturn','action':'DoNothing','preDelay':1200,
        'maxTimes':3,'next':recruit_choices,'exceededNext':[r+'Wait']}
    # 原生ChooseOperFlag只归还10次；兜底增大后也须同步，避免长动画把
    # 后两张券的预算吃掉。只在确认进入新券选人页时归还，不在每次等待时重置。
    flag = 'BlackFlow@StartExplore@Roguelike@ChooseOperFlag'
    original_flag = raw.get(flag, raw.get('Roguelike@ChooseOperFlag', {}))
    inherited_reductions = original_flag.get('reduceOtherTimes',
        raw.get('Roguelike@ChooseOperFlag', {}).get('reduceOtherTimes', []))
    patch(flag, reduceOtherTimes=[*inherited_reductions, animation+f'*{animation_budget}',
                                 r+'RecruitAnimation*3',r+'RecruitRead*3',r+'Recruit*3'])
    # 任何恢复分支都不会直接重开一局、放弃、随机选择、重新执行完整招募插件。
    patch(p+'RecoveryFailed', next=[r+'Wait'])
    patch(p+'Stages', onErrorNext=[r+'Wait'])
    for name in (p+'StageEncounterJudgeOption', 'BlackFlow@StartExplore@Roguelike@ChooseOper'):
        patch(name, onErrorNext=[r+'Wait'])
    # 正常页之间的短暂动画、确认文字漏识别交给原有 ProcessTask 重读，再进统一恢复。
    resets = [r+'Wait*6', r+'Recruit*3', r+'RecruitRead*3', r+'RecruitAnimation*3', r+'Floor*3']
    if phase == 'prepare':
        resets.extend([r+'Event*3',r+'MapReady*3',r+'MapZoomOut*3'])
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
                  'reduceOtherTimes':[*original.get('reduceOtherTimes',[]),r+'RecruitRead*3',r+'Recruit*3',
                                      r+'RecruitAnimation*3',animation+f'*{animation_budget}']}
        if 'next' in original:
            values['next'] = ['BlackFlow@'+n if n.startswith(('StartExplore@','Roguelike@')) else n for n in original['next']]
        values['template'] = 'RecruitSkip.png' if name.endswith('RecruitSkip') else 'Roguelike@StageEncounterGiveUpRecruitConfirm.png'
        patch(name, **values)
