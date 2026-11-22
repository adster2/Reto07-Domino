"""Dataset procedurale e rilevamento geometrico. Nessun riconoscimento puntini."""
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEED = 7072026
PATTERNS = {
    0: [], 1: [(0, 0)], 2: [(-1, -1), (1, 1)],
    3: [(-1, -1), (0, 0), (1, 1)],
    4: [(-1, -1), (-1, 1), (1, -1), (1, 1)],
    5: [(-1, -1), (-1, 1), (1, -1), (1, 1), (0, 0)],
    6: [(-1, -1), (-1, 0), (-1, 1), (1, -1), (1, 0), (1, 1)],
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def write_image(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f'Impossibile salvare {path}')


def vertices(center, length, angle):
    """Vertici ordinati del rettangolo ideale; angolo orario sul piano immagine."""
    rad = np.deg2rad(angle)
    rotation = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
    local = np.array([[-length/2, -length/4], [length/2, -length/4],
                      [length/2, length/4], [-length/2, length/4]])
    return (local @ rotation.T + center).astype(np.float32)


def iou(a, b):
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    intersection, _ = cv2.intersectConvexConvex(a, b)
    union = cv2.contourArea(a) + cv2.contourArea(b) - intersection
    return float(intersection / union) if union > 0 else 0.0


def tile_sprite(a, b):
    # Disegno ad alta risoluzione per ottenere bordi e puntini antialias.
    sprite = np.zeros((128, 256, 4), np.uint8)
    white = (236, 239, 242, 255)
    cv2.rectangle(sprite, (8, 0), (247, 127), white, -1)
    cv2.rectangle(sprite, (0, 8), (255, 119), white, -1)
    for x, y in [(8, 8), (247, 8), (8, 119), (247, 119)]:
        cv2.circle(sprite, (x, y), 8, white, -1, cv2.LINE_AA)
    cv2.line(sprite, (128, 8), (128, 120), (80, 80, 80, 255), 2, cv2.LINE_AA)
    for cx, value in [(64, a), (192, b)]:
        for px, py in PATTERNS[value]:
            cv2.circle(sprite, (cx + 30*px, 64 + 30*py), 9, (18, 18, 18, 255), -1, cv2.LINE_AA)
    return sprite


def generate_dataset(root=ROOT, seed=SEED):
    rng = np.random.default_rng(seed)
    specifications = [
        ('Una tessera orizzontale', [(2, 4)], False),
        ('Una tessera ruotata', [(3, 6)], False),
        ('Tre tessere orizzontali', [(0, 2), (1, 5), (4, 6)], False),
        ('Cinque orientamenti casuali', [(0, 0), (1, 3), (2, 6), (4, 5), (3, 3)], False),
        ('Sei tessere distribuite', [(0, 4), (1, 6), (2, 2), (3, 5), (4, 4), (5, 6)], False),
        ('Valori zero', [(0, 0), (0, 1), (0, 3), (0, 5), (0, 6)], False),
        ('Valori elevati', [(5, 5), (5, 6), (6, 6), (2, 5), (3, 6)], False),
        ('Dimensioni apparenti differenti', [(1, 1), (2, 3), (3, 4), (4, 6), (0, 6)], False),
        ('Ombre e illuminazione variabile', [(0, 2), (1, 4), (2, 5), (3, 6), (5, 5)], True),
        ('Sei tessere vicine ruotate', [(0, 5), (1, 2), (2, 4), (3, 3), (4, 5), (6, 6)], True),
    ]
    for scene_index, (description, pairs, lighting) in enumerate(specifications, 1):
        image = np.empty((720, 1280, 3), np.float32)
        image[:] = (47, 116, 48)
        image += rng.normal(0, 1.5, (720, 1280, 1)).astype(np.float32)
        if lighting:
            yy, xx = np.mgrid[:720, :1280]
            light = 0.76 + 0.27 * xx/1280 + 0.05 * np.sin(yy/160)
            image *= light[..., None]
        image = np.clip(image, 0, 255).astype(np.uint8)
        tiles = []
        clearance = np.zeros((720, 1280), np.uint8)
        centers = [(350, 220), (640, 220), (930, 220), (350, 470), (640, 470), (930, 470)]
        if len(pairs) == 1:
            centers = [(640, 360)]
        elif scene_index == 3:
            centers = [(290, 360), (640, 360), (990, 360)]
        elif scene_index == 10:
            centers = [(460, 260), (640, 260), (820, 260), (460, 440), (640, 440), (820, 440)]
        for tile_index, (a, b) in enumerate(pairs):
            for attempt in range(2000):
                length = float([100, 140, 180, 220, 260][tile_index]) if scene_index == 8 else (160.0 if scene_index == 10 else 188.0)
                angle = 0.0 if scene_index in (1, 3) else (32.0 if scene_index == 2 else float(rng.uniform(-85, 85)))
                center = np.array(centers[tile_index], dtype=float)
                if scene_index not in (1, 2, 3):
                    center += rng.uniform(-18, 18, 2)
                polygon = vertices(center, length, angle)
                mask = np.zeros_like(clearance)
                cv2.fillConvexPoly(mask, np.rint(polygon).astype(np.int32), 255)
                if np.any(polygon < 20) or np.any(polygon[:, 0] > 1259) or np.any(polygon[:, 1] > 699):
                    continue
                # Distanza minima esplicita: 6 px (scena 10), 20 px nelle altre.
                expanded = cv2.dilate(mask, np.ones((7 if scene_index == 10 else 21,)*2, np.uint8))
                if not np.any(cv2.bitwise_and(expanded, clearance)):
                    clearance = cv2.bitwise_or(clearance, expanded)
                    break
            else:
                raise RuntimeError('Impossibile collocare le tessere senza sovrapposizione')
            if lighting:
                shadow_matrix = np.float32([[1, 0, 7], [0, 1, 9]])
                shadow = cv2.warpAffine(mask, shadow_matrix, (1280, 720))
                shadow = cv2.GaussianBlur(shadow, (25, 25), 5)/255.0
                image = np.clip(image.astype(float) * (1 - 0.25 * shadow[..., None]), 0, 255).astype(np.uint8)
            sprite = tile_sprite(a, b)
            transform = cv2.getAffineTransform(np.float32([[0, 0], [256, 0], [0, 128]]), polygon[[0, 1, 3]])
            warped = cv2.warpAffine(sprite, transform, (1280, 720), flags=cv2.INTER_LINEAR)
            alpha = warped[:, :, 3:4].astype(float)/255
            color = warped[:, :, :3].astype(float)
            if lighting:
                color *= float(rng.uniform(0.83, 1.0))
            image = np.clip(image * (1-alpha) + color*alpha, 0, 255).astype(np.uint8)
            xmin, ymin = polygon.min(axis=0)
            xmax, ymax = polygon.max(axis=0)
            tiles.append({'id': tile_index+1, 'values': [a, b], 'center': center.tolist(),
                          'angle_deg': angle, 'length': length, 'width': length/2,
                          'vertices': polygon.tolist(), 'bbox_xyxy': [float(xmin), float(ymin), float(xmax), float(ymax)]})
        filename = f'synthetic_{scene_index:02d}.png'
        write_image(root/'data/synthetic'/filename, image)
        write_json(root/'data/ground_truth'/f'synthetic_{scene_index:02d}.json', {
            'image': filename, 'seed': seed, 'scene': description, 'size': [1280, 720],
            'coordinate_convention': 'pixel x right, y down; degrees clockwise; vertices TL,TR,BR,BL in local frame',
            'tile_count': len(tiles), 'total_pips': sum(a+b for a, b in pairs), 'tiles': tiles})


def detect(image, config):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    background = cv2.inRange(hsv, np.array(config['green_hsv_low']), np.array(config['green_hsv_high']))
    objects = cv2.bitwise_not(background)
    cleaned = cv2.morphologyEx(objects, cv2.MORPH_OPEN, np.ones((config['opening_kernel'],)*2, np.uint8))
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, np.ones((config['closing_kernel'],)*2, np.uint8))
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_view = image.copy()
    cv2.drawContours(contour_view, contours, -1, (255, 80, 0), 2)
    annotated = image.copy()
    candidates, detections = [], []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        rect = cv2.minAreaRect(contour)
        sides = rect[1]
        short, long = sorted(sides)
        if short == 0:
            continue
        ratio = long/short
        rectangularity = area/(long*short)
        box = cv2.boxPoints(rect)
        edges = np.roll(box, -1, axis=0)-box
        edge = edges[np.argmax(np.linalg.norm(edges, axis=1))]
        angle = float(np.degrees(np.arctan2(edge[1], edge[0])) % 180)
        moment = cv2.moments(contour)
        center = [moment['m10']/moment['m00'], moment['m01']/moment['m00']] if moment['m00'] else list(rect[0])
        rejected = []
        if not config['min_area'] <= area <= config['max_area']:
            rejected.append('area')
        if not config['min_aspect'] <= ratio <= config['max_aspect']:
            rejected.append('aspect_ratio')
        if rectangularity < config['min_rectangularity']:
            rejected.append('rectangularity')
        item = {'area': area, 'perimeter': perimeter, 'aspect_ratio': ratio,
                'rectangularity': rectangularity, 'center': center, 'angle_deg': angle,
                'vertices': box.tolist(), 'rejected_by': rejected}
        candidates.append(item)
        if not rejected:
            detections.append(item)
            cv2.polylines(annotated, [np.rint(box).astype(np.int32)], True, (0, 0, 255), 3, cv2.LINE_AA)
            x, y = map(int, center)
            cv2.putText(annotated, f'T{len(detections)}', (x-15, y), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 220), 2)
    return detections, candidates, {'01_original': image, '02_background': background,
                                   '03_objects': objects, '04_morphology': cleaned,
                                   '05_contours': contour_view, '06_final': annotated}


def match_detections(detections, truth, threshold):
    # Associazione bipartita a cardinalita massima, soglia IoU su rettangoli orientati.
    scores = [[iou(d['vertices'], t['vertices']) for t in truth] for d in detections]
    owner = {}
    def augment(di, seen):
        for ti in sorted(range(len(truth)), key=lambda t: scores[di][t], reverse=True):
            if scores[di][ti] < threshold or ti in seen:
                continue
            seen.add(ti)
            if ti not in owner or augment(owner[ti], seen):
                owner[ti] = di
                return True
        return False
    for di in range(len(detections)):
        augment(di, set())
    pairs = [{'detection': di, 'truth': ti, 'iou': scores[di][ti],
              'center_error_px': float(np.linalg.norm(np.array(detections[di]['center'])-truth[ti]['center']))}
             for ti, di in owner.items()]
    tp = len(pairs)
    fp, fn = len(detections)-tp, len(truth)-tp
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': tp/(tp+fp) if tp+fp else (1.0 if not truth else 0.0),
            'recall': tp/(tp+fn) if tp+fn else 1.0, 'matches': pairs}


def run_pipeline(root=ROOT, config_path=None):
    config_path = config_path or root/'config/detection.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    rows, details, panels = [], [], []
    for annotation in sorted((root/'data/ground_truth').glob('synthetic_*.json')):
        gt = json.loads(annotation.read_text(encoding='utf-8'))
        image = cv2.imread(str(root/'data/synthetic'/gt['image']))
        if image is None:
            raise OSError(f'Immagine non leggibile: {gt["image"]}')
        detected, candidates, debug = detect(image, config)
        score = match_detections(detected, gt['tiles'], config['match_iou'])
        errors = [m['center_error_px'] for m in score['matches']]
        overlaps = [m['iou'] for m in score['matches']]
        row = {'image': gt['image'], 'real_tiles': gt['tile_count'], 'detected_tiles': len(detected),
               **{k: score[k] for k in ['tp', 'fp', 'fn', 'precision', 'recall']},
               'mean_iou': float(np.mean(overlaps)) if overlaps else '',
               'mean_center_error_px': float(np.mean(errors)) if errors else ''}
        rows.append(row)
        stem = annotation.stem
        for name, output in debug.items():
            write_image(root/'results/debug'/stem/f'{name}.png', output)
        write_image(root/'results/final'/f'{stem}_detected.png', debug['06_final'])
        details.append({'image': gt['image'], 'detections': detected, 'candidates': candidates, 'evaluation': score})
        if stem in ('synthetic_01', 'synthetic_08', 'synthetic_09', 'synthetic_10'):
            left = cv2.resize(image, (640, 360))
            right = cv2.resize(debug['06_final'], (640, 360))
            panel = np.hstack([left, right])
            band = np.full((42, 1280, 3), 245, np.uint8)
            cv2.putText(band, f'{stem}: originale', (12, 28), cv2.FONT_HERSHEY_SIMPLEX, .7, (30, 30, 30), 1)
            cv2.putText(band, f'Rilevate {len(detected)}/{gt["tile_count"]} | TP {score["tp"]} FP {score["fp"]} FN {score["fn"]}', (652, 28), cv2.FONT_HERSHEY_SIMPLEX, .65, (30, 30, 30), 1)
            panel = np.vstack([band, panel])
            panels.append(panel)
            write_image(root/'results/final'/f'{stem}_comparison.png', panel)
    if not rows:
        raise RuntimeError('Nessuna ground truth trovata. Generare prima il dataset.')
    with (root/'results/metrics.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    totals = {k: sum(r[k] for r in rows) for k in ['real_tiles', 'detected_tiles', 'tp', 'fp', 'fn']}
    totals['precision'] = totals['tp']/(totals['tp']+totals['fp']) if totals['tp']+totals['fp'] else 0
    totals['recall'] = totals['tp']/(totals['tp']+totals['fn']) if totals['tp']+totals['fn'] else 0
    all_matches = [m for detail in details for m in detail['evaluation']['matches']]
    totals['mean_iou'] = float(np.mean([m['iou'] for m in all_matches])) if all_matches else None
    totals['mean_center_error_px'] = float(np.mean([m['center_error_px'] for m in all_matches])) if all_matches else None
    write_json(root/'results/evaluation.json', {'seed': SEED, 'config': config, 'totals': totals, 'images': details})
    write_image(root/'results/final/comparisons.png', np.vstack(panels))
    print(json.dumps(totals, indent=2))
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='Genera il dataset deterministico')
    parser.add_argument('--show', action='store_true', help='Mostra confronti, spazio/N avanti, Q esce')
    parser.add_argument('--config', type=Path, default=ROOT/'config/detection.json')
    args = parser.parse_args()
    if args.generate or not list((ROOT/'data/synthetic').glob('synthetic_*.png')):
        generate_dataset()
    run_pipeline(config_path=args.config)
    if args.show:
        title = 'Domino statico | SPAZIO/N: avanti | Q: chiudi'
        try:
            for path in sorted((ROOT/'results/final').glob('*_comparison.png')):
                cv2.namedWindow(title, cv2.WINDOW_NORMAL)
                cv2.imshow(title, cv2.imread(str(path)))
                while True:
                    key = cv2.waitKey(100) & 0xFF
                    if key in (ord('q'), ord('Q'), 27):
                        return
                    if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                        return
                    if key in (32, ord('n'), ord('N')):
                        break
        finally:
            cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
