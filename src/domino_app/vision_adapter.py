"""Adattatore prudente: identita, stabilita misurata e contatti geometrici."""
from dataclasses import dataclass
import time
import cv2
import numpy as np
from domino_engine import Tile,Side,OrientedTile
from domino_engine.events import ObservedTile,ObservedScene


@dataclass(frozen=True)
class VisualTile:
    identity: Tile
    values: tuple
    center: tuple
    polygon: tuple
    faces: tuple
    width: float


def extract(report):
    tiles=[]
    if report['unknown_count']:raise ValueError('Some tiles are uncertain: rescan or correct them manually.')
    if report.get('green_fraction',0)<.35:raise ValueError('Mat not visible or frame is black.')
    for geometry,reading in zip(report['detections'],report['readings']):
        identity=reading.get('identity')
        spatial=reading.get('spatial_order',{})
        if identity is None or len(spatial.get('halves',[]))!=2:raise ValueError('Missing reading or face coordinates.')
        halves=sorted(spatial['halves'],key=lambda h:h['reading_rank'])
        polygon=np.asarray(geometry['vertices'])
        width=float(min(np.linalg.norm(np.roll(polygon,-1,axis=0)-polygon,axis=1)))
        tiles.append(VisualTile(Tile(*identity),tuple(identity),tuple(geometry['center']),
                               tuple(map(tuple,polygon)),tuple(tuple(h['camera_center']) for h in halves),width))
    if len(tiles)!=report['detected_count']:raise ValueError('Inconsistent number of readings.')
    if len({t.identity for t in tiles})!=len(tiles):raise ValueError('Duplicate identities: correct the reading.')
    return tuple(tiles)


def polygon_gap(a,b):
    pa,pb=np.float32(a.polygon),np.float32(b.polygon)
    if cv2.intersectConvexConvex(pa,pb)[0]>0:return 0.
    return min([abs(cv2.pointPolygonTest(pa,tuple(map(float,p)),True)) for p in pb]
               +[abs(cv2.pointPolygonTest(pb,tuple(map(float,p)),True)) for p in pa])


def touching_face(tile,other):
    distances=[float(np.linalg.norm(np.array(p)-other.center)) for p in tile.faces]
    if abs(distances[0]-distances[1])<.12*tile.width and tile.values[0]!=tile.values[1]:
        raise ValueError('The contact between tile faces is geometrically ambiguous.')
    return int(np.argmin(distances))


class VisionAdapter:
    def __init__(self,required_frames=3,minimum_seconds=.7,contact_fraction=.22):
        self.required_frames=required_frames;self.minimum_seconds=minimum_seconds
        self.contact_fraction=contact_fraction;self.reset();self.pose_signature=None;self.pose_hits=0;self.pose_since=None;self.pose_last=None;self.pose_center=None

    def reset(self):
        self.signature=None;self.hits=0;self.since=None;self.last_time=None
        self.pose_signature=None;self.pose_hits=0;self.pose_since=None;self.pose_last=None;self.pose_center=None

    def stable_tiles(self,report,now=None):
        now=time.monotonic() if now is None else now
        try:tiles=extract(report)
        except ValueError:self.reset();raise
        signature=tuple(sorted((t.identity.a,t.identity.b) for t in tiles))
        if signature!=self.signature or self.last_time is not None and now-self.last_time>2.5:
            self.signature=signature;self.hits=1;self.since=now
        else:self.hits+=1
        self.last_time=now
        quality=min(1.,self.hits/self.required_frames)
        if self.hits<self.required_frames or now-self.since<self.minimum_seconds:
            raise ValueError(f'Waiting for stability: {self.hits}/{self.required_frames} consistent readings.')
        return tiles,quality

    def observation(self,report,state,now=None,image_ref=None):
        try:return self._observation(report,state,now,image_ref)
        except ValueError as exc:
            if not str(exc).startswith('New tile read.'):
                self.reset()
            raise

    def _observation(self,report,state,now=None,image_ref=None):
        now=time.monotonic() if now is None else now
        tiles=extract(report);quality=1.
        byid={t.identity:t for t in tiles};baseline={t.tile for t in state.chain}
        if not baseline.issubset(byid):raise ValueError('A tile in the confirmed chain is missing or misread.')
        new=set(byid)-baseline
        if len(new)!=1:raise ValueError('No new placement' if not new else 'Multiple new tiles: confirm one placement at a time.')
        candidate=byid[next(iter(new))]
        # Gli errori di identificazione non vengono corretti con le regole.
        for ambiguity in report.get('chain_geometry',{}).get('ambiguous',[]):
            center=ambiguity['candidate']['center']
            if np.linalg.norm(np.array(center)-candidate.center)<1.5*candidate.width:
                raise ValueError('Uncertain geometric separation near the new tile.')
        def neighbors(tile):
            return [other for other in tiles if other.identity!=tile.identity
                    and polygon_gap(tile,other)<=self.contact_fraction*min(tile.width,other.width)]
        if not state.chain:
            if len(tiles)!=1:raise ValueError('Show only one tile for the opening move.')
            side=Side.RIGHT;orientation=OrientedTile(*candidate.values)
        else:
            # L'ordine storico e logico e gia noto: verificare la sua geometria.
            for left,right in zip(state.chain,state.chain[1:]):
                if polygon_gap(byid[left.tile],byid[right.tile])>self.contact_fraction*min(byid[left.tile].width,byid[right.tile].width):
                    raise ValueError('The confirmed chain moved or its contacts cannot be read: correct manually.')
            contacts=neighbors(candidate)
            if len(contacts)!=1:raise ValueError('New contact is missing or ambiguous: choose the logical end manually.')
            neighbor=contacts[0]
            if len(state.chain)==1:
                face=touching_face(neighbor,candidate);contact=neighbor.values[face]
                if state.ends[0]==state.ends[1]:raise ValueError('Opening double: the logical ends require manual confirmation.')
                side=Side.LEFT if contact==state.ends[0] else Side.RIGHT
            elif neighbor.identity==state.chain[0].tile:side=Side.LEFT
            elif neighbor.identity==state.chain[-1].tile:side=Side.RIGHT
            else:raise ValueError('The new tile touches an internal tile in the chain.')
            free=state.ends[0 if side==Side.LEFT else 1]
            if neighbor.values[touching_face(neighbor,candidate)]!=free:
                raise ValueError('The placement touches an occupied or incompatible face: check the logical end.')
            index=touching_face(candidate,neighbor)
            if candidate.values[index]!=free:
                self.reset()
                raise ValueError(f'Invalid connection: {candidate.values[index]} does not match {free}. Turn the tile around.')
            outer=candidate.values[1-index]
            orientation=OrientedTile(outer,free) if side==Side.LEFT else OrientedTile(free,outer)
        # Stabilizza la posa fisica, non soltanto l'elenco delle identità.
        signature=(candidate.identity,side,orientation)
        moved=self.pose_center is not None and np.linalg.norm(np.array(candidate.center)-self.pose_center)>.2*candidate.width
        if signature!=self.pose_signature or moved or self.pose_last is not None and now-self.pose_last>2.5:
            self.pose_signature=signature;self.pose_hits=1;self.pose_since=now;self.pose_center=np.array(candidate.center)
        else:self.pose_hits+=1
        self.pose_last=now
        if self.required_frames>1 and (self.pose_hits<2 or now-self.pose_since<.25):
            raise ValueError(f'New tile read. Checking placement: {min(self.pose_hits,2)}/2 readings, at least 0.25 s.')
        items=tuple(ObservedTile(t.identity.a,t.identity.b,side if t is candidate else Side.RIGHT,
                                orientation if t is candidate else OrientedTile(*t.values),quality) for t in tiles)
        return ObservedScene(items,False,image_ref)
