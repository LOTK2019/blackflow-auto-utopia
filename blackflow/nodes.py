"""基于 MAA 原生完整地图快照统计，不把总格子数当成有效节点数。"""
from collections import Counter


def effective_nodes(snapshot):
    if snapshot.get('floor') != 1 or not snapshot.get('floor_from_ocr'):
        raise ValueError('未确认第一层')
    nodes = snapshot.get('nodes')
    if not isinstance(nodes,list) or not nodes or len(nodes) != snapshot.get('node_count'):
        raise ValueError('节点列表不完整')
    positions = [(n.get('row'),n.get('column')) for n in nodes]
    if len(set(positions)) != len(nodes):
        raise ValueError('节点位置重复')
    if any(n.get('identity_state') == 'unclassified' or n.get('type') in (None,'unknown','unclassified','') for n in nodes):
        raise ValueError('地图含未识别节点，需重扫')
    counts = Counter(n['type'] for n in nodes)
    result = sum(count for name,count in counts.items() if name != 'empty')
    return {'effective':result,'empty':counts.get('empty',0),'total':len(nodes),'types':dict(counts),
            'observation_id':snapshot.get('observation_id'),'map_revision':snapshot.get('map_revision')}
