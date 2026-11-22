"""Stato e verifica del tavolo digitale, indipendenti dalla partita assistita."""
from collections import defaultdict
from dataclasses import dataclass

import cv2
import numpy as np

from live_tile_memory import LiveTileMemory
from recognize_domino import normalize
from static_domino import iou


def tile_faces(vertices, halves=()):
    polygon = np.asarray(vertices, dtype=float)
    edges = np.roll(polygon, -1, axis=0) - polygon
    a, b, c, d = np.roll(polygon, -int(np.argmax(np.linalg.norm(edges, axis=1))), axis=0)
    top, bottom = (a+b)/2, (c+d)/2
    faces = (np.array([a, top, bottom, d]), np.array([top, b, c, bottom]))
    first = (min(halves, key=lambda half: half['reading_rank'])['camera_center']
             if halves else min((face.mean(axis=0) for face in faces),
                                key=lambda point: point[int(abs(b[1]-a[1]) > abs(b[0]-a[0]))]))
    if np.linalg.norm(faces[1].mean(axis=0)-first) < np.linalg.norm(faces[0].mean(axis=0)-first):
        return faces[::-1]
    return faces


def short_side(polygon):
    return float(min(np.linalg.norm(np.roll(polygon, -1, axis=0)-polygon, axis=1)))


@dataclass
class SceneTile:
    polygon: np.ndarray
    faces: tuple
    values: tuple
    current: tuple | None
    uncertain: bool
    from_memory: bool = False


def signature(lab, polygon):
    crop, _ = normalize(lab, polygon, {'width': 96, 'height': 48})
    # Media locale per attenuare il rumore, mantenendo puntini, divisoria e faccia.
    smooth = cv2.GaussianBlur(crop, (3, 3), 0).astype(np.float32)
    return smooth[5:-5, 5:-5]


def same_region(reference, current):
    diff = np.abs(current-reference)
    # Una variazione moderata e uniforme di luce non equivale a una rimozione.
    light_shift = np.clip(np.median(current[:, :, 0]-reference[:, :, 0]), -22, 22)
    luma = np.abs(current[:, :, 0]-reference[:, :, 0]-light_shift)
    changed = (luma > 23) | (diff[:, :, 1:].max(axis=2) > 17)
    # Basta una zona della dimensione di un puntino, anche se il resto coincide.
    local = cv2.boxFilter(np.float32(changed), -1, (7, 7))
    return changed.mean() < .045 and local.max() < .38


class SceneMemory:
    def __init__(self, divider_threshold):
        self.divider_threshold = divider_threshold
        self.clear()

    def clear(self):
        self.entries = []

    def update(self, bundle):
        report = bundle['report']
        lab = cv2.cvtColor(bundle['original'], cv2.COLOR_BGR2LAB)
        polygons = [np.float32(item['vertices']) for item in report['detections']]
        # Confronto con il riferimento originale, anche quando il rilevatore perde la sagoma.
        candidates = []
        for tile, reference in self.entries:
            if not same_region(reference, signature(lab, tile.polygon)):
                continue
            matches = [i for i, polygon in enumerate(polygons)
                       if LiveTileMemory._same_position(tile.polygon, polygon)]
            overlaps = [i for i, polygon in enumerate(polygons) if iou(tile.polygon, polygon) > .20]
            if len(matches) == 1 and overlaps == matches:
                candidates.append((matches[0], tile, reference))
            elif not overlaps:
                candidates.append((None, tile, reference))

        by_index = defaultdict(list)
        for index, tile, reference in candidates:
            by_index[index].append((tile, reference))
        tiles, entries = [], []
        for index, (polygon, reading) in enumerate(zip(polygons, report['readings'])):
            identity = reading['identity']
            current = tuple(identity) if identity is not None else None
            spatial = reading.get('spatial_order', {})
            weak = current is None or reading.get('divider_coverage', 1) < self.divider_threshold+.06
            matches = by_index[index]
            if len(matches) == 1:
                old, reference = matches[0]
                uncertain = weak or current != old.values
                tile = SceneTile(old.polygon, old.faces, old.values, current, uncertain, uncertain)
                entries.append((tile, reference))
            else:
                partial = (spatial.get('values', (None, None))
                           if reading.get('reasons') == ['invalid_half'] else (None, None))
                tile = SceneTile(polygon, tile_faces(polygon, spatial.get('halves', ())),
                                 current if current is not None else tuple(partial), current, weak)
                if not weak:
                    entries.append((tile, signature(lab, polygon)))
            tiles.append(tile)
        for old, reference in by_index[None]:
            tile = SceneTile(old.polygon, old.faces, old.values, None, True, True)
            entries.append((tile, reference))
            tiles.append(tile)
        self.entries = entries
        return tiles


def scene_preview(frame):
    height, width = frame.shape[:2]
    if width > 480:
        frame = cv2.resize(frame, (480, max(1, round(480*height/width))), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(frame, (3, 3), 0)


def scene_changed(reference, current):
    if reference is None or reference.shape != current.shape:
        return True
    changed = np.float32(cv2.absdiff(reference, current).max(axis=2) > 13)
    return cv2.boxFilter(changed, -1, (5, 5)).max() >= .16


def edges(polygon):
    center = polygon.mean(axis=0)
    for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
        delta = end-start
        length = np.linalg.norm(delta)
        direction = delta/length
        normal = np.array([-direction[1], direction[0]])
        if (center-start) @ normal > 0:
            normal = -normal
        yield start, end, length, direction, normal


def contact(first, second):
    """Cerca bordi affrontati con sovrapposizione reale, escludendo i soli angoli."""
    side = min(short_side(first), short_side(second))
    if np.linalg.norm(first.mean(axis=0)-second.mean(axis=0)) > 1.4*(short_side(first)+short_side(second)):
        return None
    contacts = []
    for a, _, length, axis, normal in edges(first):
        for b, c, _, _, other_normal in edges(second):
            if normal @ other_normal > -.94:
                continue
            low, high = sorted(((b-a) @ axis, (c-a) @ axis))
            start, end = max(0, low), min(length, high)
            if end-start < .28*side:
                continue
            pos = (start+end)/2
            point = a+pos*axis
            other = b+(c-b)*((pos-low)/(high-low) if (c-b) @ axis > 0 else (high-pos)/(high-low))
            gap = (other-point) @ normal
            if -.14*side <= gap <= .18*side:
                contacts.append((end-start, abs(gap), point, other))
    if contacts:
        return max(contacts, key=lambda item: (item[0], -item[1]))[2:]
    return None


def contact_face(tile, point):
    first, second = (face.mean(axis=0) for face in tile.faces)
    axis = (second-first)/np.linalg.norm(second-first)
    projection = (point-(first+second)/2) @ axis
    # Una doppia trasversale può ricevere il contatto al centro del lato lungo.
    if tile.values[0] == tile.values[1] and tile.values[0] is not None:
        return 0
    if abs(projection) < .12*short_side(tile.polygon):
        return None
    return int(projection > 0)


def check_chain(tiles):
    contacts = []
    by_tile, by_face = defaultdict(list), defaultdict(list)
    uncertain, wrong = set(), set()
    for i, first in enumerate(tiles):
        for j in range(i+1, len(tiles)):
            second = tiles[j]
            points = contact(first.polygon, second.polygon)
            if points is None:
                continue
            a, b = contact_face(first, points[0]), contact_face(second, points[1])
            index = len(contacts)
            contacts.append((i, j, points))
            if a is None or b is None or first.values[a] is None or second.values[b] is None:
                uncertain.update((i, j))
                continue
            by_tile[i].append(index)
            by_tile[j].append(index)
            for k, tile, face in ((i, first, a), (j, second, b)):
                if tile.values[0] != tile.values[1]:
                    by_face[k, face].append(index)
            if first.values[a] != second.values[b]:
                wrong.add(index)
    for indices in by_tile.values():
        if len(indices) > 2:
            wrong.update(indices)
    for indices in by_face.values():
        if len(indices) > 1:
            wrong.update(indices)
    # In una componente senza diramazioni, tutti i nodi di grado due formano un ciclo.
    visited = set()
    for start in by_tile:
        component, pending = set(), [start]
        while pending:
            k = pending.pop()
            if k in visited:
                continue
            visited.add(k)
            component.add(k)
            for index in by_tile[k]:
                i, j, _ = contacts[index]
                pending.append(j if i == k else i)
        if component and all(len(by_tile[k]) == 2 for k in component):
            for k in component:
                wrong.update(by_tile[k])
    return uncertain, [contacts[index] for index in sorted(wrong)]
