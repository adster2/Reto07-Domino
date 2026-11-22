"""Anteprima Camo con selezione per nome DirectShow, FPS e snapshot."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time
import cv2

ROOT = Path(__file__).resolve().parents[1]


def list_cameras():
    script = (ROOT / 'src' / 'list_cameras.ps1').read_text(encoding='utf-8-sig')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, check=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json.loads(result.stdout.strip())


def save_frame(frame):
    folder = ROOT / 'data' / 'raw'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'camo_{datetime.now():%Y%m%d_%H%M%S_%f}.png'
    if not cv2.imwrite(str(path), frame):
        raise OSError(f'Salvataggio fallito: {path}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='Camo', help='Nome esatto della sorgente DirectShow')
    parser.add_argument('--list', action='store_true', help='Elenca le sorgenti senza aprirle')
    parser.add_argument('--check', action='store_true', help='Test acquisizione senza anteprima')
    parser.add_argument('--seconds', type=float, default=8, help='Durata test senza anteprima')
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds deve essere positivo')
    names = list_cameras()
    for index, name in enumerate(names):
        print(f'[{index}] {name}', flush=True)
    if args.list:
        return 0
    matches = [i for i, name in enumerate(names) if name.casefold() == args.name.casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'Sorgente {args.name!r} assente o ambigua. Aprire Camo Studio e controllare --list.')
    index = matches[0]
    print(f'Selezionata: {names[index]} (DirectShow, indice {index})', flush=True)
    camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    title = f'Reto 07 - {names[index]} | S: salva | Q: esci'
    frames = 0
    fps = 0.0
    started = time.perf_counter()
    window_start = started
    window_frames = 0
    first_frame = None
    last_shape = None
    saved_message = ''
    message_until = 0
    try:
        if not camera.isOpened():
            raise RuntimeError('Camo trovata ma non apribile. Controllare Camo Studio e altre app video.')
        if not args.check:
            cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        while True:
            ok, frame = camera.read()
            now = time.perf_counter()
            if not ok or frame is None or not frame.size:
                if frames == 0 and now - started < 10:
                    time.sleep(0.1)
                    continue
                raise RuntimeError('Camo non invia fotogrammi. Controllare il collegamento Wi-Fi e Camo Studio.')
            if first_frame is None:
                first_frame = now
            frames += 1
            window_frames += 1
            height, width = frame.shape[:2]
            last_shape = [width, height]
            if now - window_start >= 1:
                fps = window_frames / (now - window_start)
                window_start, window_frames = now, 0
            if args.check:
                if now - started >= args.seconds:
                    encoded, _ = cv2.imencode('.png', frame)
                    if not encoded:
                        raise RuntimeError('Codifica PNG fallita')
                    break
                continue
            display = frame.copy()
            label = f'{names[index]} | {width}x{height} | FPS ricevuti: {fps:.1f}'
            cv2.rectangle(display, (0, 0), (width, 70), (0, 0, 0), -1)
            cv2.putText(display, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)
            help_text = saved_message if now < message_until else 'S: salva fotogramma | Q / ESC: esci'
            cv2.putText(display, help_text, (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(title, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27):
                break
            if key in (ord('s'), ord('S')):
                try:
                    path = save_frame(frame)
                    print(f'Salvato: {path}', flush=True)
                    saved_message = f'Salvato: {path.name}'
                except (OSError, cv2.error) as error:
                    print(f'Errore salvataggio: {error}', flush=True)
                    saved_message = 'Salvataggio fallito: vedere terminale'
                message_until = now + 3
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()
    elapsed = time.perf_counter() - started
    measured_fps = (frames - 1) / (time.perf_counter() - first_frame) if frames > 1 else 0
    report = {'source': names[index], 'index': index, 'backend': 'DirectShow',
              'resolution': last_shape, 'frames': frames, 'elapsed_seconds': round(elapsed, 2),
              'received_fps': round(measured_fps, 2), 'mode': 'check' if args.check else 'preview',
              'timestamp': datetime.now().isoformat(timespec='seconds')}
    print(json.dumps(report, indent=2), flush=True)
    if args.check:
        (ROOT / 'outputs').mkdir(exist_ok=True)
        (ROOT / 'outputs' / 'camera_check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Acquisizione interrotta.')
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, cv2.error) as error:
        print(f'ERRORE: {error}', flush=True)
        raise SystemExit(1)
