"""整理已完成的账户实测；人工坐标来自对保存地图的逐点查看，不参与运行时判断。"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SESSION=ROOT/'artifacts/20261022-141547-429128'


def main():
    data=json.loads((SESSION/'001-nodes-1.json').read_text(encoding='utf-8'))
    nodes=data['maps'][-1]['nodes']
    # 人工直接查看 001-nodes-1.png：上排2、中排3、下排3。
    manual={(0,1),(0,4),(1,1),(1,2),(1,3),(2,1),(2,2),(2,4)}
    detected={(n['row'],n['column']) for n in nodes if n['type']!='empty'}
    assert manual==detected and data['accepted']['effective']==8
    result={'manual_effective':8,'manual_empty':4,'manual_row_counts':[2,3,3],
            'detected_effective':data['accepted']['effective'],'coordinates_match':manual==detected,
            'image':'001-nodes-1.png','scope':'非空节点位置与数量；隐藏节点具体类型不作为人工确认',
            'type_notes':[{'position':[1,3],'native':'shop','visible':'未知的诡秘'},
                          {'position':[2,4],'native':'final','visible':'未知的诡秘'}]}
    (SESSION/'manual-node-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    verification=json.loads((SESSION/'verification.json').read_text(encoding='utf-8'))
    assert verification['account_flow_passed'] is True
    summary={'date':'2026-10-22','engine':'v6.20.1','full_flow_passed':True,
             'preparation':'第二层黄商店种植，两帧确认猫2，随后通过第二层到第三层',
             'formal_difficulty':16,'operators':['结城理','冬时','深海色'],
             'opening_reward':'空间租赁','formal_map':'玻利瓦尔肤层',
             'node_check':result,'dystopia':'连续四帧确认无邦，退出后准备新循环；联调入口在新准备开始前停止',
             'default_node_filter_enabled':False,'default_animal_counts':{'猫':0,'狗':0,'三头犬':0},
             'limitations':['三头犬多次奖励选择与全部蓝色奖励尚未逐项进行账户实测']}
    (ROOT/'runtime/seed-flow-verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
