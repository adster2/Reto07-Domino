"""Ordine delle meta basato esclusivamente sulle coordinate della fotocamera."""
import cv2
import numpy as np


def order_halves(values, transform, width, height, divider):
    # Centri geometrici delle due meta fisiche, non centroidi dei puntini.
    centers = np.float64([[divider/2, (height-1)/2],
                          [(divider+width-1)/2, (height-1)/2]])
    inverse = np.linalg.inv(np.asarray(transform, dtype=np.float64))
    camera = cv2.perspectiveTransform(centers[None], inverse)[0]
    delta = camera[1]-camera[0]
    tolerance = 1e-6*max(float(np.linalg.norm(delta)), 1.0)
    axis = 'horizontal' if abs(delta[0])+tolerance >= abs(delta[1]) else 'vertical'
    coordinate = 0 if axis == 'horizontal' else 1
    other = 1-coordinate
    order = sorted(range(2), key=lambda i: (camera[i, coordinate], camera[i, other]))
    direction = camera[order[1]]-camera[order[0]]
    angle = float(np.degrees(np.arctan2(direction[1], direction[0])))
    spatial = []
    for rank, i in enumerate(order):
        x0, x1 = (0, divider) if i == 0 else (divider, width-1)
        corners = np.float64([[x0, 0], [x1, 0], [x1, height-1], [x0, height-1]])
        polygon = cv2.perspectiveTransform(corners[None], inverse)[0]
        toward_other = camera[1-i]-camera[i]
        spatial.append({'reading_rank': rank, 'normalized_index': i, 'value': values[i],
                        'normalized_center': centers[i].tolist(), 'camera_center': camera[i].tolist(),
                        'camera_vertices': polygon.tolist(), 'reading_axis_angle_deg': angle,
                        'toward_other_angle_deg': float(np.degrees(np.arctan2(toward_other[1], toward_other[0])))})
    return {'axis': axis, 'convention': 'left_to_right' if axis == 'horizontal' else 'top_to_bottom',
            'normalized_indices': order, 'values': [values[i] for i in order],
            'reading_axis_angle_deg': angle, 'halves': spatial}
