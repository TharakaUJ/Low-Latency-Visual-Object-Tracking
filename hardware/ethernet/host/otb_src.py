"""OTB-100 frames for the demo, read from the research tree (read-only import of common.otb_full).
Same preprocessing as the research loaders (grayscale, one fixed scale per target, INTER_AREA,
invalid GT -> NaN), except the target size is a parameter (demo default 16 px; research uses 20)."""
import os, sys
import numpy as np
import cv2

RESEARCH = os.path.expanduser("~/Documents/Object_tracking_test/object_tracking")
sys.path.insert(0, RESEARCH)
from common import otb_full            # noqa: E402
from common import metrics             # noqa: E402


def targets():
    return otb_full.targets()


def load(key, target_px=16.0, color=False):
    """-> dict(name, frames (scaled gray), frames_orig (BGR, only if color), gt (scaled), gt_orig, scale)."""
    m = otb_full.meta()[key]
    imgs = [os.path.join(otb_full.ROOT, p) for p in m["img_names"]]
    gt = np.array(m["gt_rect"], dtype=np.float64)[:, :4]
    n = min(len(imgs), len(gt))
    imgs, gt = imgs[:n], gt[:n].copy()
    bad = ~np.isfinite(gt).all(1) | (gt[:, 2] <= 0) | (gt[:, 3] <= 0)
    gt[bad] = np.nan
    s = target_px / np.sqrt(gt[0, 2] * gt[0, 3])
    frames, orig = [], []
    for p in imgs:
        im = cv2.imread(p, cv2.IMREAD_COLOR)
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        H, W = g.shape
        frames.append(cv2.resize(g, (max(1, round(W * s)), max(1, round(H * s))),
                                 interpolation=cv2.INTER_AREA))
        if color:
            orig.append(im)
    return dict(name=key, frames=frames, frames_orig=orig, gt=gt * s, gt_orig=gt, scale=s,
                attr=list(m["attr"]))


def iou_auc(pred_c, gt_orig, scale):
    """Success AUC with a fixed box size (the first GT box; ZSAD does not estimate scale). Frame 0 excluded."""
    w0, h0 = gt_orig[0, 2], gt_orig[0, 3]
    pc = np.asarray(pred_c[1:]) / scale
    g = gt_orig[1:]
    ok = np.isfinite(g).all(1)
    pc, g = pc[ok], g[ok]
    px0, py0 = pc[:, 0] - w0 / 2, pc[:, 1] - h0 / 2
    ix = np.clip(np.minimum(px0 + w0, g[:, 0] + g[:, 2]) - np.maximum(px0, g[:, 0]), 0, None)
    iy = np.clip(np.minimum(py0 + h0, g[:, 1] + g[:, 3]) - np.maximum(py0, g[:, 1]), 0, None)
    inter = ix * iy
    iou = inter / (w0 * h0 + g[:, 2] * g[:, 3] - inter)
    th = np.linspace(0, 1, 21)
    return float(np.mean([(iou > t).mean() for t in th]) * 100)
