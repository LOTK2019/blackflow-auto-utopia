"""从实际完成的准备阶段回调核对步数约束，不连接或操作游戏。"""
import json
from pathlib import Path
import sys


def audit(session):
    complete=[];failures=[];moves=[];mismatches=[];exhausted=[]
    for path in sorted(Path(session).glob('*-prepare.jsonl')):
        events=[]
        for line in path.read_text(encoding='utf-8').splitlines():
            try:events.append(json.loads(line))
            except json.JSONDecodeError:continue
        if not any(e.get('kind') in ('done','error') for e in events):continue
        complete.append(path.name)
        failures.extend({'file':path.name,'error':e} for e in events if e.get('kind')=='error')
        for event in events:
            data=event.get('data',{})
            if data.get('what')!='BlackFlowRoutingDecision':continue
            d=data['details'];moves.append(d)
            if d.get('action_points_after',0)<=0:exhausted.append({'file':path.name,'decision':d})
            bound=d.get('path_edge_count') if d.get('movement')=='walk' else 1
            if d.get('movement') not in ('walk','rogue_6_scrap_M_11') or d.get('exact_cost',0)>bound:
                mismatches.append({'file':path.name,'decision':d})
    report={'completed_prepare_attempts':len(complete),'executed_moves':len(moves),
            'minimum_remaining_ap':min((d['action_points_after'] for d in moves),default=None),
            'zero_ap_moves':exhausted,'unexpected_movement_costs':mismatches,'worker_errors':failures}
    (Path(session)/'ap-budget-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    print(json.dumps(audit(sys.argv[1]),ensure_ascii=False))
