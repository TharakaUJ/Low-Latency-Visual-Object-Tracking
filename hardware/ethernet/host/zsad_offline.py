#!/usr/bin/env python3
"""Offline (no board) run of the P2 ZSAD demo tracker over all OTB-100 targets, to choose the demo
sequences. Same rules as the board path: bit-exact ZSAD model, fixed template, ROI R x R, hold on reject.

  python3 zsad_offline.py --roi 80 --target-px 16 --out results/p2_offline
Information only (one-pass evaluation from the GT first box; no learning, no tuning).
"""
import argparse, csv, os
from multiprocessing import Pool
import numpy as np

import otb_src
from zsad_model import ZsadTracker, match


def run(args):
    key, roi, target_px = args
    d = otb_src.load(key, target_px)
    g0 = d["gt"][0]
    tr = ZsadTracker(d["frames"][0], (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2), roi)
    pred = [tr.center()]
    rejects = 0
    for f in d["frames"][1:]:
        rx, ry, crop = tr.crop(f)
        x, y, z, good = match(crop, tr.tmpl)
        rejects += not good
        pred.append(tr.update(rx, ry, x, y, good))
    pred = np.array(pred)
    gt_c = d["gt"][:, :2] + d["gt"][:, 2:] / 2
    m = otb_src.metrics.compute(pred, gt_c, d["scale"])
    return dict(target=key, frames=len(d["frames"]), scale=round(d["scale"], 4),
                frame_w=d["frames"][0].shape[1], frame_h=d["frames"][0].shape[0],
                prec20=round(m["prec20"], 1), auc=round(otb_src.iou_auc(pred, d["gt_orig"], d["scale"]), 1),
                mean_err_orig=round(m["mean_err_orig"], 1), lost_pct=round(m["lost_pct"], 1),
                reject_pct=round(100 * rejects / max(1, len(d["frames"]) - 1), 1),
                attr=" ".join(d["attr"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roi", type=int, default=80)
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    keys = otb_src.targets()
    with Pool(a.jobs) as p:
        rows = p.map(run, [(k, a.roi, a.target_px) for k in keys])
    rows.sort(key=lambda r: -r["prec20"])
    with open(os.path.join(a.out, "per_target.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    p20 = np.array([r["prec20"] for r in rows])
    auc = np.array([r["auc"] for r in rows])
    lines = [f"# P2 offline ZSAD over OTB-100 (ROI {a.roi}, target {a.target_px:g} px, fixed template)", "",
             f"command: `python3 zsad_offline.py --roi {a.roi} --target-px {a.target_px:g} --out {a.out}`", "",
             f"{len(rows)} targets: mean P@20 {p20.mean():.1f}, median {np.median(p20):.1f}; "
             f"mean AUC (fixed box size) {auc.mean():.1f}. Information only.", "",
             "| target | frames | scaled frame | P@20 | AUC | mean err (orig px) | lost % | reject % | attributes |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['target']} | {r['frames']} | {r['frame_w']}x{r['frame_h']} | {r['prec20']} | {r['auc']} | "
                     f"{r['mean_err_orig']} | {r['lost_pct']} | {r['reject_pct']} | {r['attr']} |")
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines[:6]))


if __name__ == "__main__":
    main()
