"""Demo dashboard (1920 x 1080) and the background FPGA = model checker for demo.py.

Checker: every board result is re-computed by the bit-exact host model in worker processes, so the
display loop runs at camera rate while every frame is still checked (a few frames late). Workers also
return what the dashboard shows: the full score map and, for S-3x8, the ROI feature maps.

Dashboard: camera view with boxes, the scaled gray frame the FPGA receives, the ROI with the FPGA's
best window, the score map, the template (gray patch and, for S-3x8, its int8 feature maps), the ROI
feature maps, history plots (score, FPGA compute, round trip, fps) and the protocol flags.
"""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

import cv2
import numpy as np

W, H = 1920, 1080
MAIN_W, MAIN_H = 1280, 720
FONT = cv2.FONT_HERSHEY_SIMPLEX
GREY, WHITE, GREEN, RED, ORANGE, CYAN, YELLOW = ((170, 170, 170), (235, 235, 235), (0, 220, 0), (0, 0, 255),
                                                 (0, 160, 255), (255, 200, 0), (0, 230, 230))
FLAG_NAMES = ((1, "complete"), (2, "closed"), (4, "good"), (8, "tracked"), (16, "timeout"), (32, "RTL crop"))

# ---------------------------------------------------------------- checker (worker processes)
_model, _tmpl = None, None


def _init(tracker):
    global _model
    from trackers import make_model
    _model = make_model(tracker)


def _check(job):
    """job: n, tmpl, roi, origin, prev_pos, crop, res (dict or None), margin -> check result for frame n."""
    global _tmpl
    if job["tmpl"] != _tmpl:
        _model.set_template(job["tmpl"])
        _tmpl = job["tmpl"]
    mx, my, mz, mgood, extra = _model.inspect(job["roi"])
    res, ok = job["res"], None
    if res is not None:
        m = job["margin"]
        if job["crop"] == "fpga":
            exp_o = job["origin"]
            exp_xy = (exp_o[0] + mx + m, exp_o[1] + my + m) if mgood else job["prev_pos"]
        else:
            exp_o = (0, 0)
            exp_xy = (mx + m, my + m) if mgood else (res["x"], res["y"])
        tracked = bool(res["flags"] & 8) and bool(res["flags"] & 1)
        ok = (tracked and res["score"] == mz and bool(res["flags"] & 4) == mgood
              and (res["roi_x"], res["roi_y"]) == tuple(exp_o) and (res["x"], res["y"]) == tuple(exp_xy))
    out = dict(n=job["n"], ok=ok, mx=mx, my=my, mz=mz, mgood=mgood, map=extra["map"].astype(np.int32))
    if "feat" in extra:
        out["feat"] = extra["feat"].astype(np.int16)
    return out


class Checker:
    """Submit one job per frame; poll() returns finished checks in frame order."""

    def __init__(self, tracker, workers=4):
        self.ex = ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"), initializer=_init,
                                      initargs=(tracker,))
        self.pending = deque()

    def submit(self, job):
        self.pending.append(self.ex.submit(_check, job))

    def poll(self, wait=False):
        out = []
        while self.pending and (wait or self.pending[0].done()):
            out.append(self.pending.popleft().result())
        return out

    def lag(self):
        return len(self.pending)

    def close(self):
        self.ex.shutdown(wait=True)


# ---------------------------------------------------------------- drawing helpers
def text(img, s, x, y, col=WHITE, scale=0.55, th=1):
    cv2.putText(img, s, (int(x), int(y)), FONT, scale, col, th, cv2.LINE_AA)


def title(img, s, x, y):
    text(img, s, x, y, YELLOW, 0.5)


def fit(img, w, h, interp=cv2.INTER_AREA):
    """Resize to fit (w, h) keeping the aspect ratio -> (image, scale)."""
    s = min(w / img.shape[1], h / img.shape[0])
    return cv2.resize(img, (max(1, round(img.shape[1] * s)), max(1, round(img.shape[0] * s))), interpolation=interp), s


def paste(dst, src, x, y):
    h, w = src.shape[:2]
    dst[y:y + h, x:x + w] = src if src.ndim == 3 else cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)


def heat(a, size, cmap=cv2.COLORMAP_VIRIDIS, lo=None, hi=None):
    a = np.asarray(a, np.float64)
    lo = a.min() if lo is None else lo
    hi = a.max() if hi is None else hi
    u = np.clip((a - lo) / max(1e-9, hi - lo) * 255, 0, 255).astype(np.uint8)
    return cv2.resize(cv2.applyColorMap(u, cmap), size, interpolation=cv2.INTER_NEAREST)


def gray_tile(a, size):
    return cv2.cvtColor(cv2.resize(np.asarray(a, np.uint8), size, interpolation=cv2.INTER_NEAREST),
                        cv2.COLOR_GRAY2BGR)


def feat_grid(f, tile, amp, cols=4, gap=4):
    """(C, h, w) int feature maps -> grid of heat tiles on one diverging scale [-amp, amp]
    (the same amp for the template and the ROI features, so their colours compare)."""
    c = f.shape[0]
    rows = (c + cols - 1) // cols
    g = np.full((rows * (tile + gap) - gap, cols * (tile + gap) - gap, 3), 30, np.uint8)
    for i in range(c):
        r, k = divmod(i, cols)
        paste(g, heat(f[i], (tile, tile), cv2.COLORMAP_TWILIGHT_SHIFTED, -amp, amp), k * (tile + gap), r * (tile + gap))
    return g


def plot(img, x, y, w, h, vals, name, unit, col, fmt="{:.0f}", lo=None, hi=None):
    """Sparkline of the recent history with its range and last value (axis from the data unless lo/hi)."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (60, 60, 60), 1)
    v = np.array([q for q in vals if q is not None and np.isfinite(q)], float)
    if len(v) < 2:
        title(img, f"{name} [{unit}]", x + 4, y - 6)
        return
    title(img, f"{name} [{unit}]: " + fmt.format(v[-1]), x + 4, y - 6)
    lo = float(v.min()) if lo is None else lo
    hi = float(v.max()) if hi is None else hi
    v = np.clip(v, lo, hi)
    if hi - lo < 1e-9:
        hi = lo + 1
    pts = np.stack([x + np.linspace(0, w, len(v)), y + h - (v - lo) / (hi - lo) * (h - 4) - 2], 1).astype(np.int32)
    cv2.polylines(img, [pts], False, col, 1, cv2.LINE_AA)
    text(img, fmt.format(hi), x + w + 4, y + 12, GREY, 0.4)
    text(img, fmt.format(lo), x + w + 4, y + h, GREY, 0.4)


# ---------------------------------------------------------------- dashboard
class Dash:
    def __init__(self, model, tname, note, hist=300):
        self.m, self.tname, self.note = model, tname, note
        self.h = {k: deque(maxlen=hist) for k in ("score", "fpga_us", "rtt_us", "fps")}
        self.last_check = None
        self.checked = self.mismatch = 0
        self.first_bad = None

    def add_check(self, c):
        if c["ok"] is not None:
            self.checked += 1
            if not c["ok"]:
                self.mismatch += 1
                self.first_bad = self.first_bad or c["n"]
        self.last_check = c

    def render(self, d):
        """d: frame (BGR, camera), n, k, name, mode, view boxes, fp (scaled gray frame), roi, origin,
        best (window top-left in the ROI or None), res, score, good, f_us, rtt_us, rx_us, fps,
        tmpl_patch (16x16 gray), tmpl_feat (or None), lag, board (bool), init (bool)."""
        img = np.zeros((H, W, 3), np.uint8)
        m = self.m
        # ---- camera view
        v, s = fit(d["frame"], MAIN_W, MAIN_H)
        ox, oy = (MAIN_W - v.shape[1]) // 2, (MAIN_H - v.shape[0]) // 2
        bx = lambda r: (int(ox + r[0] * s), int(oy + r[1] * s), int(ox + (r[0] + r[2]) * s), int(oy + (r[1] + r[3]) * s))
        if d.get("gt") is not None and np.isfinite(d["gt"]).all():
            a = bx(d["gt"])
            cv2.rectangle(v, (a[0] - ox, a[1] - oy), (a[2] - ox, a[3] - oy), (200, 200, 200), 1)
        a = bx(d["roi_box"])
        for t in range(a[0], a[2], 10):
            cv2.line(v, (t - ox, a[1] - oy), (min(t + 5, a[2]) - ox, a[1] - oy), CYAN, 1)
            cv2.line(v, (t - ox, a[3] - oy), (min(t + 5, a[2]) - ox, a[3] - oy), CYAN, 1)
        for t in range(a[1], a[3], 10):
            cv2.line(v, (a[0] - ox, t - oy), (a[0] - ox, min(t + 5, a[3]) - oy), CYAN, 1)
            cv2.line(v, (a[2] - ox, t - oy), (a[2] - ox, min(t + 5, a[3]) - oy), CYAN, 1)
        a = bx(d["box"])
        cv2.rectangle(v, (a[0] - ox, a[1] - oy), (a[2] - ox, a[3] - oy), GREEN if d["good"] else ORANGE, 2)
        paste(img, v, ox, oy)

        # ---- right column: what the FPGA gets
        X = MAIN_W + 16
        cw = W - X - 16
        fp = d["fp"]
        fpv, fs = fit(fp, cw, 200, cv2.INTER_NEAREST)
        fpv = cv2.cvtColor(fpv, cv2.COLOR_GRAY2BGR)
        o = d["origin"]
        cv2.rectangle(fpv, (int(o[0] * fs), int(o[1] * fs)), (int((o[0] + m.ROI) * fs), int((o[1] + m.ROI) * fs)), CYAN, 1)
        title(img, f"{'FPGA input: whole scaled frame' if d['mode'] == 'fpga' else 'scaled frame (server crops the ROI)'}"
                   f" {fp.shape[1]}x{fp.shape[0]} gray", X, 22)
        paste(img, fpv, X, 30)
        y = 30 + fpv.shape[0] + 30

        # ROI and score map
        t = 290
        roi_v = gray_tile(d["roi"], (t, t))
        k = t / m.ROI
        if d["best"] is not None:
            p = d["best"]
            cv2.rectangle(roi_v, (int(p[0] * k), int(p[1] * k)), (int((p[0] + 16) * k), int((p[1] + 16) * k)),
                          GREEN if d["good"] else ORANGE, 2)
        title(img, f"ROI at ({o[0]},{o[1]}) + {'FPGA' if d['board'] else 'model'} best", X, y - 8)
        paste(img, roi_v, X, y)
        c = self.last_check
        if c is not None:
            mp_ = c["map"]
            # bright = good match; colour scale from the best score to the median (the rest is dark)
            hv = heat(-mp_.astype(np.float64), (t, t), cv2.COLORMAP_INFERNO, -float(np.median(mp_)), -float(mp_.min()))
            kk = t / mp_.shape[1]
            cv2.drawMarker(hv, (int((c["mx"] + 0.5) * kk), int((c["my"] + 0.5) * kk)), (0, 255, 0), cv2.MARKER_CROSS, 14, 2)
            title(img, f"score map (model, frame {c['n']})", X + t + 16, y - 8)
            paste(img, hv, X + t + 16, y)
        y += t + 34

        # template
        title(img, "template (target, 16x16 gray)" if d["tmpl_feat"] is None else "template: target patch | int8 features (8 ch)", X, y - 8)
        paste(img, gray_tile(d["tmpl_patch"], (128, 128)), X, y)
        if d["tmpl_feat"] is not None:
            amp = max(1.0, float(np.abs(d["tmpl_feat"]).max()))
            g = feat_grid(d["tmpl_feat"], 60, amp)
            paste(img, g, X + 144, y)
            y += max(128, g.shape[0]) + 34
            if c is not None and "feat" in c:
                title(img, f"ROI features 8 x {c['feat'].shape[1]}x{c['feat'].shape[2]} (model, frame {c['n']})", X, y - 8)
                g = feat_grid(c["feat"], min(140, (cw - 12) // 4), amp)
                paste(img, g[:H - y - 8], X, y)
        else:
            if d["best"] is not None:
                p = d["best"]
                win = d["roi"][p[1]:p[1] + 16, p[0]:p[0] + 16]
                if win.shape == (16, 16):
                    title(img, "best window", X + 144, y + 140)
                    paste(img, gray_tile(win, (128, 128)), X + 144, y)
                    tp = d["tmpl_patch"].astype(np.int64)
                    w_ = win.astype(np.int64)
                    diff = np.abs((w_ - w_.mean()) - (tp - tp.mean()))
                    paste(img, heat(diff, (128, 128), cv2.COLORMAP_INFERNO, 0, 128), X + 288, y)
                    title(img, "|zero-mean diff|", X + 288, y + 140)

        # ---- bottom: status text and history plots
        Y = MAIN_H + 8
        board = d["board"]
        line1 = f"{d['name']}  frame {d['k'] if d['k'] is not None else d['n']}   {self.tname}   " \
                f"{'crop in the FPGA (RTL)' if d['mode'] == 'fpga' else 'crop on the server'}" if board else \
                f"{d['name']}  frame {d['n']}   {self.tname}   NO BOARD: host model only, not the FPGA"
        text(img, line1, 12, Y + 22, WHITE, 0.62)
        if board:
            ok_col = GREEN if self.mismatch == 0 else RED
            text(img, f"FPGA = bit-exact model: {self.checked - self.mismatch}/{self.checked} frames checked"
                      f"{'' if self.mismatch == 0 else f'   MISMATCH x{self.mismatch} (first at frame {self.first_bad})'}"
                      f"   (check lag {d['lag']} frames)", 12, Y + 50, ok_col, 0.62)
            r = d["res"]
            if r is not None:
                fl = ", ".join(nm for b, nm in FLAG_NAMES if r["flags"] & b)
                text(img, f"result: score {r['score']} ({'good' if d['good'] else 'rejected: hold'})   position ({r['x']},{r['y']})"
                          f"   ROI origin ({r['roi_x']},{r['roi_y']})   rows {r['rows_seen']}/{r['height']}   flags {fl}",
                     12, Y + 78, WHITE, 0.5)
            else:
                text(img, "result: none (timeout)", 12, Y + 78, RED, 0.5)
            text(img, f"FPGA: frame in over {d['rx_us']:.0f} us, result {d['f_us']:.1f} us after the last row   "
                      f"network round trip {d['rtt_us']:.0f} us (transport, not part of the drone system)   "
                      f"display {d['fps']:.1f} fps", 12, Y + 102, WHITE, 0.5)
        else:
            text(img, f"model score {d['score']} ({'good' if d['good'] else 'rejected: hold'})   display {d['fps']:.1f} fps",
                 12, Y + 50, ORANGE, 0.6)
        text(img, self.note, 12, Y + 126, GREY, 0.5)
        text(img, "boxes: green = result (orange = rejected, hold)   grey = ground truth   dashed = ROI", 12, Y + 148, GREY, 0.45)
        pw, ph, py = 280, 110, Y + 192
        plot(img, 12, py, pw, ph, self.h["score"], "score", "low = good", (0, 200, 255))
        if board:
            plot(img, 12 + 320, py, pw, ph, self.h["fpga_us"], "FPGA after last row", "us", GREEN, "{:.1f}")
            plot(img, 12 + 640, py, pw, ph, self.h["rtt_us"], "round trip", "us", CYAN)
        plot(img, 12 + 960, py, pw, ph, self.h["fps"], "display rate", "fps", WHITE, "{:.1f}", 0, 40)
        return img
