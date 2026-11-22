"""Visualizzazione live del tavolo fisico, con coordinate della fotocamera."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np

from live_domino import LatestCamera, analyze_frame, select_camera
from static_domino import ROOT
from visualizer_scene import SceneMemory, check_chain, scene_changed, scene_preview, short_side
from webcam import list_cameras


PIPS = (
    (), ((0, 0),), ((-1, -1), (1, 1)),
    ((-1, -1), (0, 0), (1, 1)),
    ((-1, -1), (1, -1), (-1, 1), (1, 1)),
    ((-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)),
    ((-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)),
)


def viewport(canvas, shape):
    height, width = shape[:2]
    scale = min(max(1, canvas.winfo_width())/width, max(1, canvas.winfo_height())/height)
    offset = np.array([(canvas.winfo_width()-scale*width)/2,
                       (canvas.winfo_height()-scale*height)/2])
    return scale, offset


def table_viewport(canvas, tiles):
    points = np.vstack([tile.polygon for tile in tiles])
    low, high = points.min(axis=0), points.max(axis=0)
    room = np.maximum(1, np.array([canvas.winfo_width(), canvas.winfo_height()])-48)
    typical_side = np.median([short_side(tile.polygon) for tile in tiles])
    scale = min(*(room/np.maximum(high-low, 1)), 110/typical_side)
    offset = np.array([canvas.winfo_width(), canvas.winfo_height()])/2-scale*(low+high)/2
    return scale, offset


def draw_pips(canvas, face, value):
    center = face.mean(axis=0)
    horizontal = (face[1]-face[0]+face[2]-face[3])/2
    vertical = (face[3]-face[0]+face[2]-face[1])/2
    size = min(np.linalg.norm(horizontal), np.linalg.norm(vertical))
    if value is None:
        canvas.create_text(*center, text='?', fill='#694c13',
                           font=('Segoe UI', max(8, round(size*.42)), 'bold'))
        return
    radius = max(1, size*.094)
    for x, y in PIPS[value]:
        px, py = center + .28*(x*horizontal+y*vertical)
        canvas.create_oval(px-radius, py-radius, px+radius, py+radius,
                           fill='#101a1d', outline='')


YELLOW = '#ffcf55'
RED = '#ff666a'


def draw_tile(canvas, tile, scale, offset, uncertain, wrong):
    faces = tuple(face*scale+offset for face in tile.faces)
    polygon = tile.polygon*scale+offset
    color = RED if wrong else YELLOW if uncertain else '#687576'
    canvas.create_polygon(*(polygon+np.array([2, 4])).ravel(), fill='#141f24')
    canvas.create_polygon(*polygon.ravel(), fill='#f3f4ef', outline=color,
                          width=3 if wrong or uncertain else 1, joinstyle='miter')
    seam = [p for p in faces[0] if np.any(np.all(np.isclose(faces[1], p), axis=1))]
    center = (seam[0]+seam[1])/2
    a, b = (center+.88*(p-center) for p in seam)
    canvas.create_line(*a, *b, fill='#596668', width=2)
    for face, value in zip(faces, tile.values):
        draw_pips(canvas, face, value)
    if tile.from_memory or (wrong and uncertain):
        corner = min(polygon, key=lambda p: (p[1], p[0]))
        canvas.create_text(corner[0]+2, corner[1]-3,
                           text='MEM' if tile.from_memory else '?',
                           anchor='sw', fill=YELLOW, font=('Segoe UI', 8, 'bold'))


class Visualizer:
    def __init__(self, root):
        self.root = root
        self.camera = None
        self.bundle = None
        self.tiles = []
        self.chain = set(), []
        self.last_analysis = self.last_video = 0
        self.reset_at = 0
        self.reference = self.reference_shape = None
        self.photo = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.detection, self.recognition = (
            json.loads((ROOT/'config'/name).read_text(encoding='utf-8-sig'))
            for name in ('detection_live.json', 'recognition_live.json')
        )
        self.memory = SceneMemory(self.recognition['divider_min_coverage'])
        self.future = self.executor.submit(lambda: select_camera(list_cameras()))
        self.pending_at = 0

        root.title('Domino | Visualizzatore del tavolo')
        root.geometry('1320x740')
        root.minsize(700, 380)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=4, uniform='panels')
        root.grid_columnconfigure(1, weight=6, uniform='panels')
        self.video = self.panel(0, 'Camo · Video live', '#111918')
        self.table = self.panel(1, 'Tavolo digitale', '#27353b')
        self.table.bind('<Configure>', lambda _: self.draw_scene())

        footer = ttk.Frame(root, padding=(12, 6, 12, 12))
        footer.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.status = tk.StringVar(value='Ricerca della sorgente Camo…')
        ttk.Button(footer, text='Azzera scena', command=self.reset).pack(side='right')
        ttk.Label(footer, textvariable=self.status, wraplength=610).pack(side='left')
        root.after(20, self.poll)

    def panel(self, column, label, color):
        panel = ttk.Frame(self.root, padding=10)
        panel.grid(row=0, column=column, sticky='nsew')
        ttk.Label(panel, text=label, font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=(0, 8))
        canvas = tk.Canvas(panel, width=1, height=1, background=color, highlightthickness=0)
        canvas.pack(fill='both', expand=True)
        return canvas

    def draw_video(self, frame):
        scale, _ = viewport(self.video, frame.shape)
        height, width = frame.shape[:2]
        resized = cv2.resize(frame, (max(1, round(width*scale)), max(1, round(height*scale))))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        header = f'P6\n{rgb.shape[1]} {rgb.shape[0]}\n255\n'.encode('ascii')
        self.photo = tk.PhotoImage(data=header+rgb.tobytes(), format='PPM')
        self.video.delete('all')
        self.video.create_image(self.video.winfo_width()/2, self.video.winfo_height()/2, image=self.photo)

    def draw_scene(self):
        self.table.delete('all')
        if self.bundle is None:
            return
        ambiguous, wrong_contacts = self.chain
        wrong_tiles = {k for i, j, _ in wrong_contacts for k in (i, j)}
        if self.tiles:
            scale, offset = table_viewport(self.table, self.tiles)
            for i, tile in enumerate(self.tiles):
                draw_tile(self.table, tile, scale, offset,
                          tile.uncertain or i in ambiguous, i in wrong_tiles)
            for _, _, points in wrong_contacts:
                a, b = (point*scale+offset for point in points)
                x, y = (a+b)/2
                self.table.create_line(*a, *b, fill=RED, width=4)
                self.table.create_oval(x-5, y-5, x+5, y+5, fill=RED, outline='#79262d')
        report = self.bundle['report']
        weak = sum(tile.uncertain or i in ambiguous for i, tile in enumerate(self.tiles))
        kept = sum(tile.from_memory for tile in self.tiles)
        parts = [f"Ultima analisi: {report['recognized_count']}/{report['detected_count']} lette",
                 f'Vista stabilizzata: {len(self.tiles)} tessere']
        if kept:
            parts.append(f'{kept} da memoria (MEM)')
        if weak:
            parts.append(f'{weak} incerte (giallo)')
        if wrong_contacts:
            parts.append(f'{len(wrong_contacts)} giunzioni incoerenti (rosso)')
        if report.get('warnings'):
            parts.append('Geometria incerta')
        if report['green_fraction'] < .35:
            parts.append('Tappeto poco visibile')
        self.status.set(' · '.join(parts))

    def reset(self):
        self.reset_at = time.perf_counter()
        self.memory.clear()
        self.bundle = None
        self.tiles = []
        self.reference = self.reference_shape = None
        self.draw_scene()
        self.status.set('Scena azzerata. Il rilevamento continua.')

    def poll(self):
        now = time.perf_counter()
        try:
            if self.future is not None and self.future.done():
                future, self.future = self.future, None
                result = future.result()
                if self.camera is None:
                    self.camera = LatestCamera(result).start()
                    self.camera_started = now
                    self.status.set('In attesa del video Camo…')
                elif self.pending_at > self.reset_at:
                    if self.bundle is not None and self.bundle['original'].shape != result['original'].shape:
                        self.memory.clear()
                    self.tiles = self.memory.update(result)
                    self.chain = check_chain(self.tiles)
                    self.bundle = result
                    self.draw_scene()
            if self.camera is not None:
                packet, error, _ = self.camera.snapshot()
                if error:
                    raise RuntimeError(error)
                if packet is None:
                    if now-self.camera_started > 10:
                        raise RuntimeError('Nessun fotogramma da Camo entro 10 secondi.')
                else:
                    seq, received, _, frame = packet
                    if now-received > 2:
                        raise RuntimeError('Il flusso video Camo si è interrotto.')
                    if seq != self.last_video:
                        self.last_video = seq
                        self.draw_video(frame)
                    if self.future is None and seq != self.last_analysis and received > self.reset_at:
                        self.last_analysis = seq
                        preview = scene_preview(frame)
                        if (frame.shape != self.reference_shape or scene_changed(self.reference, preview)
                                or received-self.pending_at >= 2):
                            self.reference, self.reference_shape = preview, frame.shape
                            self.pending_at = received
                            self.future = self.executor.submit(analyze_frame, frame, self.detection,
                                                               self.recognition, True, preprocess=True)
        except Exception as error:
            self.reset()
            self.video.delete('all')
            self.status.set(str(error))
            self.stop()
            return
        self.root.after(25, self.poll)

    def stop(self):
        if self.camera is not None:
            self.camera.close()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def close(self):
        self.stop()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    Visualizer(root)
    root.mainloop()
