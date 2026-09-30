#!/usr/bin/env python3
"""
int_model.py — bit-exact integer reference model for the layer-pipelined
Tiny-CNN, built directly from the same gen/ files the RTL loads (gen/tcnn.json,
gen/w_L*.hex [packed], gen/b_L*.hex, gen/m_L*.hex, gen/s_L*.hex, gen/hw.hex,
gen/hb.hex).

This is the model RTL simulation and the FPGA board must match EXACTLY. It
deliberately unpacks the same lane-packed weight ROM format the RTL reads
(see docs/architecture.md's "Data formats" section), rather than reading the
ONNX weights directly, so a layout bug in gen_tcnn.py's packing is caught
here before any RTL exists.

Per-layer arithmetic (matches gen_tcnn.py's quantize_multiplier contract,
inherited from fpga_cnn_pipeline/onnx_to_rtl.py -- real_multiplier ==
M0 * 2^-shift exactly, NO extra 2^-31 factor):
    acc  = bias[oc] + sum_{kh,kw,ic} x[ih,iw,ic] * w[oc,ic,kh,kw]   (int, zp==0 everywhere)
    y    = round_half_up( (acc * M0) / 2^shift ) == (acc*M0 + (1<<(shift-1))) >> shift
    out  = clamp(y + out_zp, 0, 255)                                (uint8, ReLU via clamp)

The GAP step sums (not averages) the last conv layer's N_SPATIAL positions
per channel, then requantizes that integer sum directly to the 'view' code
with GAP_MULT/GAP_SHIFT (the /N_SPATIAL average is folded into that fixed-
point multiplier -- see gen_tcnn.py's find_gap_requant() docstring).

Activations are HWC uint8, all zero-points 0 except head output (123).
"""
import json
import os

import numpy as np


def requant(acc, mult: int, shift: int, out_zp: int):
    """acc: int64 (scalar or ndarray). Returns uint8 (same shape), round-half-up."""
    acc = np.asarray(acc, dtype=np.int64)
    prod = acc * np.int64(mult)
    rounding = np.int64(1) << np.int64(shift - 1)
    y = (prod + rounding) >> np.int64(shift)
    y = y + out_zp
    return np.clip(y, 0, 255).astype(np.uint8)


def _unpack_weight_rom(path, cout, npass, cin_par):
    """Reads gen/w_L{k}.hex: one line per (oc,pass), lane j = tap*cin_par+ci_local
    at bits [4j+3:4j], two's complement int4. Returns w[oc][ci][ky][kx] int32,
    ci in [0, cin_par*npass)."""
    with open(path) as f:
        words = [int(line.strip(), 16) for line in f if line.strip()]
    assert len(words) == cout * npass, (path, len(words), cout * npass)
    cin = cin_par * npass
    w = np.zeros((cout, cin, 3, 3), dtype=np.int32)
    for oc in range(cout):
        for p in range(npass):
            word = words[oc * npass + p]
            for tap in range(9):
                ky, kx = divmod(tap, 3)
                for ci_local in range(cin_par):
                    j = tap * cin_par + ci_local
                    nib = (word >> (4 * j)) & 0xF
                    if nib >= 8:
                        nib -= 16
                    ci = p * cin_par + ci_local
                    w[oc, ci, ky, kx] = nib
    return w


def _load_u32_hex(path, n):
    with open(path) as f:
        vals = [int(line.strip(), 16) for line in f if line.strip()]
    assert len(vals) == n, (path, len(vals), n)
    vals = [v - (1 << 32) if v >= (1 << 31) else v for v in vals]
    return np.array(vals, dtype=np.int64)


class IntModel:
    def __init__(self, gen_dir="gen"):
        self.gen_dir = gen_dir
        with open(os.path.join(gen_dir, "tcnn.json")) as f:
            d = json.load(f)
        self.layers = d["layers"]
        self.head = d["head"]
        self.gap = d["gap"]

        self.weights, self.biases, self.mults, self.shifts = [], [], [], []
        for li, l in enumerate(self.layers):
            cout, npass, par = l["out_ch"], l["npass"], l["cin_par"]
            w = _unpack_weight_rom(os.path.join(gen_dir, f"w_L{li}.hex"), cout, npass, par)
            b = _load_u32_hex(os.path.join(gen_dir, f"b_L{li}.hex"), cout)
            m = _load_u32_hex(os.path.join(gen_dir, f"m_L{li}.hex"), cout)
            s = _load_u32_hex(os.path.join(gen_dir, f"s_L{li}.hex"), cout)
            self.weights.append(w)
            self.biases.append(b)
            self.mults.append(m)
            self.shifts.append(s)

        cin2, cout2 = self.head["in_ch"], self.head["out_ch"]
        with open(os.path.join(gen_dir, "hw.hex")) as f:
            flat = [int(x.strip(), 16) for x in f if x.strip()]
        flat = [v - 16 if v >= 8 else v for v in flat]
        assert len(flat) == cout2 * cin2
        self.head_w = np.array(flat, dtype=np.int32).reshape(cout2, cin2)
        self.head_b = _load_u32_hex(os.path.join(gen_dir, "hb.hex"), cout2)

    def conv_layer(self, x_hwc: np.ndarray, li: int) -> np.ndarray:
        """x_hwc: [H,W,Cin] uint8. Returns [OH,OW,Cout] uint8."""
        l = self.layers[li]
        cin, cout = l["in_ch"], l["out_ch"]
        stride, pad = l["stride"], l["pad"]
        out_zp = l["out_zp"]
        h, w, c = x_hwc.shape
        assert c == cin, (li, c, cin)
        oh = (h + 2 * pad - 3) // stride + 1
        ow = (w + 2 * pad - 3) // stride + 1
        assert oh == l["out_hw"] and ow == l["out_hw"]

        xp = np.zeros((h + 2 * pad, w + 2 * pad, cin), dtype=np.int32)  # in_zp==0
        xp[pad:pad + h, pad:pad + w, :] = x_hwc.astype(np.int32)

        out = np.empty((oh, ow, cout), dtype=np.uint8)
        wt = self.weights[li]  # [cout][cin][3][3]
        bias = self.biases[li]
        acc = np.zeros((oh, ow, cout), dtype=np.int64)
        for kh in range(3):
            for kw in range(3):
                patch = xp[kh: kh + stride * oh: stride, kw: kw + stride * ow: stride, :]
                acc += patch.astype(np.int64) @ wt[:, :, kh, kw].T.astype(np.int64)
        acc += bias[None, None, :]

        for oc in range(cout):
            out[:, :, oc] = requant(acc[:, :, oc], int(self.mults[li][oc]),
                                     int(self.shifts[li][oc]), out_zp)
        return out

    def gap_and_head(self, feat_hwc: np.ndarray) -> np.ndarray:
        """feat_hwc: [OH,OW,Cout] uint8 of the last conv layer. Returns [2] uint8
        logit codes."""
        n_spatial = self.gap["n_spatial"]
        assert feat_hwc.shape[0] * feat_hwc.shape[1] == n_spatial
        ssum = feat_hwc.astype(np.int64).sum(axis=(0, 1))  # [Cout]
        view = requant(ssum, self.gap["mult"], self.gap["shift"], self.gap["out_zp"])

        in_zp = self.head["in_zp"]
        acc = self.head_b.copy()
        acc += (view.astype(np.int64) - in_zp) @ self.head_w.T.astype(np.int64)
        out_zp = self.head["out_zp"]
        mults, shifts = self.head["mults"], self.head["shifts"]
        cout = self.head["out_ch"]
        res = np.empty(cout, dtype=np.uint8)
        for oc in range(cout):
            res[oc] = requant(np.array([acc[oc]]), mults[oc], shifts[oc], out_zp)[0]
        return res, view

    def run(self, patch_hwc_u8: np.ndarray, dump: bool = False):
        """patch_hwc_u8: [16,16,3] uint8 RGB. Returns uint8 logit codes [2],
        or (logits, layer_dumps, view) if dump=True."""
        x = patch_hwc_u8
        dumps = []
        for li in range(len(self.layers)):
            x = self.conv_layer(x, li)
            if dump:
                dumps.append(x.copy())
        logits, view = self.gap_and_head(x)
        if dump:
            return logits, dumps, view
        return logits

    def run_batch(self, patches_hwc_u8: np.ndarray) -> np.ndarray:
        return np.stack([self.run(p) for p in patches_hwc_u8])


if __name__ == "__main__":
    m = IntModel(gen_dir="gen")
    rng = np.random.default_rng(0)
    patch = rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
    print("random patch logit codes:", m.run(patch))
