"""Interpretazione logica indipendente da OpenCV, immagini e ground truth."""
from collections import defaultdict
from itertools import combinations


def valid_value(value):
    return type(value) is int and 0 <= value <= 6


def validate_tiles(tiles):
    ids = set()
    for tile in tiles:
        identifier = tile['id']
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError('Ogni tessera deve avere un identificatore stringa unico non vuoto')
        ids.add(identifier)
        values = tile.get('values')
        if values is not None and (not isinstance(values, (list, tuple)) or len(values) != 2
                                   or not all(valid_value(v) for v in values)):
            raise ValueError(f'Valori non validi per {identifier}: usare [0..6,0..6] oppure None')


def pair_compatibility(a, b):
    validate_tiles([a, b])
    av, bv = a.get('values'), b.get('values')
    if av is None or bv is None:
        return {'ids': [a['id'], b['id']], 'status': 'unknown', 'common_values': [], 'connections': []}
    common = sorted(set(av) & set(bv))
    connections = []
    for value in common:
        # Convenzione esplicita: A a sinistra di B, contatto A[1] == B[0].
        reverse_a, reverse_b = av[1] != value, bv[0] != value
        oriented_a = list(reversed(av)) if reverse_a else list(av)
        oriented_b = list(reversed(bv)) if reverse_b else list(bv)
        connections.append({'common_value': value, 'oriented_a': oriented_a, 'oriented_b': oriented_b,
                            'reverse_a': reverse_a, 'reverse_b': reverse_b,
                            'logical_turn_a_deg': 180 if reverse_a else 0,
                            'logical_turn_b_deg': 180 if reverse_b else 0})
    return {'ids': [a['id'], b['id']], 'status': 'compatible' if common else 'incompatible',
            'common_values': common, 'connections': connections}


def chain_moves(tiles, ends, used_ids=()):
    validate_tiles(tiles)
    if len(ends) != 2 or not all(valid_value(v) for v in ends):
        raise ValueError('Le estremita devono essere due interi da 0 a 6')
    used = set(used_ids)
    if used - {tile['id'] for tile in tiles}:
        raise ValueError('Identificatore di tessera gia usata assente dalla scena')
    left, right = ends
    result = []
    for tile in tiles:
        identifier, values = tile['id'], tile.get('values')
        item = {'id': identifier, 'sides': [], 'options': []}
        if identifier in used:
            item['status'] = 'already_used'
        elif values is None:
            item['status'] = 'unknown'
        else:
            for side, contact in [('left', left), ('right', right)]:
                if contact not in values:
                    continue
                reverse = (values[1] != contact) if side == 'left' else (values[0] != contact)
                oriented = list(reversed(values)) if reverse else list(values)
                new_ends = [oriented[0], right] if side == 'left' else [left, oriented[1]]
                item['sides'].append(side)
                item['options'].append({'side': side, 'oriented_values': oriented,
                                        'reverse': reverse, 'logical_turn_deg': 180 if reverse else 0,
                                        'new_ends': new_ends})
            item['status'] = 'both' if len(item['sides']) == 2 else (item['sides'][0] if item['sides'] else 'not_playable')
        result.append(item)
    return result


def analyze_scene(tiles, ends=None, used_ids=()):
    validate_tiles(tiles)
    recognized = [tile for tile in tiles if tile.get('values') is not None]
    unknown = [tile['id'] for tile in tiles if tile.get('values') is None]
    identities = defaultdict(list)
    doubles = {str(v): [] for v in range(7)}
    for tile in recognized:
        a, b = tile['values']
        identities[tuple(sorted((a, b)))].append(tile['id'])
        if a == b:
            doubles[str(a)].append(tile['id'])
    comparisons = [pair_compatibility(a, b) for a, b in combinations(tiles, 2)]
    if ends is None and used_ids:
        raise ValueError('Fornire le estremita quando si escludono tessere gia usate')
    return {'detected_count': len(tiles), 'recognized_count': len(recognized),
            'unknown_count': len(unknown), 'unknown_ids': unknown,
            'tiles': [{'id': t['id'], 'values': list(t['values']) if t.get('values') is not None else None} for t in tiles],
            'recognized_pip_sum': sum(sum(t['values']) for t in recognized),
            'sum_incomplete': bool(unknown), 'sum_complete_for_detected_tiles': not unknown,
            'doubles': doubles,
            'duplicates': [{'values': list(values), 'ids': ids} for values, ids in sorted(identities.items()) if len(ids) > 1],
            'single_set_assumed': True,
            'compatible_pairs': [p for p in comparisons if p['status'] == 'compatible'],
            'incompatible_pairs': [p for p in comparisons if p['status'] == 'incompatible'],
            'unknown_pairs': [p for p in comparisons if p['status'] == 'unknown'],
            'chain_ends': list(ends) if ends is not None else None,
            'chain_moves': chain_moves(tiles, ends, used_ids) if ends is not None else None}
