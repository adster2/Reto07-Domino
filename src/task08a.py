"""Esperimenti statici catene: generazione, inferenza e valutazione separata."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from static_domino import ROOT,tile_sprite,vertices,write_image,write_json,match_detections
from real_domino import detect_white_faces
from recognize_domino import recognize, normalize, retry_with_preprocessing
from domino_chain_vision import detect_chains


LAYOUTS={
 'A_two':[(2,2,0),(4,2,0)],
 'B_three':[(2,2,0),(4,2,0),(6,2,0)],
 'C_six':[(2+2*i,2,0) for i in range(6)],
 'C_vertical':[(2,2+2*i,90) for i in range(4)],
 'D_turn':[(2,2,0),(4,2,0),(5.5,2.5,90),(5.5,4.5,90)],
 'E_two_turns':[(2,2,0),(4,2,0),(5.5,2.5,90),(5.5,4.5,90),(7,5,0),(9,5,0)],
 'F_transverse_double':[(2,3,0),(4,3,0),(5.5,3,90),(7,3,0),(9,3,0)],
 'G_separate':[(2,2,0),(6,2,90),(2,6,30),(6,6,-35)]}


def generate(split,seed):
    folder=ROOT/'data/task08a'/split
    rng=np.random.default_rng(seed)
    for case,layout in LAYOUTS.items():
        side=float(rng.integers(44,58))
        image=np.full((720,1280,3),(47,116,48),np.uint8)
        image=np.clip(image.astype(float)+rng.normal(0,1.2,image.shape),0,255).astype(np.uint8)
        tiles=[]
        combinations=[(a,b) for a in range(7) for b in range(a,7)]
        chosen=rng.choice(len(combinations),len(layout),replace=False)
        for i,(x,y,angle) in enumerate(layout):
            center=np.float32([80+x*side,45+y*side]);polygon=vertices(center,2*side,angle)
            a,b=combinations[chosen[i]]
            if case=='F_transverse_double' and i==2:a=b=6
            sprite=tile_sprite(a,b)
            matrix=cv2.getAffineTransform(np.float32([[0,0],[256,0],[0,128]]),polygon[[0,1,3]])
            warped=cv2.warpAffine(sprite,matrix,(1280,720))
            alpha=warped[:,:,3:4]/255
            image=np.clip(image*(1-alpha)+warped[:,:,:3]*alpha,0,255).astype(np.uint8)
            tiles.append({'id':i+1,'values':[int(a),int(b)],'center':center.tolist(),'vertices':polygon.tolist()})
        if split!='development':
            image=np.clip(image.astype(float)*rng.uniform(.88,1.02),0,255).astype(np.uint8)
            image=cv2.GaussianBlur(image,(3,3),.4)
        write_image(folder/f'{case}.png',image)
        write_json(folder/f'{case}.json',{'image':f'{case}.png','split':split,'seed':seed,'tiles':tiles,'side':side})


def border_crop_failure(report):
    """Riprova solo componenti tagliate dal bordo, mai conteggi fuori dominio."""
    if report['reasons']!=['invalid_half']:return False
    rejected=[c for half in report['halves'] for c in half['components']
              if c['rejected_by'] not in (None,'tiny_noise','ignored_border_band')]
    return bool(rejected) and all(c['rejected_by']=='border_or_occlusion' for c in rejected)


def analyze(image,detection_config,recognition_config,chain_config=None,*,preprocess=False):
    started=time.perf_counter()
    chain_config=chain_config or json.loads((ROOT/'config/chain_vision.json').read_text())
    found,geometry,debug=detect_chains(image,detection_config,chain_config)
    annotated=debug['11_chain_final'].copy()
    sampling_image=image.copy()
    sampling_image[debug['03d_white_face_filled']==0]=(255,255,255)
    readings=[];tiles=[]
    for i,item in enumerate(found,1):
        polygon=np.asarray(item['vertices'],dtype=np.float32)
        crop_config=dict(recognition_config)
        if item.get('source')=='expansion':
            crop_config['margin']=chain_config.get('rectified_margin',recognition_config['margin'])
        source=image
        restore=None
        if item.get('source')=='expansion':
            source=sampling_image
            x,y=item['center'];side=item['side']
            # La divisoria puo interrompere la maschera bianca: conservarne
            # sempre la banda centrale. I buchi dei puntini sono gia riempiti
            # nella maschera geometrica, quindi i puntini originali restano.
            low=np.floor(polygon.min(0)-2).astype(int);high=np.ceil(polygon.max(0)+3).astype(int)
            if item['orientation']=='horizontal':low[0],high[0]=int(x-.12*side),int(x+.12*side)+1
            else:low[1],high[1]=int(y-.12*side),int(y+.12*side)+1
            x0,y0=np.maximum(low,0);x1,y1=np.minimum(high,[image.shape[1],image.shape[0]])
            restore=(x0,y0,x1,y1,source[y0:y1,x0:x1].copy())
            source[y0:y1,x0:x1]=image[y0:y1,x0:x1]
        report,images=recognize(source,polygon,crop_config)
        attempts = None
        if item.get('source')=='expansion' and border_crop_failure(report):
            retry_config={**crop_config,'margin':chain_config.get('border_retry_margin',3)}
            retry,retry_images=recognize(source,polygon,retry_config)
            attempts=[{'margin':crop_config['margin'],'identity':report['identity'],'reasons':report['reasons']},
                      {'margin':retry_config['margin'],'identity':retry['identity'],'reasons':retry['reasons']}]
            if retry['identity'] is not None:
                report,images=retry,retry_images;crop_config=retry_config
        if preprocess:
            report, images = retry_with_preprocessing(source, polygon, crop_config, report, images)
        if attempts is not None:
            report['crop_attempts'] = attempts
        if restore is not None:
            x0,y0,x1,y1,block=restore;source[y0:y1,x0:x1]=block
            images['normalized_source']=normalize(image,polygon,crop_config)[0]
        report['rectified_margin']=crop_config['margin']
        report['sampling_vertices']=polygon.tolist()
        readings.append({'id':f'T{i}',**report});tiles.append(images)
        values=report['identity'];label=f'[{values[0]}|{values[1]}]' if values is not None else '[?|?]'
        x,y=map(int,item['center'])
        cv2.putText(annotated,label,(x-25,y),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,230) if values is not None else (0,150,255),2)
    return {'original':image,'annotated':annotated,'debug':debug,'tiles':tiles,
            'report':{'detected_count':len(found),'recognized_count':sum(r['identity'] is not None for r in readings),
                      'unknown_count':sum(r['identity'] is None for r in readings),
                      'green_fraction':float(np.mean(debug['02_background']!=0)),
                      'warnings':['Catena sperimentale: componenti ambigue o incomplete'] if geometry['ambiguous'] or geometry['unresolved_components'] else [],
                      'detections':found,'readings':readings,'chain_geometry':geometry,
                      'pipeline_ms':1000*(time.perf_counter()-started)}}


def run(split):
    d=json.loads((ROOT/'config/detection_live.json').read_text());r=json.loads((ROOT/'config/recognition_live.json').read_text())
    rows=[]
    for path in sorted((ROOT/'data/task08a'/split).glob('*.json')):
        gt=json.loads(path.read_text());image=cv2.imread(str(path.with_suffix('.png')))
        bundle=analyze(image,d,r);report=bundle['report']
        score=match_detections(report['detections'],gt['tiles'],.5)
        correct=sum(report['readings'][m['detection']]['identity'] is not None and sorted(report['readings'][m['detection']]['identity'])==sorted(gt['tiles'][m['truth']]['values']) for m in score['matches'])
        normal,_,_=detect_white_faces(image,d)
        baseline=match_detections(normal,gt['tiles'],.5)
        row={'case':path.stem,'real':len(gt['tiles']),'detected':len(report['detections']),
             'correctly_separated':score['tp'],'correct_identities':correct,
             'tp':score['tp'],'fp':score['fp'],'fn':score['fn'],'precision':score['precision'],'recall':score['recall'],
             'normal_tp':baseline['tp'],'normal_fp':baseline['fp'],
             'ambiguous_hypotheses':len(report['chain_geometry']['ambiguous']),
             'unresolved_regions':len(report['chain_geometry']['unresolved_components']),
             'pipeline_ms':report['pipeline_ms']}
        folder=ROOT/'results/task08a'/split/path.stem
        write_image(folder/'annotated.png',bundle['annotated'])
        for name,im in bundle['debug'].items():write_image(folder/f'{name}.png',im)
        for i,images in enumerate(bundle['tiles'],1):
            for name,im in images.items():write_image(folder/f'tiles/T{i}'/f'{name}.png',im)
        write_json(folder/'geometry_and_recognition.json',report)
        write_json(folder/'evaluation.json',{'metrics':row,'matches':score})
        write_image(folder/'comparison.png',np.hstack([cv2.resize(image,(640,360)),cv2.resize(bundle['annotated'],(640,360))]))
        rows.append(row)
    folder=ROOT/'results/task08a'/split;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'metrics.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(split,json.dumps(rows,indent=2),flush=True)
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--split',default='development');parser.add_argument('--generate',action='store_true');parser.add_argument('--seed',type=int,default=80801)
    parser.add_argument('--real',action='store_true');parser.add_argument('--show',action='store_true')
    args=parser.parse_args()
    if args.real:
        evaluate_real()
        return
    if args.generate:generate(args.split,args.seed)
    run(args.split)
    if args.show:
        title='Task08A statico | SPAZIO/N avanti | Q esci'
        try:
            for path in sorted((ROOT/'results/task08a'/args.split).glob('*/comparison.png')):
                cv2.namedWindow(title,cv2.WINDOW_NORMAL);cv2.imshow(title,cv2.imread(str(path)))
                while True:
                    key=cv2.waitKey(100)&255
                    if key in [ord('q'),ord('Q'),27] or cv2.getWindowProperty(title,cv2.WND_PROP_VISIBLE)<1:return
                    if key in [32,ord('n'),ord('N')]:break
        finally:cv2.destroyAllWindows()


def evaluate_real():
    d=json.loads((ROOT/'config/detection_live.json').read_text());r=json.loads((ROOT/'config/recognition_live.json').read_text())
    rows=[]
    for path in sorted((ROOT/'data/real').glob('*.png')):
        image=cv2.imread(str(path));normal_started=time.perf_counter();normal,_,_=detect_white_faces(image,d)
        normal_readings=[recognize(image,item['vertices'],r)[0]['identity'] for item in normal]
        normal_ms=1000*(time.perf_counter()-normal_started)
        bundle=analyze(image,d,r);report=bundle['report']
        equivalent=match_detections(report['detections'],normal,.99)
        same_values=sum(report['readings'][m['detection']]['identity']==normal_readings[m['truth']] for m in equivalent['matches'])
        row={'image':path.name,'normal_detected':len(normal),'experimental_detected':len(report['detections']),
             'same_rectangles_as_normal':equivalent['tp'],'same_readings_as_normal':same_values,
             'recognized':report['recognized_count'],'unknown':report['unknown_count'],
             'normal_pipeline_ms':normal_ms,'pipeline_ms':report['pipeline_ms'],'physical_touching_chain_verified':False}
        folder=ROOT/'results/task08a/real'/path.stem
        write_image(folder/'annotated.png',bundle['annotated'])
        for name,im in bundle['debug'].items():write_image(folder/f'{name}.png',im)
        write_json(folder/'report.json',report);rows.append(row)
    write_json(ROOT/'results/task08a/real/summary.json',{'role':'existing_real_isolated_photos_baseline_consistency_not_touching_chain_validation','rows':rows})
    print(json.dumps(rows,indent=2),flush=True)


if __name__=='__main__':main()
