"""Raffinamento della sola faccia chiara, prima delle regole geometriche esistenti."""
import cv2
import numpy as np
from static_domino import detect


def detect_white_faces(image, config):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array(config['green_hsv_low']), np.array(config['green_hsv_high']))
    face = config['white_face_refinement']
    white = np.uint8((hsv[:, :, 1] < face['max_saturation'])
                     & (hsv[:, :, 2] > face['min_value']) & (green == 0))*255
    kernel = np.ones((face['closing_kernel'],)*2, np.uint8)
    joined = cv2.morphologyEx(white, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(joined)
    cv2.drawContours(filled, contours, -1, 255, -1)
    # Codifica la maschera per riusare detect(), inclusi tutti i filtri geometrici.
    # Le immagini originali sono usate dal riconoscitore; qui non si contano puntini.
    middle = ((np.array(config['green_hsv_low'])+np.array(config['green_hsv_high']))/2).astype(np.uint8)
    background = cv2.cvtColor(middle.reshape(1, 1, 3), cv2.COLOR_HSV2BGR)[0, 0]
    proxy = np.empty_like(image)
    proxy[:] = background
    proxy[filled != 0] = (255, 255, 255)
    found, candidates, debug = detect(proxy, config)
    all_contours, _ = cv2.findContours(debug['04_morphology'], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_view = image.copy()
    cv2.drawContours(contour_view, all_contours, -1, (255, 80, 0), 2)
    annotated = image.copy()
    for tile in found:
        cv2.polylines(annotated, [np.int32(np.rint(tile['vertices']))], True, (0, 0, 255), 2)
    debug.update({'01_original': image, '02_background': green, '03_objects': cv2.bitwise_not(green),
                  '03b_white_face_threshold': white, '03c_white_face_closed': joined,
                  '03d_white_face_filled': filled, '05_contours': contour_view, '06_final': annotated})
    return found, candidates, debug
