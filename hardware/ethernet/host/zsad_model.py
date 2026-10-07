"""Bit-exact Python model of hardware/rtl/processing/template_match.sv (RADIUS = 0) on one ROI,
plus the server-side tracking rules of the P2 demo (scale, ROI placement, hold on reject).

template_match.sv, per window w (16x16) and template t:
    delta = (sum(w) - sum(t) + N/2) >>> log2(N)       (arithmetic shift = floor)
    ZSAD  = sum |(w - t) - delta|
Windows arrive in raster order of their top-left corner; the minimum is kept with a strict '<',
so the first (top-most, then left-most) minimum wins. good = min ZSAD <= REJECT_SAD.
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

WIN = 16
REJECT_SAD = 8192
SCORE_SAT = 0xFFFF          # result packet score = debug_data[31:16], saturated to 16 bits


def zsad_map(roi, tmpl):
    """ZSAD for every window position of roi (H, W uint8) -> (H-15, W-15) int64."""
    w = sliding_window_view(roi.astype(np.int64), (WIN, WIN))
    t = tmpl.astype(np.int64)
    delta = (w.sum((2, 3)) - t.sum() + (WIN * WIN) // 2) >> 8
    return np.abs(w - t - delta[..., None, None]).sum((2, 3))


def match(roi, tmpl):
    """-> (x, y, zsad, good) exactly as the FPGA reports them (x, y = window top-left in the ROI)."""
    m = zsad_map(roi, tmpl)
    k = int(np.argmin(m))            # argmin returns the first minimum in raster (C) order
    y, x = divmod(k, m.shape[1])
    z = int(m[y, x])
    return x, y, z, z <= REJECT_SAD


class ZsadTracker:
    """Server-side rules of the demo: fixed template, ROI of size R centred on the last position
    (clamped to the image), position held when the match is rejected."""

    def __init__(self, frame0, center0, roi=80):
        self.R = roi
        self.frame_shape = frame0.shape
        f = self._pad(frame0)
        self.H, self.W = f.shape
        tx = int(np.clip(round(center0[0] - WIN / 2), 0, self.W - WIN))
        ty = int(np.clip(round(center0[1] - WIN / 2), 0, self.H - WIN))
        self.tmpl = f[ty:ty + WIN, tx:tx + WIN].copy()
        self.tx, self.ty = tx, ty

    def _pad(self, f):
        """Frames smaller than the ROI are padded right/bottom by edge replication."""
        ph, pw = max(0, self.R - f.shape[0]), max(0, self.R - f.shape[1])
        return np.pad(f, ((0, ph), (0, pw)), mode="edge") if (ph or pw) else f

    def roi_origin(self):
        off = (self.R - WIN) // 2
        rx = int(np.clip(self.tx - off, 0, self.W - self.R))
        ry = int(np.clip(self.ty - off, 0, self.H - self.R))
        return rx, ry

    def crop(self, frame):
        f = self._pad(frame)
        rx, ry = self.roi_origin()
        return rx, ry, np.ascontiguousarray(f[ry:ry + self.R, rx:rx + self.R])

    def update(self, rx, ry, x, y, good):
        if good:
            self.tx, self.ty = rx + x, ry + y
        return self.center()

    def center(self):
        return self.tx + WIN / 2, self.ty + WIN / 2
