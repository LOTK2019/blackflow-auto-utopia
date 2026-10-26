"""独立进程加载 MaaCore，避免 OCR / Conda DLL 与 MAA 的 DLL 相互影响。

标准输出仅为 JSON Lines。源实现参考 MAA (AGPL-3.0)，不修改用户的 MAA 安装。
"""
import ctypes as C
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
from .config import Config, ROOT, REWARD_TARGETS, read_blackflow_strategy
from .errors import error_event
from .progress import WorkerProgress
from .recovery import install_native_recovery
from .strategy import seed_burn_strategy, map_inspection_strategy, optional_seed_completion, SEED_PROFILE, COUNT_PROFILE
from .rewards import install_reward_tasks, reward_plan, required_rewards
from .recruitment import NativeRecruitAudit


def emit(kind, **data):
    print(json.dumps({"kind": kind, **data}, ensure_ascii=False), flush=True)


def make_overlay(config, phase, folder):
    resource = folder / "resource"
    (resource / "tasks").mkdir(parents=True, exist_ok=True)
    if phase in ('prepare','formal'):
        engine_config=json.loads((Path(config.maa_dir)/'resource/config.json').read_text(encoding='utf-8'))
        # 保留每个动作的动画等待与确认，只缩短相邻任务间的通用空闲。
        engine_config['options']['taskDelay']=250
        (resource/'config.json').write_text(json.dumps(engine_config,ensure_ascii=False),encoding='utf-8')
    prefix = "BlackFlow@Roguelike@"
    tasks = {
        prefix + "LastReward-Strategy": {"next": [prefix + "LastReward" + s for s in ("6", "2", "5", "4", "", "3")]},
        prefix + "Begin": {"next": [prefix + n for n in ("MissionFailedFlag2", "ChooseDifficulty", "StartExplore", "Continue", "StartExploreCD", "Abandon", "ExitThenAbandon", "MapPrepare-FloorEnterZoom", "NextLevel")]},
    }
    if phase in ("prepare", "formal"):
        # 原生指定招募和候选遍历都直接读取这个全局键（不是主题前缀键）。
        # 默认5轮不足以覆盖大账号的职业列表；仍由原生重复名单/位置判断提前结束。
        tasks['RoguelikeRecruitSwipeMaxTime'] = {'maxTimes': 20}
        # 小标题旧 ROI 仅裁到“分队”的局部，部分帧 OCR 返回空串。
        # 使用完整标题区域触发原生分队插件，不改变分队选择逻辑。
        tasks[prefix+'Squad-EnterPoint'] = {
            'algorithm':'OcrDetect','text':['选择分队'],'roi':[400,0,480,120],
            'action':'DoNothing','next':[prefix+'SquadConfirm']}
        # 猫狗收益弹窗关闭后有退场动画；确认按钮位置与招募组合卡片重叠。
        # 局部等待必须保留，否则快速循环会把下一页中间卡片误点选中。
        tasks[prefix+'SquadConfirmRewardPopup'] = {'postDelay':1000,
            'next':[prefix+'LastReward-EnterPoint',prefix+'RolesDefault',prefix+'RecruitMain',
                    '#self',prefix+'SquadConfirm@('+prefix+'CloseCollection)',prefix+'Stages#next']}
        target = 0 if phase == "prepare" else config.difficulty
        maa_options = json.loads((Path(config.maa_dir) / "resource/config.json").read_text(encoding="utf-8")).get("options", {})
        duration_multiplier = float(maa_options.get("adbSwipeDurationMultiplier", 10.0))
        if duration_multiplier <= 0:
            raise ValueError("MAA 的 adbSwipeDurationMultiplier 必须大于0")
        swipe_duration = max(1, round(450 / duration_multiplier))
        # 复用 MAA 难度选择插件；旧通用滑动中心 x=650 落在数字列表外。
        # 覆盖只作用于本脚本启动的 BlackFlow 子进程。
        for direction, start_y, end_y in (("Up", 600, 150), ("Down", 150, 600)):
            swipe = {
                "algorithm": "JustReturn", "action": "Swipe", "specificRect": [480, start_y, 80, 40],
                # 抵消用户 MAA 的 ADB 时长倍数，使实际滑动约450ms。
                "rectMove": [480, end_y, 80, 40], "specialParams": [swipe_duration],
                "postDelay": 1200, "next": ["#next"], "maxTimes": 20}
            extra = f"AutoUtopia@DifficultySwipe{direction}Extra"
            tasks[extra] = {**swipe, "next": []}
            tasks[f"SwipeToThe{direction}"] = {**swipe, "sub": [extra]}
        tasks["Roguelike@ChooseDifficulty_AnalyzeCurrentDifficulty"] = {
            "baseTask": "NumberOcrReplace", "roi": [430, 315, 200, 125],
            "text": [str(i) for i in range(17)], "fullMatch": True}
        tasks[prefix + "ChooseDifficulty_Specified"] = {
            "baseTask": "Roguelike@ChooseDifficulty_Specified", "roi": [430, 465, 200, 250]}
        tasks[prefix + "ChooseDifficultyConfirm"] = {
            "algorithm": "OcrDetect", "text": ["选择"], "roi": [1064, 294, 216, 170],
            "action": "DoNothing", "sub": ["AutoUtopia@DifficultyValueConfirm"]}
        tasks[prefix + "ChooseDifficulty"] = {
            "algorithm": "OcrDetect", "text": ["选择"], "roi": [1064, 294, 216, 170],
            "action": "DoNothing", "sub": ["AutoUtopia@DifficultyValueConfirm"],
            "next": [prefix + "StartExplore"]}
        tasks["AutoUtopia@DifficultyValueConfirm"] = {
            "algorithm": "OcrDetect", "text": ["保密等级" if target == 0 else str(target)], "fullMatch": True,
            "isAscii": target != 0,
            "roi": [430, 315, 200, 125], "action": "ClickRect", "specificRect": [1190, 365, 50, 30],
            "postDelay": 800}
    if phase == "prepare":
        tasks[prefix+'MovePreviewWait'] = {'postDelay':1200}
        # 自定义 burn 策略的原生结果不携带动物明细。收获页留出短窗口，
        # 由父进程使用新截图独立读取每张动物卡，支持重复品种数量。
        tasks[prefix+'CultivateHarvestReady'] = {'next':['AutoUtopia@HarvestRead']}
        tasks['AutoUtopia@HarvestRead'] = {
            'algorithm':'JustReturn','action':'DoNothing','postDelay':3500,
            'next':[prefix+'CultivationResult']}
        strategy, profile, flight = read_blackflow_strategy(config.maa_dir)
        for rule in profile["terminal_rules"]:
            rule["next_action"] = "stop_run"
        profile["failure_action"] = "stop_run"
        # 实际上报：第二层漏扫“说服同伴”，编号1落到禁用的“召集同伴”，
        # 原生通用兜底随后选了最后一项支线。烧水只允许明确的跨层选项。
        flight.setdefault("encounter_rules", []).append({
            "id": "utopia_burn_exit_by_text", "event_name": "险路尽头", "rank": -100,
            "option_text": ["说服同伴"], "allow_fallback": False,
        })
        # 三重身的捷径会跨层，但原生节点完成逻辑仍把它当普通事件，
        # 随后以旧楼层重建新地图。准备局选择安全离开，不猜测跨层地图。
        flight['encounter_rules'].append({
            'id':'utopia_avoid_untracked_floor_shortcut','event_name':'三重身','rank':-100,
            'option_text':['自己找路'],'allow_fallback':False,
        })
        # 原生插件在严格选择失败时会转入放弃入口；准备阶段保留现场，
        # 由父进程核验烧水证据后报错，不能误入正式局或清掉诊断现场。
        tasks[prefix + "ExitThenAbandon-Enter"] = {
            "algorithm": "JustReturn", "action": "DoNothing", "next": ["Stop"]}
        # 正常扫描保留 MAA 原本时序，较长等待只在恢复分支使用。
        direct_movement = {"any": [{"fact": "candidate.movement", "op": "eq", "value": "rogue_6_scrap_M_11"},
                                   {"fact": "candidate.movement", "op": "eq", "value": "walk"}]}
        # 相邻节点可能只生成徒步候选。允许直接进入目标节点，仍禁止先绕去其他事件。
        for rule in flight["rules"]:
            if rule["id"] == "burn_require_flight_on_floor2":
                rule["candidate_if"]["all"][0] = direct_movement
        if config.prepare_method == '绿商店投资':
            flight["rules"].extend([
            {"id": "utopia_fly_to_green_shop", "kind": "require", "tier": "strategy_constraint", "rank": 0,
             "when": {"all": [{"fact": "current_floor", "op": "eq", "value": 1},
                                {"fact": "burn_shop_done", "op": "eq", "value": False}]},
             "candidate_if": {"all": [direct_movement,
                                       {"fact": "candidate.node_type", "op": "eq", "value": "shop"}]}},
            {"id": "utopia_fly_to_first_exit", "kind": "require", "tier": "strategy_constraint", "rank": 0,
             "when": {"all": [{"fact": "current_floor", "op": "eq", "value": 1},
                                {"fact": "burn_shop_done", "op": "eq", "value": True}]},
             "candidate_if": {"all": [direct_movement,
                                       {"fact": "candidate.exit", "op": "eq", "value": True}]}}
            ])
        else:
            seed_burn_strategy(strategy, config.require_animals)
        (resource / "roguelike/BlackFlow").mkdir(parents=True, exist_ok=True)
        (resource / "roguelike/BlackFlow/strategy.json").write_text(json.dumps(strategy, ensure_ascii=False), encoding="utf-8")
    elif phase == "formal":
        # 在一层标题被识别后结束任务；不让 MAA 进入选路或放弃流程。
        # 原生动画会展开NextLevel#next，因此停止入口本身也须识别地图。
        # Stop不能放sub（仅结束嵌套任务），也不能直接展开为无条件Stop。
        tasks[prefix + "NextLevel"] = {"next": ["AutoUtopia@VerifiedMapStop"]}
        tasks['AutoUtopia@VerifiedMapStop'] = {
            'baseTask':prefix+'NextLevel','action':'DoNothing',
            'sub':[], 'next':['Stop']}
        install_reward_tasks(tasks, config)
        # 选人、确认、动画均由原生MAA完成，不对详情姓名重复OCR。
        from .config import PROFESSION_NAMES
        roles = [config.operators()[n]['profession'] for n in [config.six_star, *config.four_stars]]
        checks=[]
        for i, role in enumerate(roles):
            check=f'AutoUtopia@StartVoucherCheck{i}'
            checks.append(check)
            tasks[check]={'algorithm':'OcrDetect','text':[PROFESSION_NAMES[role]+'招募券'],
                          'fullMatch':False,'roi':[186,298,913,200],'action':'DoNothing'}
        # 原生组合确认完成、三张券展示后只读核对；失败由原生sub失败停止，不进入错误职业列表。
        tasks[prefix+'RolesConfirm']={'sub':checks}
        # 排名仅影响首选找不到时的 MAA 回退，四星不接受任意替代。
        recruitment = json.loads((Path(config.maa_dir) / "resource/roguelike/BlackFlow/recruitment.json").read_text(encoding="utf-8"))
        preferred = config.allowed_six()
        for group in recruitment.get("priority", []):
            for oper in group.get("opers", []):
                if oper.get("name") in preferred:
                    oper["recruit_priority"] = 10000 - preferred.index(oper["name"]) * 10
                    oper["recruit_priority_when_team_full"] = oper["recruit_priority"]
        (resource / "roguelike/BlackFlow").mkdir(parents=True, exist_ok=True)
        (resource / "roguelike/BlackFlow/recruitment.json").write_text(json.dumps(recruitment, ensure_ascii=False), encoding="utf-8")
    elif phase == 'map':
        strategy, _, _ = read_blackflow_strategy(config.maa_dir)
        map_inspection_strategy(strategy)
        (resource / 'roguelike/BlackFlow').mkdir(parents=True,exist_ok=True)
        (resource / 'roguelike/BlackFlow/strategy.json').write_text(json.dumps(strategy,ensure_ascii=False),encoding='utf-8')
        # 地图读取专用入口：不含开始探索、招募、放弃，策略禁止所有移动。
        tasks[prefix+'Begin'] = {'next':[prefix+'NextLevel']}
    elif phase == "abandon":
        tasks['AutoUtopia@AbandonRecruitAnimation'] = {
            'algorithm':'OcrDetect','text':[*config.allowed_six(),*config.four_stars,'机械师',
                'SPECIAL','GUARD','DEFENDER','MEDIC','CASTER','SUPPORTER','VANGUARD','SNIPER'],
            'roi':[300,280,950,350],'fullMatch':False,
            'action':'ClickRect','specificRect':[615,330,50,60],'postDelay':800,
            'next':[prefix+'ExitThenAbandon-Enter']}
        tasks['AutoUtopia@AbandonBattle'] = {
            'baseTask':'BattleOfficiallyBegin','template':'BattleOfficiallyBegin.png',
            'action':'ClickRect','specificRect':[1170,20,60,60],'postDelay':500,
            'next':['RoguelikeBattleAbandon']}
        tasks['RoguelikeBattleAbandon'] = {'next':['AutoUtopia@AbandonBattleConfirm']}
        tasks['AutoUtopia@AbandonBattleConfirm'] = {
            'baseTask':'RoguelikeBattleAbandonConfirm','template':'RoguelikeBattleAbandonConfirm.png',
            'postDelay':1500,'next':[prefix+'MissionFailedFlag2',prefix+'ExitThenAbandon-Enter']}
        tasks['AutoUtopia@AbandonRecruitDialog'] = {
            'algorithm':'MatchTemplate','template':'Roguelike@StageEncounterGiveUpRecruitConfirm.png',
            'roi':[613,410,424,171],'action':'ClickSelf','postDelay':600,
            'next':[prefix+'ExitThenAbandon-Enter']}
        tasks[prefix + "StartExplore"] = {"action": "DoNothing", "next": ["Stop"]}
        tasks[prefix + "StartExploreCD"] = {"action": "DoNothing", "next": ["Stop"]}
    install_native_recovery(tasks, config.maa_dir, phase)
    (resource / "tasks/tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def run(config, phase):
    phase_started = time.monotonic()
    wall_started = time.time_ns()
    folder = ROOT / "runtime" / f"maa-{phase}"
    folder.mkdir(parents=True, exist_ok=True)
    make_overlay(config, phase, folder)
    dll_dir = os.add_dll_directory(str(Path(config.maa_dir).resolve()))
    lib = C.WinDLL(str(Path(config.maa_dir) / "MaaCore.dll"))
    callback_type = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_void_p)
    for name, restype, args in [
        ("AsstSetUserDir", C.c_bool, [C.c_char_p]),
        ("AsstLoadResource", C.c_bool, [C.c_char_p]),
        ("AsstCreateEx", C.c_void_p, [callback_type, C.c_void_p]),
        ("AsstConnect", C.c_bool, [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p]),
        ("AsstAppendTask", C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
        ("AsstStart", C.c_bool, [C.c_void_p]),
        ("AsstRunning", C.c_bool, [C.c_void_p]),
        ("AsstStop", C.c_bool, [C.c_void_p]),
        ("AsstDestroy", None, [C.c_void_p]),
        ("AsstSetInstanceOption", C.c_bool, [C.c_void_p, C.c_int, C.c_char_p]),
        ("AsstGetVersion", C.c_char_p, []),
    ]:
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = restype, args
    events = queue.Queue()

    @callback_type
    def callback(msg, data, _):
        try:
            events.put((msg, json.loads(data.decode("utf-8")) if data else {}))
        except Exception as exc:
            events.put((0, {"error": str(exc)}))

    if not lib.AsstSetUserDir(str(folder).encode()) or not lib.AsstLoadResource(config.maa_dir.encode()) or not lib.AsstLoadResource(str(folder).encode()):
        raise RuntimeError("MAA 资源加载失败，请检查 MAA 版本和 runtime 日志")
    emit("version", version=lib.AsstGetVersion().decode())
    handle = lib.AsstCreateEx(callback, None)
    if not handle:
        raise RuntimeError("MAA 实例创建失败")
    recruitment_audit = NativeRecruitAudit(folder/'debug/asst.log', config, phase)
    cancelled = threading.Event()

    def read_commands():
        for line in sys.stdin:
            if line.strip() == "stop":
                cancelled.set()
                return
        if os.environ.get("BLACKFLOW_MANAGED") == "1":
            cancelled.set()  # 配置窗口 / 父进程消失时停止游戏操作。

    threading.Thread(target=read_commands, daemon=True).start()
    try:
        # ADB 自带输入方式；不使用 Win32 / 电脑鼠标。
        lib.AsstSetInstanceOption(handle, 2, b"adb")
        if not lib.AsstConnect(handle, config.adb_path.encode(), config.address.encode(), b"General"):
            raise RuntimeError("MAA 无法连接 MuMu ADB")
        if phase == "abandon":
            task_type = "Custom"
            params = {"task_names": ['AutoUtopia@AbandonBattle','RoguelikeBattleAbandon','AutoUtopia@AbandonRecruitAnimation','AutoUtopia@AbandonRecruitDialog',"BlackFlow@Roguelike@StartExplore", "BlackFlow@Roguelike@StartExploreCD", "BlackFlow@Roguelike@MissionFailedFlag2", "BlackFlow@Roguelike@Abandon", "BlackFlow@Roguelike@ExitThenAbandon"]}
        else:
            task_type = "Roguelike"
            params = {
                "theme": "BlackFlow", "mode": 0, "starts_count": 1,
                "difficulty": 0 if phase == "prepare" else config.difficulty,
                "squad": config.prepare_squad if phase == "prepare" else "文明开化分队",
                "roles": config.prepare_roles if phase == "prepare" else config.roles,
                "core_char_list": ([{"name": "机械师", "use_support": False}] if phase == "prepare" else
                                   [{"name": config.six_star, "use_support": config.use_support},
                                    *({"name": n, "use_support": False} for n in config.four_stars)]),
                "investment_enabled": phase == "prepare" and config.prepare_method == '绿商店投资', "investments_count": 999,
                "stop_when_investment_full": False,
                "use_nonfriend_support": config.use_nonfriend_support,
            }
            if phase == 'map':
                params.update(blackflow_strategy=COUNT_PROFILE,blackflow_diagnostics='detailed',blackflow_diagnostic_image_limit=0)
            elif phase == 'prepare' and config.prepare_method == '黄商店种植':
                params.update(blackflow_diagnostics='detailed',blackflow_diagnostic_image_limit=0)
        task_id = lib.AsstAppendTask(handle, task_type.encode(), json.dumps(params, ensure_ascii=False).encode())
        if not task_id or not lib.AsstStart(handle):
            raise RuntimeError("MAA 拒绝任务参数，可能需要更新 MAA")
        start = time.monotonic()
        completed = False
        reward_rejected = False
        error = None
        progress = WorkerProgress()
        recovery_attempts = 0
        latest_map = {}
        last_decision = {}
        repeated_level_reads = 0
        while True:
            try:
                msg, data = events.get(timeout=.1)
                if data.get('what') == 'BlackFlowMapSummary':
                    latest_map = data.get('details',{})
                    repeated_level_reads = 0
                if data.get('what') == 'BlackFlowRoutingDecision':
                    last_decision = data.get('details',{})
                if (phase == 'prepare' and config.prepare_method == '黄商店种植'
                    and data.get('what') == 'BlackFlowStrategyResult'):
                    data['details'] = optional_seed_completion(data.get('details',{}), latest_map)
                    result=data['details']
                    if (result.get('outcome') == 'planning_failed'
                        and result.get('termination_reason') == 'no eligible safe candidate'
                        and latest_map.get('floor_from_ocr') is True and latest_map.get('floor') in (1,2)):
                        result['optional_route_exhausted']=True
                emit("callback", msg=msg, data=data)
                progress.observe(msg, data)
                if msg == 20002 and data.get('subtask') == 'RoguelikeRecruitTask':
                    recruitment_audit.complete()
                    emit('recruitment_audit', **recruitment_audit.snapshot())
                current_task=data.get('details',{}).get('task','').split('@')[-1]
                if msg == 20001 and current_task == 'NextLevel':
                    repeated_level_reads += 1
                    if repeated_level_reads >= 6:
                        error = '重复读取同一楼层但未进入地图，保留现场；' + progress.summary()
                if (phase == 'prepare' and config.prepare_method == '黄商店种植'
                    and msg == 20003 and data.get('what') == 'BlackFlowRoutingDecision'
                    and last_decision.get('action_points_after',1) <= 0):
                    error='准备局移动预算守卫异常：出现耗尽行动力的原生回执，已停止并保留现场'
                if msg == 20001 and data.get("details", {}).get("task",'').split('@')[-1] in ("RecoveryWait", "RecoveryRecruitRead"):
                    recovery_attempts += 1
                    if recovery_attempts >= 12:
                        error = "本阶段识别恢复预算已用尽，保留现场；" + progress.summary()
                if msg == 20001 and data.get("details", {}).get("task",'').split('@')[-1] == "RecoveryExhausted":
                    error = "页面识别多次恢复失败，保留现场；" + progress.summary()
                if phase == "formal" and msg == 20001 and data.get("details", {}).get("task", "").endswith("RewardRejected"):
                    lib.AsstStop(handle)
                    reward_rejected = True
                    emit("reward_rejected", target=required_rewards(config),
                         requirement='排序前'+str(len(required_rewards(config)))+'项至少选到一项')
                    break
                if msg == 3:
                    completed = True
                if msg in (0, 1, 10000):
                    error = f"MAA 任务错误：{data}；{progress.summary()}"
                # 准备局结算由父进程的 abandon 阶段完成。成功回调之后立即停住，
                # 避免原生成功退出入口被识别恢复入口接管，再次扫描同一张地图。
                if phase == 'prepare' and msg == 20003 and data.get('what') == 'BlackFlowStrategyResult':
                    result = data.get('details',{})
                    if result.get('succeeded') is True and result.get('outcome') == 'burn_completed':
                        lib.AsstStop(handle)
                        completed = True
                        break
                    if (config.prepare_method == '黄商店种植' and result.get('outcome') == 'planning_failed'
                        and result.get('termination_reason') == 'no eligible safe candidate'
                        and latest_map.get('floor_from_ocr') is True and latest_map.get('floor') in (1,2)):
                        emit('prepare_route_exhausted',map_summary=latest_map,result=result)
                        lib.AsstStop(handle)
                        completed=True
                        break
                if phase == 'map' and msg == 20003 and data.get('what') == 'BlackFlowStrategyResult':
                    result=data.get('details',{})
                    lib.AsstStop(handle)  # 原生路由失败可能安排重开；只读统计必须在这里截住。
                    if result.get('profile') == COUNT_PROFILE and result.get('outcome') == 'planning_failed':
                        completed=True
                    else:
                        error='地图统计未正常结束：'+str(result)
                    break
            except queue.Empty:
                pass
            recruitment_audit.poll()
            if error:
                lib.AsstStop(handle)
                break
            if cancelled.is_set():
                lib.AsstStop(handle)
                raise RuntimeError("任务已停止")
            if time.monotonic() - start > config.phase_timeout:
                lib.AsstStop(handle)
                raise RuntimeError("阶段执行超时，保留现场；" + progress.summary())
            if not lib.AsstRunning(handle) and events.empty():
                break
        if phase == 'map' and not error:
            snapshots = []
            for path in (folder/'debug/BlackFlow').glob('*/snapshot.json'):
                if path.stat().st_mtime_ns < wall_started:
                    continue
                snapshot = json.loads(path.read_text(encoding='utf-8'))
                if snapshot.get('floor') == 1 and 'nodes' in snapshot:
                    snapshots.append(snapshot)
            emit('node_maps', snapshots=snapshots)
        emit("phase_stats", phase=phase, elapsed_seconds=round(time.monotonic()-phase_started,3),
             recovery_attempts=recovery_attempts)
        if error:
            raise RuntimeError(error)
        if not completed and not reward_rejected:
            raise RuntimeError("MAA 未正常完成阶段")
        emit("done", phase=phase)
    finally:
        lib.AsstStop(handle)
        lib.AsstDestroy(handle)
        dll_dir.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = Config(**json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
        run(config, sys.argv[1])
    except Exception as exc:
        emit("error", **error_event(exc))
        sys.exit(1)
