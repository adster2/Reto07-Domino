"""Short-lived display memory for standalone Camo recognition."""
from dataclasses import dataclass

import cv2
import numpy as np

from recognize_domino import normalize
from static_domino import iou


@dataclass
class Observation:
    polygon: np.ndarray
    identity: tuple
    texture: np.ndarray
    observed_at: float
    misses: int = 0


class LiveTileMemory:
    def __init__(self, max_age=.9, max_misses=3):
        self.max_age = max_age
        self.max_misses = max_misses
        self.clear()

    def clear(self):
        self.entries = []

    @staticmethod
    def _texture(gray, polygon):
        crop, _ = normalize(gray, polygon, {'width': 96, 'height': 48})
        crop = crop.astype(np.float32)
        background = cv2.GaussianBlur(crop, (0, 0), 4)
        contrast = np.maximum((background-crop)/np.maximum(background, 30)-.10, 0)
        return contrast[7:-7, 8:-8]

    @staticmethod
    def _same_face(previous, current):
        # Compare both interiors independently so a changed blank half is visible.
        for a, b in ((previous[:, :34], current[:, :34]),
                     (previous[:, -34:], current[:, -34:])):
            difference = np.abs(a-b).sum()
            if difference > .50*max(a.sum(), b.sum(), 3):
                return False
        return True

    @staticmethod
    def _same_position(previous, current):
        short_edge = min(np.linalg.norm(previous-np.roll(previous, 1, axis=0), axis=1))
        shift = np.linalg.norm(previous.mean(axis=0)-current.mean(axis=0))
        return shift <= .12*short_edge and iou(previous, current) >= .80

    def update(self, bundle, now):
        report = bundle['report']
        polygons = [np.float32(item['vertices']) for item in report['detections']]
        gray = cv2.cvtColor(bundle['original'], cv2.COLOR_BGR2GRAY)
        links = [[i for i, polygon in enumerate(polygons) if self._same_position(entry.polygon, polygon)]
                 for entry in self.entries]
        previous = {indices[0]: entry for entry, indices in zip(self.entries, links)
                    if len(indices) == 1
                    and sum(indices[0] in other for other in links) == 1}
        visible = {tuple(sorted(r['identity'])) for r in report['readings'] if r['identity'] is not None}
        entries, held = [], []
        for index, (polygon, reading) in enumerate(zip(polygons, report['readings'])):
            if reading['identity'] is not None:
                entries.append(Observation(polygon, tuple(reading['identity']), self._texture(gray, polygon), now))
                continue
            entry = previous.get(index)
            if entry is None or entry.misses >= self.max_misses or now-entry.observed_at >= self.max_age:
                continue
            if tuple(sorted(entry.identity)) in visible:
                continue
            partial = reading.get('spatial_order', {}).get('values', ())
            if any(value is not None and value != old for value, old in zip(partial, entry.identity)):
                continue
            if not self._same_face(entry.texture, self._texture(gray, entry.polygon)):
                continue
            entry.misses += 1
            entries.append(entry)
            held.append({'index': index, 'identity': list(entry.identity),
                         'expires_at': entry.observed_at+self.max_age, 'vertices': polygon.tolist()})
        self.entries = entries
        bundle['held'] = held
        report['temporal_memory'] = [
            {'index': item['index'], 'identity': item['identity'],
             'remaining_seconds': round(item['expires_at']-now, 3)} for item in held
        ]

    @staticmethod
    def draw(canvas, held, now, *, chains=False):
        color = (255, 230, 80)
        for item in held:
            if now >= item['expires_at']:
                continue
            box = np.int32(np.rint(item['vertices']))
            cv2.polylines(canvas, [box], True, color, 2, cv2.LINE_AA)
            a, b = item['identity']
            label = f'[{a}|{b}] MEM'
            x = max(0, int(box[:, 0].min()))
            y = max(18, int(box[:, 1].min())-8)
            if chains:
                center = box.mean(axis=0)
                x, y = max(0, int(center[0]-25)), max(18, int(center[1]+5))
            (width, height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .65, 2)
            cv2.rectangle(canvas, (x, y-height-3), (x+width+4, y+4), (30, 30, 30), -1)
            cv2.putText(canvas, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .65, color, 2, cv2.LINE_AA)

