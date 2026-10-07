"""Bit-exact host models of the two P3 tracker cores, behind one API, plus the tracking rules
shared by the server-crop and FPGA-crop modes (p3_track/rtl/row_stats.v).

    model = make_model("zsad" | "s3x8")
    model.ROI, model.MARGIN, model.TMPL_BYTES
    model.template(frame, tx, ty) -> bytes      template for a target window at (tx, ty)
    model.match(roi) -> (bx, by, score, good)   exactly what the FPGA core reports for this ROI

Tracking rules (same as the RTL): the position t = (tx, ty) is the top-left of the 16x16 target
window in frame pixels. ROI origin = clamp(t - (ROI-16)/2, 0, size - ROI). After a good result
t = origin + (bx, by) + MARGIN. Frames smaller than the ROI are padded right/bottom by edge
replication (the server does this before sending).
"""
import json, os
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = 16


class ZsadModel:
    """User's template_match.sv (RADIUS 0): ZSAD over the 80x80 ROI, template = 16x16 gray patch."""
    name, ROI, MARGIN, TMPL_BYTES = "zsad", 80, 0, 256
    REJECT_SAD, SCORE_SAT = 8192, 0xFFFF

    def template(self, frame, tx, ty):
        return np.ascontiguousarray(frame[ty:ty + WIN, tx:tx + WIN], dtype=np.uint8).tobytes()

    def match(self, roi):
        bx, by, z, good, _ = self.inspect(roi)
        return bx, by, z, good

    def inspect(self, roi):
        """match() plus what the demo displays: {"map": ZSAD scores (65, 65)}."""
        t = np.frombuffer(self._t, np.uint8).reshape(WIN, WIN).astype(np.int64)
        w = sliding_window_view(roi.astype(np.int64), (WIN, WIN))
        delta = (w.sum((2, 3)) - t.sum() + (WIN * WIN) // 2) >> 8
        m = np.abs(w - t - delta[..., None, None]).sum((2, 3))
        by, bx = divmod(int(np.argmin(m)), m.shape[1])     # first minimum in raster order
        z = int(m[by, bx])
        return bx, by, min(z, self.SCORE_SAT), z <= self.REJECT_SAD, {"map": m}

    def template_features(self):
        return None

    def set_template(self, tb):
        self._t = bytes(tb)


class S3x8Model:
    """E48 integer S-3x8 (3 conv x 8 ch, int8, 8-bit requant) + L1 matcher, ROI 72, 49 x 49 candidates.
    Template = int8 features of a 24x24 crop around the target (edge padded), centre 16x16."""
    name, ROI, MARGIN, TMPL_BYTES = "s3x8", 72, 4, 2048
    PAD = 4

    def __init__(self, qlayers=os.path.join(HERE, "models", "s3x8_qlayers_8.json")):
        d = json.load(open(qlayers))
        self.layers = [dict(w=np.array(l["w"], np.int64), M=np.array(l["M"], np.int64),
                            s=np.array(l["s"], np.int64), B=np.array(l["B"], np.int64), signed=bool(l["signed"]))
                       for l in d["layers"]]

    # --- integer model (same arithmetic as E48 src/intmodel.py) ---
    @staticmethod
    def _conv(x, w):
        Ci, H, W = x.shape
        acc = np.zeros((w.shape[0], H - 2, W - 2), np.int64)
        for dy in range(3):
            for dx in range(3):
                acc += np.einsum("oi,ihw->ohw", w[:, :, dy, dx], x[:, dy:dy + H - 2, dx:dx + W - 2])
        return acc

    @staticmethod
    def _requant(acc, ly):
        M, s, B = ly["M"][:, None, None], ly["s"][:, None, None], ly["B"][:, None, None]
        q = (acc * M + B + (np.int64(1) << (s - 1))) >> s
        return np.clip(q, -127, 127) if ly["signed"] else np.clip(q, 0, 255)

    def embed(self, img):
        x = np.asarray(img, np.int64)[None]
        for ly in self.layers:
            x = self._requant(self._conv(x, ly["w"]), ly)
        return x

    def template(self, frame, tx, ty):
        p = self.PAD
        crop = np.pad(frame, p, mode="edge")[ty:ty + WIN + 2 * p, tx:tx + WIN + 2 * p]
        m = p - len(self.layers)
        tf = self.embed(crop)[:, m:m + WIN, m:m + WIN]            # (8, 16, 16) int8
        # row r: byte k*8 + c = tf[c, r, k]  (s3x8_top t_data layout)
        return (tf.transpose(1, 2, 0).astype(np.int8)).tobytes()

    def set_template(self, tb):
        a = np.frombuffer(bytes(tb), np.int8).reshape(WIN, WIN, -1)   # (r, k, c)
        self._tf = a.transpose(2, 0, 1).astype(np.int64)              # (c, r, k)

    def match(self, roi):
        bx, by, z, good, _ = self.inspect(roi)
        return bx, by, z, good

    def inspect(self, roi):
        """match() plus what the demo displays: {"map": L1 scores (49, 49), "feat": ROI features (8, 64, 64)}."""
        m = self.PAD - len(self.layers)
        nc = self.ROI - WIN - 2 * self.PAD + 1                          # 49
        f = self.embed(roi)[:, m:m + nc + WIN - 1, m:m + nc + WIN - 1]  # (8, 64, 64)
        w = sliding_window_view(f, (WIN, WIN), axis=(1, 2))             # (8, 49, 49, 16, 16)
        s = np.abs(w - self._tf[:, None, None]).sum((0, 3, 4))
        by, bx = divmod(int(np.argmin(s)), s.shape[1])
        return bx, by, int(s[by, bx]), True, {"map": s, "feat": f}

    def template_features(self):
        return self._tf                                                  # (8, 16, 16)


def make_model(name):
    return {"zsad": ZsadModel, "s3x8": S3x8Model}[name]()


def pad_to(frame, roi):
    ph, pw = max(0, roi - frame.shape[0]), max(0, roi - frame.shape[1])
    return np.pad(frame, ((0, ph), (0, pw)), mode="edge") if (ph or pw) else frame


class Track:
    """Position state + ROI rules shared with the RTL."""

    def __init__(self, model, frame0, center0):
        self.m = model
        f = pad_to(frame0, model.ROI)
        H, W = f.shape
        self.tx = int(np.clip(round(center0[0] - WIN / 2), 0, W - WIN))
        self.ty = int(np.clip(round(center0[1] - WIN / 2), 0, H - WIN))
        self.tmpl = model.template(f, self.tx, self.ty)
        model.set_template(self.tmpl)

    def origin(self, shape):
        off = (self.m.ROI - WIN) // 2
        H, W = shape
        return (int(np.clip(self.tx - off, 0, W - self.m.ROI)), int(np.clip(self.ty - off, 0, H - self.m.ROI)))

    def crop(self, frame):
        """-> (padded frame, ROI origin, ROI)."""
        f = pad_to(frame, self.m.ROI)
        ox, oy = self.origin(f.shape)
        return f, (ox, oy), np.ascontiguousarray(f[oy:oy + self.m.ROI, ox:ox + self.m.ROI])

    def step_model(self, frame):
        """Model-only step: -> (bx, by, score, good, origin)."""
        f, o, roi = self.crop(frame)
        bx, by, z, good = self.m.match(roi)
        self.update(o, bx, by, good)
        return bx, by, z, good, o

    def update(self, origin, bx, by, good):
        if good:
            self.tx, self.ty = origin[0] + bx + self.m.MARGIN, origin[1] + by + self.m.MARGIN

    def center(self):
        return self.tx + WIN / 2, self.ty + WIN / 2
