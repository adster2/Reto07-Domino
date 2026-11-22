"""Preparazione dei ritagli sperimentali; riusa il riconoscitore consolidato."""
import cv2
import numpy as np
from recognize_domino import normalize,recognize
from spatial_order import order_halves


def border_crop_failure(report):
    if report['reasons']!=['invalid_half']:return False
    rejected=[c for half in report['halves'] for c in half['components']
              if c['rejected_by'] not in (None,'tiny_noise','ignored_border_band')]
    return bool(rejected) and all(c['rejected_by']=='border_or_occlusion' for c in rejected)


def read_camera_tile(image,polygon,recognition_config,chain_config,surface_mask=None):
    original,transform=normalize(image,polygon,recognition_config)
    tile=original.copy();height,width=tile.shape[:2]
    removed=np.zeros((height,width),np.uint8)
    if surface_mask is not None:
        valid=cv2.warpPerspective(surface_mask,transform,(width,height),flags=cv2.INTER_NEAREST)
        outside=valid==0
        band=chain_config.get('divider_protection_fraction',.12)*height
        outside[:,int(width/2-band):int(width/2+band)+1]=False
        tile[outside]=(255,255,255);removed[outside]=255
    margin=recognition_config['margin']
    white=float(np.percentile(cv2.cvtColor(original,cv2.COLOR_BGR2GRAY)[margin:height-margin,margin:width-margin],75))
    gain=1.
    if white>=recognition_config['min_white']:
        gain=max(1.,min(chain_config.get('photometric_max_gain',1.6),
                        chain_config.get('photometric_target_white',230)/max(white,1)))
    if gain>1:tile=np.clip(tile.astype(np.float32)*gain,0,255).astype(np.uint8)
    canonical=np.float32([[0,0],[width-1,0],[width-1,height-1],[0,height-1]])
    config=dict(recognition_config)
    if surface_mask is not None:config['margin']=chain_config.get('rectified_margin',config['margin'])
    report,images=recognize(tile,canonical,config)
    if surface_mask is not None and border_crop_failure(report):
        retry_config={**config,'margin':chain_config.get('border_retry_margin',3)}
        retry,retry_images=recognize(tile,canonical,retry_config)
        attempts=[{'margin':config['margin'],'identity':report['identity'],'reasons':report['reasons']},
                  {'margin':retry_config['margin'],'identity':retry['identity'],'reasons':retry['reasons']}]
        if retry['identity'] is not None:report,images,config=retry,retry_images,retry_config
        report['crop_attempts']=attempts
    # Il secondo warp e canonico; comporre comunque le due omografie evita
    # qualsiasi dipendenza dall'ordine dei vertici o da coordinate del ritaglio.
    camera_transform=np.asarray(report['transform'])@transform
    spatial=order_halves(report['half_values'],camera_transform,width,height,report['divider_x'])
    report.update({'transform':camera_transform.tolist(),'spatial_order':spatial,
                   'identity':spatial['values'] if not report['reasons'] else None,
                   'rectified_margin':config['margin'],'sampling_vertices':np.asarray(polygon).tolist(),
                   'photometric_white_before':white,'photometric_gain':gain,
                   'background_removed_pixels':int(np.count_nonzero(removed))})
    images['normalized_source']=original;images['surface_removed']=removed
    return report,images
