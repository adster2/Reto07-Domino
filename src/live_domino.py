"""Task 07: acquisizione Camo indipendente e riuso della pipeline congelata."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

import cv2
import numpy as np
from webcam import list_cameras
from static_domino import ROOT, detect, write_image, write_json
from recognize_domino import recognize, retry_with_preprocessing
from real_domino import detect_white_faces
from live_tile_memory import LiveTileMemory


def unique_name(prefix):
    return f'{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:8]}'


class LatestCamera:
    """Un solo thread possiede VideoCapture; slot ultimo frame, nessuna coda lunga."""
    def __init__(self, index, factory=cv2.VideoCapture):
        self.index, self.factory = index, factory
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.packet = None
        self.error = None
        self.frames = 0
        self.failures = 0
        self.read_total = 0.0
        self.read_max = 0.0
        self.first_at = self.last_at = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        camera = None
        try:
            camera = self.factory(self.index, cv2.CAP_DSHOW)
            if not camera.isOpened():
                raise RuntimeError('Camo trovata ma non apribile: controllare altre applicazioni video.')
            consecutive_failures = 0
            while not self.stop_event.is_set():
                begin = time.perf_counter()
                ok, frame = camera.read()
                now = time.perf_counter()
                duration = now-begin
                if not ok or frame is None or not frame.size:
                    with self.lock:
                        self.failures += 1
                    consecutive_failures += 1
                    if consecutive_failures >= 10:
                        raise RuntimeError('Acquisizione interrotta: dieci letture senza fotogramma.')
                    self.stop_event.wait(.1)
                    continue
                consecutive_failures = 0
                with self.lock:
                    self.frames += 1
                    self.read_total += duration
                    self.read_max = max(self.read_max, duration)
                    if self.first_at is None:
                        self.first_at = now
                    self.last_at = now
                    self.packet = (self.frames, now, duration, frame)
        except Exception as error:
            with self.lock:
                self.error = str(error)
        finally:
            if camera is not None:
                camera.release()

    def snapshot(self):
        with self.lock:
            duration = (self.last_at-self.first_at) if self.frames > 1 else 0
            stats = {'acquired_frames': self.frames, 'read_failures': self.failures,
                     'acquired_fps': (self.frames-1)/duration if duration else 0.0,
                     'mean_acquisition_ms': 1000*self.read_total/self.frames if self.frames else 0.0,
                     'max_acquisition_ms': 1000*self.read_max}
            return self.packet, self.error, stats

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=1)
        # Mai release dal thread GUI mentre read e ancora attivo nel driver.


def select_camera(names, requested='Camo'):
    matches = [i for i, name in enumerate(names) if name.casefold() == requested.casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'Sorgente {requested!r} assente o ambigua. Disponibili: {names}')
    return matches[0]


def analyze_frame(frame, detection_config, recognition_config, experimental_chains=False, *, preprocess=False):
    options = {'preprocess': True} if preprocess else {}
    if experimental_chains:
        from task08a import analyze
        return analyze(frame, detection_config, recognition_config, **options)
    begin = time.perf_counter()
    detector = detect_white_faces if detection_config.get('white_face_refinement') else detect
    detections, candidates, debug = detector(frame, detection_config)
    annotated = frame.copy()
    readings, tile_debug = [], []
    for i, detection in enumerate(detections, 1):
        polygon = detection['vertices']
        result, images = recognize(frame, polygon, recognition_config)
        if preprocess:
            result, images = retry_with_preprocessing(frame, polygon, recognition_config, result, images)
        readings.append({'id': f'T{i}', **result})
        tile_debug.append(images)
        values = result['identity']
        label = f'[{values[0]}|{values[1]}]' if values is not None else '[?|?]'
        color = (20, 20, 230) if values is not None else (0, 170, 255)
        box = np.int32(np.rint(detection['vertices']))
        cv2.polylines(annotated, [box], True, color, 2, cv2.LINE_AA)
        x = max(0, int(box[:, 0].min()))
        y = max(20, int(box[:, 1].min())-8)
        cv2.putText(annotated, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .65, color, 2, cv2.LINE_AA)
    green = float(np.count_nonzero(debug['02_background'])/debug['02_background'].size)
    recognized = sum(r['identity'] is not None for r in readings)
    warnings = []
    # Solo allarmi diagnostici, non cambiano maschere o decisioni della pipeline.
    if green < .35:
        warnings.append('Poco verde: verificare tappeto, luce e inquadratura')
    if recognized < len(readings):
        warnings.append('Tessere incerte: premere D per diagnostica')
    if not detections:
        warnings.append('Nessuna tessera rilevata: tappeto vuoto o rilevamento fallito')
    report = {'detected_count': len(detections), 'recognized_count': recognized,
              'unknown_count': len(readings)-recognized, 'green_fraction': green,
              'warnings': warnings, 'detections': detections, 'candidates': candidates,
              'readings': readings, 'pipeline_ms': 1000*(time.perf_counter()-begin)}
    return {'original': frame, 'annotated': annotated, 'debug': debug,
            'tiles': tile_debug, 'report': report}


def save_bundle(bundle, session, reason, timing=None):
    folder = session/unique_name(reason)
    folder.mkdir(parents=True, exist_ok=False)
    write_image(folder/'original.png', bundle['original'])
    write_image(folder/'annotated.png', bundle['annotated'])
    for name, image in bundle['debug'].items():
        write_image(folder/'detection'/f'{name}.png', image)
    for index, images in enumerate(bundle['tiles'], 1):
        for name, image in images.items():
            write_image(folder/'tiles'/f'T{index}'/f'{name}.png', image)
    write_json(folder/'recognition.json', bundle['report'])
    write_json(folder/'timing.json', timing or {})
    return str(folder)


def save_original(frame):
    folder = ROOT/'data/real'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/f'{unique_name("camo_live")}.png'
    write_image(path, frame)
    return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='Camo')
    parser.add_argument('--profile', choices=['real', 'original'], default='real', help='Profilo tessere fisiche oppure soglie sintetiche originali')
    parser.add_argument('--chains', action='store_true', help='Ricostruzione geometrica sperimentale delle catene')
    parser.add_argument('--seconds', type=float, default=0, help='0: fino a Q; positivo: durata massima')
    parser.add_argument('--headless', action='store_true', help='Misura senza finestra, richiede --seconds')
    parser.add_argument('--preprocess', action=argparse.BooleanOptionalAction,
                        help='Compensazione luminosa iniziale (attiva nel profilo real)')
    parser.add_argument('--legacy', action='store_true', help='Avvia senza compensazione e senza memoria temporale')
    args = parser.parse_args()
    preprocess = args.preprocess if args.preprocess is not None else args.profile == 'real'
    preprocess = preprocess and not args.legacy
    memory = None if args.legacy else LiveTileMemory()
    if args.seconds < 0 or (args.headless and args.seconds <= 0):
        parser.error('La misura headless richiede --seconds positivo')
    if args.chains and args.profile != 'real':
        parser.error('La modalita catene richiede --profile real')
    detection_path = ROOT/'config'/('detection_live.json' if args.profile == 'real' else 'detection.json')
    detection_config = json.loads(detection_path.read_text(encoding='utf-8-sig'))
    recognition_path = ROOT/'config'/('recognition_live.json' if args.profile == 'real' else 'recognition.json')
    recognition_config = json.loads(recognition_path.read_text(encoding='utf-8-sig'))
    session = ROOT/'results/task07'/unique_name('session')
    session.mkdir(parents=True, exist_ok=False)
    write_json(session/'configuration.json', {'profile': args.profile, 'experimental_chains': args.chains,
                                             'chain_config': json.loads((ROOT/'config/chain_vision.json').read_text()) if args.chains else None,
                                             'detection': detection_config, 'recognition': recognition_config,
                                             'initial_preprocess': preprocess, 'temporal_memory': memory is not None,
                                             'diagnostic_only': {'min_green_fraction': .35, 'slow_read_seconds': .5,
                                                                 'stale_seconds': 1, 'no_frame_timeout_seconds': 10,
                                                                 'automatic_save_interval_seconds': 15, 'automatic_save_limit': 10}})
    camera = None
    writer = ThreadPoolExecutor(max_workers=1)
    pending, saved, save_errors = [], [], []
    processed = skipped = auto_saved = 0
    pipeline_times = []
    latest_bundle = None
    latest_timing = {}
    last_seq = 0
    started = time.perf_counter()
    first_processed = last_processed = None
    last_auto = -float('inf')
    last_stats = started
    last_counts = (0, 0)
    acquired_fps = processed_fps = 0.0
    error_text = None
    title = 'Reto 07 LIVE CATENA SPERIMENTALE' if args.chains else 'Reto 07 LIVE'
    message = ''
    message_until = 0.0
    try:
        names = list_cameras()
        index = select_camera(names, args.name)
        print(f'Sorgenti: {names}; selezionata {names[index]} (DirectShow {index})', flush=True)
        camera = LatestCamera(index).start()
        started = last_stats = time.perf_counter()
        while True:
            now = time.perf_counter()
            if args.seconds and now-started >= args.seconds:
                break
            for future in list(pending):
                if future.done():
                    try:
                        path = future.result()
                        saved.append(path)
                        print(f'Salvato: {path}', flush=True)
                        message, message_until = 'Salvato: '+Path(path).name, now+3
                    except Exception as error:
                        save_errors.append(str(error))
                        print(f'ERRORE salvataggio: {error}', flush=True)
                        message, message_until = 'Salvataggio fallito: vedere terminale', now+5
                    pending.remove(future)
            packet, acquisition_error, capture_stats = camera.snapshot()
            if acquisition_error:
                raise RuntimeError(acquisition_error)
            if packet is None:
                if now-started > 10:
                    raise RuntimeError('Nessun fotogramma da Camo entro 10 secondi.')
                if not args.headless and cv2.waitKey(20) & 255 in (ord('q'), ord('Q'), 27):
                    break
                time.sleep(.005)
                continue
            seq, received, read_seconds, frame = packet
            if seq != last_seq:
                skipped += max(0, seq-last_seq-1)
                last_seq = seq
                latest_bundle = analyze_frame(frame, detection_config, recognition_config, args.chains,
                                              preprocess=preprocess)
                latest_bundle['report']['preprocessing'] = preprocess
                if memory is not None:
                    memory.update(latest_bundle, received)
                processed += 1
                last_processed = time.perf_counter()
                if first_processed is None:
                    first_processed = last_processed
                pipeline_times.append(latest_bundle['report']['pipeline_ms'])
                age = last_processed-received
                latest_timing = {'sequence': seq, 'read_ms': read_seconds*1000,
                                 'age_since_local_receive_ms': age*1000,
                                 'pipeline_ms': pipeline_times[-1]}
                report = latest_bundle['report']
                problematic = report['unknown_count'] > 0 or report['green_fraction'] < .35
                if args.chains:
                    geometry = report['chain_geometry']
                    problematic = problematic or bool(geometry['ambiguous'] or geometry['unresolved_components'])
                if problematic and now-last_auto >= 15 and auto_saved < 10 and len(pending) < 2:
                    pending.append(writer.submit(save_bundle, latest_bundle, session, 'automatic_problem', latest_timing))
                    auto_saved += 1
                    last_auto = now
            now = time.perf_counter()
            if now-last_stats >= 1:
                acquired_fps = (capture_stats['acquired_frames']-last_counts[0])/(now-last_stats)
                processed_fps = (processed-last_counts[1])/(now-last_stats)
                last_counts, last_stats = (capture_stats['acquired_frames'], processed), now
                summary = {'acquired_fps_window': round(acquired_fps, 2), 'processed_fps_window': round(processed_fps, 2),
                           'resolution': [frame.shape[1], frame.shape[0]],
                           **{k: latest_bundle['report'][k] for k in ['detected_count', 'recognized_count', 'unknown_count', 'green_fraction']},
                           **latest_timing}
                write_json(session/'latest_metrics.json', summary)
                print(json.dumps(summary), flush=True)
            if now-received > 10:
                raise RuntimeError('Flusso bloccato: nessun nuovo fotogramma da 10 secondi.')
            if args.headless:
                time.sleep(.002)
                continue
            h, w = frame.shape[:2]
            header = np.full((112, max(w, 1024), 3), 30, np.uint8)
            held = [item for item in latest_bundle.get('held', []) if now < item['expires_at']]
            lines = [f'{w}x{h} | FPS acquisiti {acquired_fps:.1f} | FPS elaborati {processed_fps:.1f}',
                     f'Tessere {latest_bundle["report"]["detected_count"]} | Riconosciute {latest_bundle["report"]["recognized_count"]} | Incerte {latest_bundle["report"]["unknown_count"]} | lettura {read_seconds*1000:.1f}ms | pipeline {pipeline_times[-1]:.1f}ms',
                     f'P: luce {"ON" if preprocess else "OFF"} | memoria: {len(held)} (azzurro) | S: originale | D: diagnostica | Q: chiudi'
                     if not args.legacy else 'S: salva originale | D: salva diagnostica | Q: chiudi']
            alerts = list(latest_bundle['report']['warnings'])
            if read_seconds > .5:
                alerts.append('Acquisizione lenta: controllare Camo/Wi-Fi')
            if now-received > 1:
                alerts.append('Fotogramma vecchio: nessun aggiornamento recente')
            lines.append(message if now < message_until else (' | '.join(alerts) if alerts else 'Verificare visivamente i valori; nessuna logica delle mosse'))
            for i, line in enumerate(lines):
                cv2.putText(header, line[:150], (10, 23+26*i), cv2.FONT_HERSHEY_SIMPLEX, .53, (230, 230, 230), 1, cv2.LINE_AA)
            canvas = np.zeros((h, header.shape[1], 3), np.uint8)
            canvas[:, :w] = latest_bundle['annotated']
            if memory is not None:
                memory.draw(canvas[:, :w], held, now, chains=args.chains)
            cv2.namedWindow(title, cv2.WINDOW_NORMAL)
            cv2.imshow(title, np.vstack([header, canvas]))
            key = cv2.waitKey(1) & 255
            if key in (ord('q'), ord('Q'), 27) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key in (ord('p'), ord('P')) and not args.legacy:
                preprocess = not preprocess
                memory.clear()
                latest_bundle = {**latest_bundle, 'held': []}
                message, message_until = 'Filtro luce attivo' if preprocess else 'Filtro luce disattivato', now+2
            if key in (ord('s'), ord('S'), ord('d'), ord('D')):
                if len(pending) < 2:
                    future = writer.submit(save_original, latest_bundle['original']) if key in (ord('s'), ord('S')) else writer.submit(save_bundle, latest_bundle, session, 'manual_D', latest_timing)
                    pending.append(future)
                    message, message_until = 'Salvataggio in corso...', now+2
                else:
                    message, message_until = 'Attendere: salvataggi gia in corso', now+2
    except KeyboardInterrupt:
        error_text = 'Interrotto dal terminale'
    except Exception as error:
        error_text = str(error)
        print(f'ERRORE: {error_text}', flush=True)
        if latest_bundle is not None and len(pending) < 2:
            pending.append(writer.submit(save_bundle, latest_bundle, session, 'capture_error_last_frame', latest_timing))
    finally:
        if camera is not None:
            camera.close()
        cv2.destroyAllWindows()
        writer.shutdown(wait=True)
        for future in pending:
            try:
                saved.append(future.result())
            except Exception as error:
                save_errors.append(str(error))
        stats = camera.snapshot()[2] if camera else {}
        elapsed = time.perf_counter()-started
        processing_span = last_processed-first_processed if processed > 1 else 0
        final = {**stats, 'processed_frames': processed, 'processed_fps': (processed-1)/processing_span if processing_span else 0,
                 'skipped_frames': skipped, 'elapsed_seconds': elapsed,
                 'mean_pipeline_ms': float(np.mean(pipeline_times)) if pipeline_times else None,
                 'max_pipeline_ms': max(pipeline_times) if pipeline_times else None,
                 'last_scene': latest_bundle['report'] if latest_bundle else None,
                 'saved_paths': saved, 'save_errors': save_errors, 'error': error_text,
                 'physical_recognition_visually_confirmed': False,
                 'latency_note': 'Eta dal ricevimento locale, non latenza sensore-iPhone/Wi-Fi'}
        write_json(session/'session_summary.json', final)
        print('SESSIONE', session, flush=True)
        print(json.dumps({k: v for k, v in final.items() if k != 'last_scene'}, indent=2), flush=True)
    return 1 if error_text else 0


if __name__ == '__main__':
    raise SystemExit(main())
