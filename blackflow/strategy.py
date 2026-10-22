"""以 MAA 原生地图、秘境行商培育与结果回调组合准备局策略。"""
from copy import deepcopy

PREPARE_METHODS = ('黄商店种植', '绿商店投资')
SEED_PROFILE = 'utopia_seed_burn'
COUNT_PROFILE = 'utopia_inspect_map'


def seed_action_point_rules():
    """移动前的硬限制；原生 reserves 在无候选时可被释放，不能用于防追猎。

    仅使用已核对计费的徒步（move_edges）与结构性原理（1点）。所有层
    留1点；前两层非出口移动留2点，以便保留的飞行还能安全退出。
    """
    def f(name,value,op='eq'):return {'fact':name,'op':op,'value':value}
    def forbid(name,when,conditions):
        return {'id':name,'kind':'forbid','tier':'legality','rank':0,
                'when':when,'candidate_if':{'all':conditions}}
    walk=f('candidate.movement','walk')
    flight=f('candidate.movement','rogue_6_scrap_M_11')
    rules=[forbid('utopia_ap_known_movement_only',f('current_floor',1,'ge'),
                  [f('candidate.movement','walk','ne'),f('candidate.movement','rogue_6_scrap_M_11','ne')]),
           forbid('utopia_ap_last_point_flight',f('action_points',1,'le'),[flight]),
           forbid('utopia_ap_keep_exit_flight',{'all':[f('current_floor',2,'le'),f('action_points',2,'le')]},
                  [flight,f('candidate.exit',False)])]
    # 地图最大路径远小于100；AP大于100时单次徒步无法耗尽。禁止结果>=预算，
    # 不依赖落点事件可能返还的行动力（追猎会先触发）。
    for points in range(1,101):
        rules.append(forbid(f'utopia_ap_walk_{points}',f('action_points',points),
                            [walk,f('candidate.move_edges',points,'ge')]))
        rules.append(forbid(f'utopia_ap_explore_{points}',
                            {'all':[f('action_points',points),f('current_floor',2,'le')]},
                            [walk,f('candidate.exit',False),f('candidate.move_edges',max(1,points-1),'ge')]))
    return rules


def optional_seed_completion(result, map_summary):
    """三层可选探索已经无安全路线，仍满足通过两层；不吞识别/执行故障。"""
    if (result.get('outcome') == 'planning_failed'
        and result.get('termination_reason') == 'no eligible safe candidate'
        and map_summary.get('floor') == 3 and map_summary.get('floor_from_ocr') is True):
        return {**result,'succeeded':True,'outcome':'burn_completed','next_action':'stop_run',
                'termination_reason':'third_floor_no_safe_optional_route',
                'native_result':dict(result),'map_observation_id':map_summary.get('observation_id')}
    return result


def seed_burn_strategy(strategy, require_animals=False):
    modules = {m['id']:m for m in strategy['modules']}
    route = deepcopy(modules['baby_animal_route'])
    route['id'] = 'utopia_seed_route'
    # 原生种植模块需要这些移动保留预算；只去黄商店，不绕绿商店买种子。
    # 没指定动物也要找黄商店；“尚未揭示”不能当作“本层没有”。
    route['milestones'] = [m for m in route['milestones'] if m['id'] in ('baby_explore_hidden','baby_visit_incident')]
    route['rules'] = [r for r in route['rules'] if r['id'] in ('avoid_empty_scrap_shop','baby_avoid_combat')]
    route['shopping_rules'] = []
    route['rules'].extend(seed_action_point_rules())
    for reserve in route.get('reserves',[]):
        if reserve['id']=='baby_keep_cultivation_movement':
            reserve['release_if']={'any':[reserve['release_if'],
                {'fact':'candidate.exit','op':'eq','value':True}]}
    direct = {'any':[{'fact':'candidate.movement','op':'eq','value':'rogue_6_scrap_M_11'},
                     {'fact':'candidate.movement','op':'eq','value':'walk'}]}
    def fact(name,value,op='eq'):return {'fact':name,'op':op,'value':value}
    def rule(name,when,target,*,prefer=False,rank=0):
        return {'id':name,'kind':'prefer' if prefer else 'require',
                'tier':'resource_reserve' if prefer else 'strategy_constraint','rank':rank,
                'when':{'all':when},'candidate_if':{'all':[direct,target]}}
    route['rules'] += [
        rule('utopia_seed_direct_yellow',[fact('cultivation_completed',False),fact('scrap_shop_available',True)],
             fact('candidate.node_type','scrap_shop'),prefer=True,rank=-1000),
        rule('utopia_seed_leave_after_plant',[fact('cultivation_completed',True),fact('current_floor',2,'le')],
             fact('candidate.exit',True),prefer=True,rank=-900),
        rule('utopia_seed_first_floor_without_yellow',[fact('current_floor',1),fact('scrap_shop_available',False)],
             fact('candidate.exit',True)),
    ]
    # 原生评分器不为 strategy_constraint 层的 prefer 计分。放到它实际
    # 优先评分的 resource_reserve 层，并排在“省加工品/探路”之前。
    # 仍是安全候选间的偏好；不可达黄店不会把撤离路线全部硬性禁掉。
    route['rules'].append({'id':'utopia_seed_fly_shop_or_exit_only','kind':'forbid','tier':'legality','rank':0,
        'candidate_if':{'all':[fact('candidate.movement','rogue_6_scrap_M_11'),
            fact('candidate.node_type','scrap_shop','ne'),fact('candidate.exit',False)]}})
    route['rules'].append({'id':'utopia_seed_keep_last_exit_flight','kind':'forbid','tier':'resource_reserve','rank':0,
        'when':{'all':[fact('current_floor',2,'le'),fact('persistent_full_map_count',1,'le')]},
        'candidate_if':{'all':[fact('candidate.movement','rogue_6_scrap_M_11'),fact('candidate.exit',False)]}})
    route['rules'].append({'id':'utopia_seed_no_battle','kind':'forbid','tier':'legality','rank':0,
        'candidate_if':fact('candidate.combat',True)})
    # 徒步探索仍由原生规划器保留抵达出口的预算；不能硬禁出口，否则
    # “还存在候选”但只剩被策略禁止的节点时会无路可走。
    # 能徒步探索就优先徒步；仍允许原生规划器在保证出口预算时飞未知节点，
    # 不把唯一可行的寻找黄商店的路线一并禁止。
    route['rules'].append({'id':'utopia_seed_save_flight','kind':'prefer','tier':'resource_reserve','rank':0,
        'candidate_if':{'all':[fact('candidate.movement','walk'),
            {'any':[fact('candidate.node_type','hide_invisible'),fact('candidate.node_type','incident')]}]}})
    cultivate = deepcopy(modules['baby_cultivate_gated'])
    cultivate['id'] = 'utopia_seed_cultivate'
    # 找不到黄商店是可选种植未完成，不应原生无限重开或强制要求某动物。
    final = next(m for m in cultivate['milestones'] if m['id']=='baby_cultivate_scrap_shop_final')
    final['on_miss']='ignore'
    for key in ('miss_outcome','miss_reason'):
        final.pop(key,None)
    # 只复用满天赋机械师赠送移动物品，不沿用“二层必须直飞出口”。
    flight = deepcopy(modules['mechanic_flight'])
    flight['id']='utopia_seed_flight'
    flight['rules']=[]
    profile = {
        'id':SEED_PROFILE,'description':'有合适黄商店就尝试种植，抵达第三层即完成；动物要求由外层可选筛选判断',
        'modules':['common_navigation','utopia_seed_flight','utopia_seed_route','utopia_seed_cultivate','burn_route'],
        'terminal_rules':[
            {'id':'utopia_seed_prepared','when':{'all':[fact('current_floor',3,'ge'),
                fact('cultivation_completed',True)]},
             'outcome':'burn_completed','reason':'third_floor_reached','succeeded':True,'next_action':'stop_run'},
        ],'failure_action':'stop_run','no_AP_is_terminal':{'floors':[3]},
    }
    strategy['modules'] += [route,flight,cultivate]
    strategy['profiles'].append(profile)
    # 原生快速烧水跳过后两张券的条件要求 blackflow_strategy 参数为空。
    # 替换默认无投资 burn 策略，使机械师单人开局保持原生语义。
    default_profile = next(p for p in strategy['profiles'] if p['id']=='burn')
    default_profile.clear()
    default_profile.update(deepcopy({**profile,'id':'burn'}))
    return profile


def map_inspection_strategy(strategy):
    # 所有候选均被禁止，原生解析地图后无法移动；只读取其节点诊断快照。
    strategy['modules'].append({'id':'utopia_no_movement','rules':[
        {'id':'utopia_forbid_every_move','kind':'forbid','tier':'legality','rank':0,
         'candidate_if':{'any':[{'fact':'candidate.combat','op':'eq','value':True},
                               {'fact':'candidate.combat','op':'eq','value':False}]}}]})
    strategy['profiles'].append({'id':COUNT_PROFILE,'modules':['common_navigation','utopia_no_movement'],
                                 'failure_action':'stop_run'})
