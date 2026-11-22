"""Acquisizione e ricerca fuori dal thread Tk; risultati con token anti-obsolescenza."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue,Empty,Full
import threading
import time
from domino_engine.strategy import StrategyEngine,SearchConfig
from domino_engine import Player
from live_domino import LatestCamera,analyze_frame,select_camera
from webcam import list_cameras
from . import ROOT
import json


class AdviceWorker:
    def __init__(self):
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='domino-strategy')
        self.generation=0;self.future=None;self.token=None

    def invalidate(self):
        self.generation+=1
        if self.future:self.future.cancel()
        self.future=None;self.token=None

    def request(self,session,level):
        if not session or session.state.phase!='active' or session.state.turn!=Player.ASSISTED or not session.aligned:
            self.invalidate();return
        token=(session.session_id,session.revision,level,self.generation)
        if token==self.token:return
        if self.future:self.future.cancel()
        self.token=token
        view=session.state.knowledge()
        self.future=self.executor.submit(StrategyEngine(SearchConfig(level=level)).rank,view)

    def poll(self,session,level):
        if not self.future or not self.future.done():return None
        future=self.future;self.future=None
        expected=(session.session_id,session.revision,level,self.generation) if session else None
        if expected!=self.token:return None
        return future.result()

    def close(self):self.invalidate();self.executor.shutdown(wait=False,cancel_futures=True)


class VisionWorker:
    def __init__(self):
        self.queue=Queue(maxsize=1);self.stop_event=threading.Event();self.thread=None;self.camera=None

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear();self.thread=threading.Thread(target=self._run,daemon=True,name='domino-vision');self.thread.start()

    def put(self,item):
        try:self.queue.put_nowait(item)
        except Full:
            try:self.queue.get_nowait()
            except Empty:pass
            try:self.queue.put_nowait(item)
            except Full:pass

    def _run(self):
        try:
            index=select_camera(list_cameras());self.camera=LatestCamera(index).start()
            d=json.loads((ROOT/'config/detection_live.json').read_text());r=json.loads((ROOT/'config/recognition_live.json').read_text())
            last=0;started=time.monotonic();processed=0
            while not self.stop_event.is_set():
                packet,error,stats=self.camera.snapshot()
                if error:raise RuntimeError(error)
                if packet is None:
                    if time.monotonic()-started>10:raise RuntimeError('Camo did not provide video within 10 seconds.')
                    self.stop_event.wait(.03);continue
                seq,received,read_seconds,frame=packet
                if time.perf_counter()-received>10:raise RuntimeError('Camo video stream is frozen.')
                if seq==last:self.stop_event.wait(.02);continue
                last=seq;bundle=analyze_frame(frame,d,r,experimental_chains=True);processed+=1
                bundle['timing']={'camera_fps':stats['acquired_fps'],'processing_fps':processed/max(.001,time.monotonic()-started),
                                  'read_ms':1000*read_seconds,'age_ms':1000*(time.perf_counter()-received)}
                self.put(('frame',bundle))
        except Exception as exc:self.put(('error',str(exc)))
        finally:
            if self.camera:self.camera.close()

    def poll(self):
        try:return self.queue.get_nowait()
        except Empty:return None

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=1.5)
