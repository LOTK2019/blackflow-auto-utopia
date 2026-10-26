"""基于 MAA 原生完整地图快照统计，不把总格子数当成有效节点数。"""
from collections import Counter


def _geometry(snapshot):
    if any(e.get('forced_by_connectivity_constraint') for e in snapshot['edges']):
        raise ValueError('含强制补全连线，不能作为统计拓扑证据')
    nodes = snapshot['nodes']
    positions = {n['id']: (n['row'], n['column']) for n in nodes}
    if len(positions) != len(nodes) or len(set(positions.values())) != len(nodes):
        raise ValueError('节点位置或编号重复')
    edges = {tuple(sorted((positions[e['first']], positions[e['second']])))
             for e in snapshot['edges'] if e.get('knowledge') == 'confirmed'}
    return positions, edges


def reconcile_node_maps(observations, templates):
    """完整识别作锚点，再按固定拓扑逐位置复核空地/有效；不用于导航。"""
    anchors = []
    for group in observations:
        for snapshot in group:
            try:
                effective_nodes(snapshot)
                positions, edges = _geometry(snapshot)
                matches = []
                for template in templates:
                    expected = {tuple(sorted(map(tuple, edge))) for edge in template['edges']}
                    cells = {p for edge in expected for p in edge}
                    if (template['floor'] == 1 and snapshot['rows'] == template['rows']
                            and snapshot['columns'] == template['columns']
                            and set(positions.values()) == cells and edges == expected
                            and positions[snapshot['current_node']] == tuple(template['start'])
                            and {positions[n['id']] for n in snapshot['nodes'] if n['type'] == 'final'}
                            == set(map(tuple, template['terminals']))):
                        matches.append((template, cells, expected))
                if len(matches) == 1:
                    anchors.append(matches[0])
            except (ValueError, KeyError, TypeError):
                continue
    if not anchors or len({a[0]['id'] for a in anchors}) != 1:
        return None
    template, cells, edges = anchors[0]
    votes = {p: Counter() for p in cells}
    ignored = set()
    supporting = 0
    for group in observations:
        readings = {p: set() for p in cells}
        usable = False
        for snapshot in group:
            try:
                positions, observed_edges = _geometry(snapshot)
                extras = set(positions.values()) - cells
                if (snapshot.get('floor') != 1 or not snapshot.get('floor_from_ocr')
                        or snapshot.get('node_count') != len(snapshot['nodes'])
                        or snapshot['rows'] != template['rows'] or snapshot['columns'] != template['columns']
                        or positions[snapshot['current_node']] != tuple(template['start'])
                        or not cells <= set(positions.values())
                        or {e for e in observed_edges if set(e) <= cells} != edges
                        or any(n['type'] != 'unclassified' for n in snapshot['nodes']
                               if positions[n['id']] in extras)):
                    continue
                usable = True
                ignored.update(extras)
                for node in snapshot['nodes']:
                    p = positions[node['id']]
                    if p in cells and node.get('identity_state') != 'unclassified' and node.get('type') not in (None, '', 'unknown', 'unclassified'):
                        readings[p].add(node['type'] != 'empty')
            except (ValueError, KeyError, TypeError):
                continue
        supporting += usable
        # 同一 worker 的两个快照不算两票；同轮相互矛盾则该位置弃票。
        for p, values in readings.items():
            if len(values) == 1:
                votes[p][next(iter(values))] += 1
    if any(len(v) != 1 or sum(v.values()) < 2 for v in votes.values()):
        return None
    count = sum(next(iter(v)) for v in votes.values())
    return {'effective': count, 'empty': len(cells)-count, 'total': len(cells),
            'types': {'nonempty': count, 'empty': len(cells)-count},
            'method': 'topology_binary_consensus', 'template': template['id'],
            'supporting_observations': supporting, 'ignored_unclassified_positions': sorted(ignored),
            'node_votes': [{'row': p[0], 'column': p[1], 'effective': next(iter(v)),
                            'observations': sum(v.values())} for p,v in sorted(votes.items())]}


def effective_nodes(snapshot):
    if snapshot.get('floor') != 1 or not snapshot.get('floor_from_ocr'):
        raise ValueError('未确认第一层')
    nodes = snapshot.get('nodes')
    if not isinstance(nodes,list) or not nodes or len(nodes) != snapshot.get('node_count'):
        raise ValueError('节点列表不完整')
    positions = [(n.get('row'),n.get('column')) for n in nodes]
    if len(set(positions)) != len(nodes):
        raise ValueError('节点位置重复')
    unknown = [(n.get('row'), n.get('column')) for n in nodes
               if n.get('identity_state') == 'unclassified' or n.get('type') in (None,'unknown','unclassified','')]
    if unknown:
        raise ValueError(f'地图含未识别节点 {unknown}，需重扫')
    counts = Counter(n['type'] for n in nodes)
    result = sum(count for name,count in counts.items() if name != 'empty')
    return {'effective':result,'empty':counts.get('empty',0),'total':len(nodes),'types':dict(counts),
            'observation_id':snapshot.get('observation_id'),'map_revision':snapshot.get('map_revision')}
