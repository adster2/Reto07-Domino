"""Memoria geometrica limitata alle tessere confermate dall'operatore.
Non inventa nuove identità e non riempie rilevamenti assenti.
"""
from copy import deepcopy
import time
import cv2
import numpy as np
from domino_engine import Tile
from spatial_order import order_halves


class ConfirmedMemory:
    def __init__(self,max_uncertain_seconds=4.0,min_iou=.72,max_shift=.25):
        self.max_uncertain_seconds=max_uncertain_seconds;self.min_iou=min_iou;self.max_shift=max_shift
        self.clear()

    def clear(self):self.entries={};self.held=[]

    @staticmethod
    def geometry_match(old,new):
        a=np.float32(old['vertices']);b=np.float32(new['vertices'])
        area_a=abs(cv2.contourArea(a));area_b=abs(cv2.contourArea(b))
        overlap=cv2.intersectConvexConvex(a,b)[0]
        iou=overlap/max(1.,area_a+area_b-overlap)
        width=min(np.linalg.norm(np.roll(a,-1,axis=0)-a,axis=1))
        shift=np.linalg.norm(np.array(old['center'])-new['center'])/max(width,1.)
        return iou,shift

    def accept(self,report,state,now=None):
        """Chiamato dopo conferma/riallineamento; salva soltanto identità già nel gioco."""
        now=time.monotonic() if now is None else now
        baseline={tile.tile for tile in state.chain}
        self.entries={key:value for key,value in self.entries.items() if key in baseline}
        for g,r in zip(report['detections'],report['readings']):
            if r.get('identity') is None or r.get('temporal_reused'):continue
            identity=Tile(*r['identity'])
            if identity in baseline:self.entries[identity]=(deepcopy(g),deepcopy(r),now)

    def reconcile(self,report,state,now=None):
        now=time.monotonic() if now is None else now
        result=deepcopy(report);self.held=[]
        if report.get('green_fraction',0)<.35:self.clear();return result
        baseline={tile.tile for tile in state.chain}
        self.entries={key:value for key,value in self.entries.items() if key in baseline}
        readings=result['readings'];geometries=result['detections']
        visible={Tile(*r['identity']) for r in readings if r.get('identity') is not None}
        matches={}
        for identity,(old,reading,last_read) in self.entries.items():
            candidates=[]
            for index,new in enumerate(geometries):
                iou,shift=self.geometry_match(old,new)
                if iou>=self.min_iou and shift<=self.max_shift:candidates.append(index)
            if len(candidates)==1:matches[identity]=candidates[0]
        # Una scomparsa rompe l'associazione: non recuperare un'identità rimessa altrove.
        for identity in set(self.entries)-set(matches):del self.entries[identity]
        for identity,index in matches.items():
            if list(matches.values()).count(index)!=1:continue
            old,reading,last_read=self.entries[identity];current=readings[index]
            if current.get('identity') is not None:
                if Tile(*current['identity'])==identity:
                    self.entries[identity]=(deepcopy(geometries[index]),deepcopy(current),now)
                else:
                    # Una lettura contraddittoria non si nasconde con la memoria.
                    del self.entries[identity]
                continue
            if identity in visible or now-last_read>self.max_uncertain_seconds:continue
            a=np.float32(old['vertices']);b=np.float32(geometries[index]['vertices'])
            variants=[np.roll(points,k,axis=0) for points in (b,b[::-1]) for k in range(4)]
            aligned=min(variants,key=lambda points:float(np.sum((points-a)**2)))
            transform=cv2.getPerspectiveTransform(a,aligned)
            reused=deepcopy(reading)
            for half in reused.get('spatial_order',{}).get('halves',[]):
                half['camera_center']=cv2.perspectiveTransform(np.float32([[half['camera_center']]]),transform)[0,0].tolist()
            if all(key in reading for key in ('transform','divider_x','half_values')):
                half_one=next(h for h in reading['spatial_order']['halves'] if h['normalized_index']==1)
                width=round(2*half_one['normalized_center'][0]-reading['divider_x']+1)
                height=round(2*half_one['normalized_center'][1]+1)
                new_transform=np.asarray(reading['transform'])@np.linalg.inv(transform)
                reused['transform']=new_transform.tolist()
                reused['spatial_order']=order_halves(reading['half_values'],new_transform,width,height,reading['divider_x'])
                reused['identity']=reused['spatial_order']['values']
            # Anche una sola metà leggibile in contraddizione invalida il recupero.
            contradiction=False
            for half in current.get('spatial_order',{}).get('halves',[]):
                if half.get('value') is None:continue
                old_half=min(reused['spatial_order']['halves'],key=lambda h:np.linalg.norm(np.array(h['camera_center'])-half['camera_center']))
                if old_half.get('value') is not None and old_half['value']!=half['value']:contradiction=True
            if contradiction:
                del self.entries[identity];continue
            reused['temporal_reused']=True;reused['raw_identity']=None;reused['raw_reasons']=current.get('reasons',[])
            reused['memory_age_seconds']=round(now-last_read,3)
            readings[index]=reused;self.held.append({'index':index,'identity':list(reused['identity']),'age':now-last_read})
        result['unknown_count']=sum(r.get('identity') is None for r in readings)
        result['recognized_count']=len(readings)-result['unknown_count']
        result['temporal_memory']={'held':deepcopy(self.held),'raw_unknown_count':report['unknown_count']}
        return result
