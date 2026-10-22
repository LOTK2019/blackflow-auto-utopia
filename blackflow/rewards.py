"""开局奖励目录与优先级；六个蓝色选项来自羽蛇，不把被动襁褓收益混进选择列表。"""
NORMAL_REWARDS = {'空间租赁':'6','林间代步':'2','调查预付款':'5','未编号物':'4','退行补偿':'','巢寄生':'3'}
SERPENT_REWARDS = ('襁褓天马','襁褓骏鹰','襁褓巨龙','襁褓九头蛇','襁褓白泽','襁褓金乌')
DEFAULT_REWARD_ORDER = ['空间租赁','林间代步','调查预付款','未编号物','退行补偿',*SERPENT_REWARDS,'巢寄生']
REWARD_DESCRIPTIONS = {
    '空间租赁':'消耗6源石锭，零件箱容量+2', '林间代步':'获得1件加工品',
    '调查预付款':'获得8源石锭', '未编号物':'获得1件普通收藏品',
    '退行补偿':'消耗2目标生命值上限，获得1件随机收藏品', '巢寄生':'零件箱容量-1，获得1件稀有收藏品',
    '襁褓天马':'每次进入新区域时，初始行动力+1',
    '襁褓骏鹰':'初始希望+1，揭示前两个区域全部节点',
    '襁褓巨龙':'前两个区域的敌人最大生命-50%',
    '襁褓九头蛇':'敌人攻击和生命+30%；每进入新区域，我方攻击和生命+10%',
    '襁褓白泽':'干员招募时更容易出现临时招募',
    '襁褓金乌':'进入第三区域时，获得3件随机收藏品',
}


def reward_plan(config):
    order = list(config.reward_priority)
    strict = config.require_first_reward
    # 兼容旧配置及旧版开发调用；新 UI 保存时清除旧筛选字段。
    if config.reward_target != '默认排序':
        name = config.reward_target.split('（',1)[0]
        order.remove(name)
        order.insert(0,name)
        strict = True
    return order, strict


def install_reward_tasks(tasks, config):
    p = 'BlackFlow@Roguelike@'
    order, strict = reward_plan(config)
    commit='AutoUtopia@RewardCommit'
    names = {}
    for name in order:
        if name in NORMAL_REWARDS:
            names[name] = p+'LastReward'+NORMAL_REWARDS[name]
            tasks[names[name]] = {'next':[commit]}
        else:
            task = 'AutoUtopia@Reward'+name.removeprefix('襁褓')
            names[name] = task
            tasks[task] = {'algorithm':'OcrDetect','text':[name.removeprefix('襁褓')],
                           'roi':[82,364,1116,201],'action':'ClickSelf','next':[commit],'postDelay':200}
    if not strict:
        tasks[p+'LastReward-Strategy'] = {'next':[names[n] for n in order]}
    else:
        # 先重扫三次，只有识别到其它已知卡片才判定第一项缺席。
        # 不认识的画面不会进入“目标未出现”的分支。
        others = [n for n in order if n != order[0]]
        probes = []
        normal = [p+'LastReward'+NORMAL_REWARDS[n]+'.png' for n in others if n in NORMAL_REWARDS]
        for suffix, algorithm, matcher in (
            ('Normal','MatchTemplate',{'template':normal,'roi':[82,145,1116,310]}),
            ('Blue','OcrDetect',{'text':[n.removeprefix('襁褓') for n in others if n in SERPENT_REWARDS],
                                'roi':[82,364,1116,201]})):
            key='AutoUtopia@RewardMissing'+suffix
            tasks[key]={'algorithm':algorithm,**matcher,'action':'DoNothing','postDelay':1000,
                        'maxTimes':3,'next':[p+'LastReward-Strategy'],
                        'exceededNext':['AutoUtopia@RewardRejected']}
            probes.append(key)
        tasks[p+'LastReward-Strategy']={'next':[names[order[0]],*probes]}
        tasks['AutoUtopia@RewardRejected']={'algorithm':'JustReturn','action':'DoNothing','postDelay':30000,'next':['Stop']}
    # 所有选择留在同一次 ProcessTask 中。严格检查仅在入口执行；
    # 第一项被选中并确认后，后续页固定走普通排序，不再次要求第一项。
    decision='AutoUtopia@RewardNormalDecision'
    ready=['AutoUtopia@RewardClose','AutoUtopia@RewardRolesReady',
           'AutoUtopia@RewardRecruitReady','AutoUtopia@RewardNextSelection']
    tasks[decision]={'algorithm':'JustReturn','next':[names[n] for n in order]}
    # 原生动态主题任务作为 baseTask 时，模板不能依赖名称推导，否则会
    # 尝试读取不存在的 AutoUtopia@*.png。
    tasks[commit]={'baseTask':p+'LastRewardConfirm','template':p+'LastRewardConfirm.png','postDelay':700,'next':ready}
    tasks[ready[0]]={'baseTask':p+'CloseCollection','template':p+'CloseCollection.png','next':ready}
    tasks[ready[1]]={'baseTask':p+'RolesDefault','template':p+'RolesDefault.png','action':'DoNothing','next':[]}
    tasks[ready[2]]={'baseTask':p+'RecruitMain','template':p+'Recruit.png','action':'DoNothing','next':[]}
    tasks[ready[3]]={'algorithm':'MatchTemplate',
        'template':[p+'LastReward'+suffix+'.png' for suffix in NORMAL_REWARDS.values()],
        'roi':[82,145,1116,310],'action':'DoNothing','next':[decision],
        'maxTimes':4,'exceededNext':['Stop']}
    # 奖励子流程已负责确认全部选择，外层从招募组合/招募券继续。
    tasks[p+'LastReward-EnterPoint']={'next':[p+'RolesDefault',p+'RecruitMain',p+'Stages#next']}
