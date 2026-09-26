#!/usr/bin/env python3
"""
check_agreement.py — Gate P0: compare int_model.py (bit-exact, built from the
packed gen/ ROMs) against onnxruntime running the real QDQ graph, on a mix of
random and real-image patches. See docs/implementation_plan.md Phase 0.

Usage:
    python3 ref/check_agreement.py [--n-random 5000] [--n-crops 5000] \
        [--out results/P0/agreement.txt]

Pass criterion: logits within +/-1 LSB on >=99.5% of patches, argmax
agreement >=99.5%.
"""
import argparse
import os
import sys

import numpy as np
import onnx
import onnxruntime as ort
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from int_model import IntModel  # noqa: E402


class OrtRef:
    """Runs the real tinycnn_qat_int4.onnx QDQ graph. Its 'patches' input is
    NCHW float32 normalized to [0,1] (pixel/255.0) -- see docs/implementation_plan.md
    and fpga_cnn_pipeline/ref/ort_ref.py for the same convention on the
    earlier model."""

    def __init__(self, model_path):
        self.sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name
        self.output_name = self.sess.get_outputs()[0].name

    def run_batch(self, patches_hwc_u8: np.ndarray) -> np.ndarray:
        assert patches_hwc_u8.shape[1:] == (16, 16, 3), patches_hwc_u8.shape
        x = (patches_hwc_u8.astype(np.float32) / 255.0).transpose(0, 3, 1, 2)
        (out,) = self.sess.run([self.output_name], {self.input_name: x})
        return out


def ort_logits_to_u8(raw_logits: np.ndarray, scale: float, zp: int) -> np.ndarray:
    q = np.round(raw_logits / scale) + zp  # round-half-to-even, same as QuantizeLinear
    return np.clip(q, 0, 255).astype(np.uint8)


def random_patches(n, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(n, 16, 16, 3), dtype=np.uint8)


def crop_patches(image_paths, n, seed=1):
    rng = np.random.default_rng(seed)
    patches = []
    for i in range(n):
        path = image_paths[i % len(image_paths)]
        img = np.asarray(Image.open(path).convert("RGB"))
        h, w, _ = img.shape
        r = rng.integers(0, h - 16 + 1)
        c = rng.integers(0, w - 16 + 1)
        patches.append(img[r:r + 16, c:c + 16, :])
    return np.stack(patches)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tinycnn_qat_int4.onnx")
    ap.add_argument("--gen-dir", default="gen")
    ap.add_argument("--n-random", type=int, default=5000)
    ap.add_argument("--n-crops", type=int, default=5000)
    ap.add_argument("--images", nargs="*",
                     default=["002675.jpg", "002683.jpg"])
    ap.add_argument("--out", default="results/P0/agreement.txt")
    args = ap.parse_args()

    m = onnx.load(args.model)
    inits = {i.name: onnx.numpy_helper.to_array(i) for i in m.graph.initializer}
    logits_scale = float(inits["logits_scale"])
    logits_zp = int(inits["logits_zero_point"])

    ort_ref = OrtRef(args.model)
    im = IntModel(gen_dir=args.gen_dir)

    patches = np.concatenate([
        random_patches(args.n_random),
        crop_patches(args.images, args.n_crops),
    ])

    ort_raw = ort_ref.run_batch(patches)
    ort_u8 = ort_logits_to_u8(ort_raw, logits_scale, logits_zp)
    int_u8 = im.run_batch(patches)

    diff = np.abs(int_u8.astype(int) - ort_u8.astype(int))
    within_1lsb = (diff <= 1).all(axis=1)
    argmax_ort = ort_u8.argmax(axis=1)
    argmax_int = int_u8.argmax(axis=1)
    argmax_agree = argmax_ort == argmax_int

    n = len(patches)
    pct_1lsb = 100.0 * within_1lsb.sum() / n
    pct_argmax = 100.0 * argmax_agree.sum() / n
    max_diff = int(diff.max())

    lines = []
    lines.append(f"patches: {n} ({args.n_random} random + {args.n_crops} crops from {args.images})")
    lines.append(f"within +/-1 LSB: {pct_1lsb:.2f}%  (gate: >=99.5%)")
    lines.append(f"argmax agreement: {pct_argmax:.2f}%  (gate: >=99.5%)")
    lines.append(f"max |diff| (logit code): {max_diff}")
    n_show = min(10, (~within_1lsb).sum())
    if n_show:
        lines.append(f"\nfirst {n_show} mismatches (idx, ort_u8, int_u8):")
        idxs = np.where(~within_1lsb)[0][:n_show]
        for i in idxs:
            lines.append(f"  {i}: ort={ort_u8[i].tolist()} int={int_u8[i].tolist()}")

    report = "\n".join(lines)
    print(report)

    gate_pass = pct_1lsb >= 99.5 and pct_argmax >= 99.5
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(report + "\n")
        f.write(f"\nGATE P0: {'PASS' if gate_pass else 'FAIL'}\n")
    print(f"\nGATE P0: {'PASS' if gate_pass else 'FAIL'}")
    print(f"report written to {args.out}")
    sys.exit(0 if gate_pass else 1)


if __name__ == "__main__":
    main()
