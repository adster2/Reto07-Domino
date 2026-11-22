"""Albero decisionale geometrico dei puntini. Non accede alla ground truth."""
import json
import cv2
import numpy as np
from static_domino import ROOT
from spatial_order import order_halves


def normalize(image, polygon, config):
    points = np.asarray(polygon, np.float32)
    # minAreaRect restituisce vertici ciclici: inizia da un lato lungo.
    lengths = np.linalg.norm(np.roll(points, -1, axis=0)-points, axis=1)
    start = int(np.argmax(lengths))
    points = np.roll(points, -start, axis=0)
    w, h = config['width'], config['height']
    target = np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]])
    transform = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(image, transform, (w, h)), transform


def recognize_half(gray, config):
    white = float(np.percentile(gray, 75))
    threshold = min(config['dark_max'], white*config['dark_white_ratio'])
    mask = np.uint8(gray < threshold)*255
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    valid_surface = np.ones(gray.shape, dtype=bool)
    candidates, pips, suspicious = [], [], []
    for label in range(1, count):
        x, y, w, h, area = map(int, stats[label])
        component = np.uint8(labels == label)*255
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, True)
        circularity = 4*np.pi*cv2.contourArea(contour)/(perimeter*perimeter) if perimeter else 0
        fraction = area/gray.size
        aspect = w/h
        border = x == 0 or y == 0 or x+w == gray.shape[1] or y+h == gray.shape[0]
        reason = None
        if area < config['noise_area']:
            reason = 'tiny_noise'
        elif border and config.get('ignore_border_bands', False) and (
            max(w/h, h/w) >= config['band_aspect_min']
            and fraction <= config['band_area_max_fraction']
            and ((w/gray.shape[1] >= config['band_span_min_fraction'] and h/gray.shape[0] <= config['band_thickness_max_fraction'])
                 or (h/gray.shape[0] >= config['band_span_min_fraction'] and w/gray.shape[1] <= config['band_thickness_max_fraction'])
                 or (fraction <= config.get('band_fragment_max_fraction', 0)
                     and min(h/gray.shape[0], w/gray.shape[1]) <= config.get('band_fragment_thickness_max_fraction', 0)))
        ):
            reason = 'ignored_border_band'
            valid_surface[labels == label] = False
        elif border:
            reason = 'border_or_occlusion'
        elif not config['area_min_fraction'] <= fraction <= config['area_max_fraction']:
            reason = 'area'
        elif not config['aspect_min'] <= aspect <= config['aspect_max']:
            reason = 'aspect'
        elif circularity < config['circularity_min']:
            reason = 'circularity'
        item = {'area': area, 'area_fraction': fraction, 'aspect': aspect,
                'circularity': float(circularity), 'center': centers[label].tolist(),
                'bbox': [x, y, w, h], 'rejected_by': reason}
        candidates.append(item)
        if reason is None:
            pips.append(item)
        elif reason not in ('tiny_noise', 'ignored_border_band'):
            suspicious.append(item)
        cv2.rectangle(overlay, (x, y), (x+w, y+h), (0, 220, 0) if reason is None else (0, 0, 255), 1)
    reasons = []
    white_fraction = float(np.mean(gray[valid_surface] >= config['min_white'])) if np.any(valid_surface) else 0.0
    if white < config['min_white'] or white_fraction < config['min_white_fraction']:
        reasons.append('insufficient_white_surface')
    if suspicious:
        reasons.append('unexplained_dark_components')
    if len(pips) > config['max_count']:
        reasons.append('more_than_six_pips')
    value = None if reasons else len(pips)
    return {'value': value, 'reasons': reasons, 'white_level': white,
            'white_fraction': white_fraction, 'threshold': threshold, 'components': candidates}, mask, overlay


def compensate_luminance(gray):
    # Il percentile alto stima la faccia chiara limitando l'effetto dei puntini.
    white = float(np.percentile(gray, 75))
    target = float(np.clip(white, 185, 225))
    gain = float(np.clip(target/max(white, 1), .85, 1.25))
    corrected = cv2.convertScaleAbs(gray, alpha=gain)
    local = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4)).apply(corrected)
    return cv2.addWeighted(corrected, .7, local, .3, 0)


def recognize(image, polygon, config=None, *, preprocess=False):
    config = config or json.loads((ROOT/'config/recognition.json').read_text())
    tile, transform = normalize(image, polygon, config)
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    if preprocess:
        gray = compensate_luminance(gray)
    h, w = gray.shape
    margin, search = config['margin'], config['divider_search']
    central = gray[margin:h-margin, w//2-search:w//2+search+1]
    threshold = min(config['dark_max'], float(np.percentile(gray, 75))*config['dark_white_ratio'])
    coverage = np.mean(central < threshold, axis=0)
    divider = int(w//2-search+np.argmax(coverage))
    divider_ok = float(np.max(coverage)) >= config['divider_min_coverage']
    gap = config['divider_margin']
    halves = [gray[margin:h-margin, margin:divider-gap], gray[margin:h-margin, divider+gap:w-margin]]
    results, masks, regions = [], [], []
    for half in halves:
        result, mask, region = recognize_half(half, config)
        results.append(result)
        masks.append(mask)
        regions.append(region)
    values = [result['value'] for result in results]
    reasons = [] if divider_ok else ['divider_not_verified']
    if any(v is None for v in values):
        reasons.append('invalid_half')
    # Le metà restano diagnosticabili; la tessera è rifiutata se manca la divisoria.
    spatial = order_halves(values, transform, w, h, divider)
    identity = spatial['values'] if not reasons else None
    visual = tile.copy()
    cv2.line(visual, (divider, 0), (divider, h-1), (0, 220, 0) if divider_ok else (0, 0, 255), 1)
    label = f'[{identity[0]}|{identity[1]}]' if identity is not None else '[?|?]'
    cv2.putText(visual, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 220), 1)
    report = {'identity': identity, 'half_values': values, 'reasons': reasons,
              'divider_x': divider, 'divider_coverage': float(np.max(coverage)),
              'halves': results, 'transform': transform.tolist(),
              'normalized_identity': values if not reasons else None, 'spatial_order': spatial}
    images = {'normalized': tile, 'divider_check': visual,
                    'half_0': halves[0], 'half_1': halves[1],
                    'mask_0': masks[0], 'mask_1': masks[1],
                    'regions_0': regions[0], 'regions_1': regions[1]}
    if preprocess:
        images['preprocessed_gray'] = gray
    return report, images


def retry_with_preprocessing(image, polygon, config, reading, images):
    if reading['identity'] is not None:
        return reading, images
    filtered, diagnostics = recognize(image, polygon, config, preprocess=True)
    identity = filtered['identity']
    partial = reading['spatial_order']['values']
    if identity is not None and all(value is None or value == new for value, new in zip(partial, identity)):
        filtered['photometric_retry'] = True
        return filtered, diagnostics
    images['preprocessed_gray'] = diagnostics['preprocessed_gray']
    return reading, images
