"""Ricerca sperimentale geometrica: i valori dei puntini NON guidano la separazione."""
from collections import deque
import json
import time
import cv2
import numpy as np
from real_domino import detect_white_faces
from static_domino import ROOT, iou


def rectangle(center, side, orientation):
    w, h = (2*side, side) if orientation == 'horizontal' else (side, 2*side)
    x, y = center
    return np.float32([[x-w/2, y-h/2], [x+w/2, y-h/2], [x+w/2, y+h/2], [x-w/2, y+h/2]])


def patch_mean(mask, bounds):
    x0, y0, x1, y1 = map(int, bounds)
    if x0 < 0 or y0 < 0 or x1 > mask.shape[1] or y1 > mask.shape[0] or x1 <= x0 or y1 <= y0:
        return 0.0
    return float(np.mean(mask[y0:y1, x0:x1] != 0))


def estimate_sides(mask, isolated, config):
    sides = [min(np.linalg.norm(np.roll(np.array(t['vertices']), -1, axis=0)-t['vertices'], axis=1)) for t in isolated]
    # Spessori delle componenti: corse orizzontali/verticali, non numero di puntini.
    lengths = []
    for rows in [mask[::5], mask.T[::5]]:
        for row in rows:
            changes = np.flatnonzero(np.diff(np.r_[0, row != 0, 0].astype(np.int8)))
            lengths.extend((changes[1::2]-changes[::2]).tolist())
    valid = [x for x in lengths if config['min_side'] <= x <= config['max_side']]
    if valid:
        hist, edges = np.histogram(valid, bins=np.arange(config['min_side'], config['max_side']+5, 4))
        peaks = sorted(range(len(hist)), key=lambda i: hist[i], reverse=True)
        for index in peaks:
            if hist[index] < max(3, hist.max()*.15):
                break
            side = float(np.median([v for v in valid if edges[index] <= v < edges[index+1]]))
            if all(abs(side-s) > .10*s for s in sides):
                sides.append(side)
    # Le prime stime da tessere isolate hanno precedenza.
    unique = []
    for side in sides:
        if config['min_side'] <= side <= config['max_side'] and all(abs(side-s) > .08*s for s in unique):
            unique.append(float(side))
    return unique[:config['max_width_hypotheses']]


def score_candidate(mask, dark, center, side, orientation, config):
    box = rectangle(center, side, orientation)
    x0, y0 = box[0]
    x1, y1 = box[2]
    inset = .08*side
    if orientation == 'horizontal':
        halves = [(x0+inset, y0+inset, center[0]-inset, y1-inset),
                  (center[0]+inset, y0+inset, x1-inset, y1-inset)]
        divider = (center[0]-2, y0+.12*side, center[0]+3, y1-.12*side)
        # I lati lunghi dovrebbero essere bordi della superficie; tollera contatti parziali.
        outside = [(x0+.1*side, y0-.08*side, x1-.1*side, y0),
                   (x0+.1*side, y1, x1-.1*side, y1+.08*side)]
        ends = [(x0-.12*side, y0+.15*side, x0-.02*side, y1-.15*side),
                (x1+.02*side, y0+.15*side, x1+.12*side, y1-.15*side)]
    else:
        halves = [(x0+inset, y0+inset, x1-inset, center[1]-inset),
                  (x0+inset, center[1]+inset, x1-inset, y1-inset)]
        divider = (x0+.12*side, center[1]-2, x1-.12*side, center[1]+3)
        outside = [(x0-.08*side, y0+.1*side, x0, y1-.1*side),
                   (x1, y0+.1*side, x1+.08*side, y1-.1*side)]
        ends = [(x0+.15*side, y0-.12*side, x1-.15*side, y0-.02*side),
                (x0+.15*side, y1+.02*side, x1-.15*side, y1+.12*side)]
    occupancy = min(patch_mean(mask, half) for half in halves)
    # Copertura della linea: almeno un pixel scuro nella banda per riga/colonna.
    a, b, c, d = map(int, divider)
    strip = dark[max(0,b):min(d,dark.shape[0]), max(0,a):min(c,dark.shape[1])]
    coverage = float(np.mean(np.any(strip != 0, axis=0 if orientation == 'vertical' else 1))) if strip.size else 0
    side_support = float(np.mean([1-patch_mean(mask, q) for q in outside]))
    exposed = [1-patch_mean(mask, q) for q in ends]
    score = .45*occupancy+.35*coverage+.20*side_support
    accepted = (occupancy >= config['white_coverage_min'] and coverage >= config['divider_coverage_min']
                and side_support >= config['side_support_min'] and score >= config['score_min']
                and x0 >= 0 and y0 >= 0 and x1 < mask.shape[1] and y1 < mask.shape[0])
    return {'vertices': box.tolist(), 'center': list(map(float, center)), 'side': float(side),
            'orientation': orientation, 'white_coverage': occupancy, 'divider_coverage': coverage,
            'side_support': side_support, 'exposed_ends': exposed, 'score': score, 'accepted': bool(accepted)}


def adjacent(a, b, config):
    aa, bb = np.array(a['vertices']), np.array(b['vertices'])
    amin, amax, bmin, bmax = aa.min(0), aa.max(0), bb.min(0), bb.max(0)
    tolerance = config['contact_tolerance_fraction']*min(a['side'], b['side'])
    overlap = np.minimum(amax, bmax)-np.maximum(amin, bmin)
    gaps = np.maximum(np.maximum(amin-bmax, bmin-amax), 0)
    return bool((gaps[0] <= tolerance and overlap[1] >= .25*min(a['side'], b['side']))
                or (gaps[1] <= tolerance and overlap[0] >= .25*min(a['side'], b['side'])))


def expansion_slots(tile):
    """Rettangoli previsti dai quattro bordi: dritti, svolte e trasversali."""
    vertices = np.array(tile['vertices'])
    low, high = vertices.min(0), vertices.max(0)
    x,y = tile['center']; side=tile['side']
    slots=[]
    for orientation in ['horizontal','vertical']:
        half_w,half_h=(side,side/2) if orientation=='horizontal' else (side/2,side)
        for shift in [-.5,0,.5]:
            for center in [(low[0]-half_w,y+shift*side),(high[0]+half_w,y+shift*side),
                           (x+shift*side,low[1]-half_h),(x+shift*side,high[1]+half_h)]:
                slots.append({'center':list(map(float,center)),'orientation':orientation,
                              'vertices':rectangle(center,side,orientation).tolist()})
    return slots


def divider_segments(dark, sides):
    """Linee spesse: evita la pendenza arbitraria dei frammenti Hough interni."""
    segments=[]
    length=max(15,int(min(sides)*.45)) if sides else 20
    for horizontal in (True,False):
        kernel=np.ones((1,length) if horizontal else (length,1),np.uint8)
        opened=cv2.morphologyEx(dark,cv2.MORPH_OPEN,kernel)
        count,_,stats,centers=cv2.connectedComponentsWithStats(opened,8)
        for index in range(1,count):
            x,y,w,h,area=stats[index]
            span,thickness=(w,h) if horizontal else (h,w)
            if span < length or span < 4*thickness:continue
            cx,cy=centers[index]
            segments.append((cx-span/2,cy,cx+span/2,cy) if horizontal
                            else (cx,cy-span/2,cx,cy+span/2))
    return segments


def refine_from_white_faces(mask, center, side, orientation):
    """Intersezione delle sezioni delle due facce, indipendente dai puntini."""
    trans,long=(1,0) if orientation=='horizontal' else (0,1)
    spans=[]
    for sign in (-1,1):
        position=np.array(center,dtype=float);position[long]+=sign*.45*side
        x,y=np.rint(position).astype(int)
        if not (0<=x<mask.shape[1] and 0<=y<mask.shape[0]):return center,side
        row=mask[:,x] if trans==1 else mask[y,:]
        pivot=int(round(center[trans]))
        if not 0<=pivot<len(row) or row[pivot]==0:return center,side
        zeros_before=np.flatnonzero(row[:pivot]==0)
        zeros_after=np.flatnonzero(row[pivot+1:]==0)
        low=int(zeros_before[-1]+1) if len(zeros_before) else 0
        high=int(pivot+zeros_after[0]) if len(zeros_after) else len(row)-1
        spans.append((low,high))
    low=max(s[0] for s in spans);high=min(s[1] for s in spans)
    width=high-low+1
    refined=list(center);refined[trans]=(low+high)/2
    return refined,float(width)


def detect_chains(image, detection_config, config=None):
    config = config or json.loads((ROOT/'config/chain_vision.json').read_text())
    started = time.perf_counter()
    isolated, candidates, debug = detect_white_faces(image, detection_config)
    mask = debug['03d_white_face_filled']
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = np.uint8(gray < config['dark_threshold'])*255
    dark = cv2.bitwise_and(dark, cv2.erode(mask, np.ones((3,3), np.uint8)))
    sides = estimate_sides(mask, isolated, config)
    component_view = image.copy()
    for label in range(1, count):
        x,y,w,h,area = stats[label]
        if area >= detection_config['min_area']:
            cv2.rectangle(component_view,(x,y),(x+w,y+h),(255,100,0),2)
            cv2.putText(component_view,f'R{label}',(x,y+20),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,100,0),1)
    cv2.putText(component_view,'Lati stimati (px): '+', '.join(f'{s:.1f}' for s in sides),(10,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,200,255),2)
    lines = cv2.HoughLinesP(dark, 1, np.pi/180, threshold=18,
                            minLineLength=max(15, int(min(sides)*.45)) if sides else 20, maxLineGap=4)
    supplemental=divider_segments(dark,sides)
    if supplemental:
        combined=[] if lines is None else lines[:,0].tolist()
        lines=np.array(combined+supplemental,dtype=float).reshape(-1,1,4)
    pool = []; evaluated=set()
    if lines is not None:
        for x0,y0,x1,y1 in lines[:,0]:
            angle = abs(float(np.degrees(np.arctan2(y1-y0,x1-x0)))) % 180
            orientation = 'vertical' if min(angle,180-angle) <= config['axis_tolerance_deg'] else ('horizontal' if abs(angle-90) <= config['axis_tolerance_deg'] else None)
            if orientation is None:
                continue
            length = float(np.hypot(x1-x0,y1-y0))
            for side in sides:
                if not config['divider_segment_min_fraction']*side <= length <= 1.10*side:
                    continue
                # Hough puo vedere solo parte della divisoria: cerca la centratura
                # trasversale con superficie e bordi, mai con i valori dei punti.
                for offset in np.linspace(-.25*side,.25*side,7):
                    center=((x0+x1)/2+offset,(y0+y1)/2) if orientation=='vertical' else ((x0+x1)/2,(y0+y1)/2+offset)
                    refined,measured=refine_from_white_faces(mask,center,side,orientation)
                    if measured>1.20*side and sides and side<.85*sides[0]:continue
                    if .85*side<=measured<=1.15*side:
                        center,side_for_box=refined,measured
                    else:side_for_box=side
                    key=(*center,side_for_box,orientation)
                    if key in evaluated:continue
                    evaluated.add(key)
                    item = score_candidate(mask,dark,center,side_for_box,orientation,config)
                    if item['accepted']:
                        pool.append(item)
                # Per linee morfologiche, la sezione reale delle facce fornisce
                # una larghezza piu precisa della stima globale della scena.
                if (x0,y0,x1,y1) in supplemental:
                    center=((x0+x1)/2,(y0+y1)/2)
                    center,measured=refine_from_white_faces(mask,center,side,orientation)
                    if not .85*side<=measured<=1.15*side:continue
                    key=(*center,measured,orientation)
                    if key in evaluated:continue
                    evaluated.add(key)
                    item=score_candidate(mask,dark,center,measured,orientation,config)
                    if item['accepted']:
                        item['divider_evidence']='elongated_dark_component'
                        pool.append(item)
    # Doppie linee dello stesso separatore non sono ipotesi distinte di tessere.
    clustered = []
    for item in sorted(pool,key=lambda q:q['score'],reverse=True):
        if not any(item['orientation']==p['orientation'] and np.linalg.norm(np.array(item['center'])-p['center']) < .18*min(item['side'],p['side']) for p in clustered):
            clustered.append(item)
    pool = clustered[:config['max_hypotheses']]
    accepted = []
    for item in isolated:
        box=np.array(item['vertices']); edges=np.roll(box,-1,axis=0)-box
        edge=edges[np.argmax(np.linalg.norm(edges,axis=1))]
        accepted.append({**item,'side':float(min(np.linalg.norm(edges,axis=1))),
                         'orientation':'horizontal' if abs(edge[0])>=abs(edge[1]) else 'vertical',
                         'source':'normal','score':1.,'parent':None})
    # Anche dentro una catena: divisoria continua, due facce bianche e
    # lati lunghi esposti costituiscono un'ancora geometrica indipendente.
    # Non richiedere un'estremita corta libera quando entrambe toccano vicini.
    anchors = [p for p in pool if max(p['exposed_ends']) >= .65 or (
        p['divider_coverage'] >= .90 and p['white_coverage'] >= .98
        and p['side_support'] >= .85)]
    ambiguous, proposals = [], []
    # Confronto geometrico di insiemi non sovrapposti: una falsa divisione al
    # giunto non deve bloccare il vero rettangolo vicino a una svolta.
    usable=[p for p in pool if not any(
        cv2.pointPolygonTest(np.float32(q['vertices']),tuple(p['center']),False)>=0
        or iou(p['vertices'],q['vertices'])>config['overlap_iou_max'] for q in accepted)]
    beam=[([],0.)]
    for index,p in enumerate(usable):
        next_beam=list(beam)
        for indices,score in beam:
            if all(iou(p['vertices'],usable[j]['vertices'])<=config['overlap_iou_max'] for j in indices):
                next_beam.append((indices+[index],score+2*p['side']**2*p['score']))
        beam=sorted(next_beam,key=lambda item:item[1],reverse=True)[:128]
    best=beam[0] if beam else ([],0.)
    alternatives=[plan for plan in beam[1:] if best[1] and best[1]-plan[1] <= config['ambiguity_score_gap']*best[1]]
    definite=set(best[0])
    for indices,score in alternatives:
        definite &= set(indices)
    uncertain=set(best[0])-definite
    for index in uncertain:
        ambiguous.append({'candidate':usable[index], 'alternatives':[usable[j] for indices,_ in alternatives for j in indices if j not in definite],
                          'reason':'competing_nonoverlapping_plans'})
    selected=[usable[i] for i in sorted(definite)]
    # Una sola radice per ciascun gruppo di candidate adiacenti: le altre
    # mantengono il legame padre/figlio dell'espansione progressiva.
    seeds = [p for p in selected if any(p is q for q in anchors)
             or any(adjacent(p,q,config) for q in accepted)]
    roots=[]; reachable=set()
    for seed in seeds:
        if id(seed) in reachable:continue
        roots.append(seed); pending=[seed]
        while pending:
            node=pending.pop()
            if id(node) in reachable:continue
            reachable.add(id(node))
            pending.extend(q for q in selected if id(q) not in reachable
                           and adjacent(node,q,config)
                           and any(slot['orientation']==q['orientation'] and
                               np.linalg.norm(np.array(slot['center'])-q['center']) <= .35*node['side']
                               for slot in expansion_slots(node)))
    frontier = deque((p,None) for p in roots)
    explored = set()
    while frontier:
        item,parent = frontier.popleft()
        key=(round(item['center'][0],1),round(item['center'][1],1),item['orientation'])
        if key in explored:
            continue
        explored.add(key)
        if any(iou(item['vertices'], other['vertices']) > config['overlap_iou_max'] for other in accepted):
            continue
        node={**item,'source':'expansion','parent':parent,'anchor':parent is None}
        accepted.append(node)
        index=len(accepted)-1
        slots=expansion_slots(node)
        # Le regioni composte possono contenere piu tessere: la risorsa consumata
        # e l'area fisica della tessera, non l'intera componente connessa.
        for q in selected:
            nearby=[slot for slot in slots if slot['orientation']==q['orientation']
                    and np.linalg.norm(np.array(slot['center'])-q['center']) <= .35*node['side']]
            if nearby and adjacent(node,q,config) and iou(node['vertices'],q['vertices']) <= config['overlap_iou_max']:
                proposals.append({'from':index,'predicted_rectangle':nearby[0],
                                  'center':q['center'],'orientation':q['orientation'],'score':q['score']})
                frontier.append((q,index))
    for item in accepted:
        x,y=np.rint(item['center']).astype(int)
        item['component_id']=int(labels[np.clip(y,0,labels.shape[0]-1),np.clip(x,0,labels.shape[1]-1)])
    final=image.copy(); anchor_view=image.copy(); hypothesis_view=image.copy(); faces=image.copy()
    for q in pool:cv2.polylines(hypothesis_view,[np.int32(q['vertices'])],True,(170,100,170),1)
    for i,q in enumerate(accepted):
        box=np.int32(np.rint(q['vertices'])); color=(0,0,255) if q['source']=='normal' else (255,200,0)
        cv2.polylines(final,[box],True,color,2)
        if q.get('anchor'):cv2.polylines(anchor_view,[box],True,(0,255,255),3)
        cv2.polylines(faces,[box],True,color,1)
        center=np.array(q['center'])
        short_axis=np.array([0,q['side']/2] if q['orientation']=='horizontal' else [q['side']/2,0])
        cv2.line(faces,tuple(np.int32(center-short_axis)),tuple(np.int32(center+short_axis)),color,2)
        for sign in [-1,1]:
            position=center+np.array([sign*q['side']/2,0] if q['orientation']=='horizontal' else [0,sign*q['side']/2])
            cv2.circle(faces,tuple(np.int32(position)),4,color,-1)
        if q.get('parent') is not None:
            cv2.arrowedLine(anchor_view,tuple(np.int32(accepted[q['parent']]['center'])),tuple(np.int32(center)),(0,220,255),2)
    for a in ambiguous:cv2.polylines(final,[np.int32(a['candidate']['vertices'])],True,(0,160,255),2)
    unresolved=[]
    for label in range(1,count):
        if stats[label,cv2.CC_STAT_AREA] < detection_config['min_area']:continue
        region=np.uint8(labels==label)*255
        used=np.zeros_like(mask)
        for q in accepted:cv2.fillConvexPoly(used,np.int32(np.rint(q['vertices'])),255)
        remaining=np.count_nonzero((region!=0)&(used==0))
        if remaining > max(500,stats[label,cv2.CC_STAT_AREA]*.20):
            unresolved.append({'component_id':label,'uncovered_pixels':int(remaining),'reason':'insufficient_geometric_evidence'})
            x,y,w,h,_=stats[label]
            cv2.rectangle(final,(x,y),(x+w,y+h),(0,150,255),2)
    ownership=np.zeros_like(labels)
    for index,q in enumerate(accepted,1):
        tile_mask=np.zeros_like(mask);cv2.fillConvexPoly(tile_mask,np.int32(np.rint(q['vertices'])),255)
        free=(tile_mask!=0)&(mask!=0)&(ownership==0)
        ownership[free]=index
        q['owned_white_pixels']=int(np.count_nonzero(free))
    debug.update({'07_chain_components':component_view,'08_chain_anchors_expansion':anchor_view,
                  '09_chain_face_candidates':faces,'10_chain_hypotheses':hypothesis_view,'11_chain_final':final,
                  '12_chain_dark_lines':dark,'13_chain_unique_ownership':np.uint8((ownership*37)%256)})
    report={'estimated_sides':sides,'hypotheses':pool,'expansion_proposals':proposals,
            'plan_comparison':{'beam_limit':128,'best_score':best[1],'near_best_plans':len(alternatives)},
            'ambiguous':ambiguous,'unresolved_components':unresolved,'components':count-1,
            'geometry_ms':1000*(time.perf_counter()-started)}
    return accepted,report,debug
