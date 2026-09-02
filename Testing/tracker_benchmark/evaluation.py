# tracker_benchmark/evaluation.py
import numpy as np

def calculate_iou(boxA, boxB):
    # box format: [x, y, w, h]
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0:
        return 0.0

    boxAArea = boxA[2] * boxA[3]
    boxBArea = boxB[2] * boxB[3]
    return interArea / float(boxAArea + boxBArea - interArea)

def calculate_center_error(boxA, boxB):
    cA = np.array([boxA[0] + boxA[2]/2, boxA[1] + boxA[3]/2])
    cB = np.array([boxB[0] + boxB[2]/2, boxB[1] + boxB[3]/2])
    return np.linalg.norm(cA - cB)