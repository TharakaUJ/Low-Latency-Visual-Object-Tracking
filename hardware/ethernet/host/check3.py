#!/usr/bin/env python3
"""P3 board check: track an OTB sequence through the board with either tracker build and either crop
mode, and compare every frame with the bit-exact host model (host/trackers.py).

  python3 check3.py --tracker zsad --crop fpga --seq Walking --frames 0 --out results/p3_check_zsad_fpga_Walking
  python3 check3.py --tracker s3x8 --crop server --seq Walking ...
The loaded bitstream must match --tracker (make program-zsad / program-s3x8).
FPGA = model: same ROI origin, same score, same good flag and the same new position.
"""
import argparse, csv, os, time
import numpy as np

import otb_src
from board_link3 import BoardLink3, FCLK, F_COMPLETE, F_GOOD, F_TRACKED
from trackers import make_model, Track, pad_to


def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["zsad", "s3x8"], default="zsad")
    ap.add_argument("--crop", choices=["fpga", "server"], default="fpga")
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--frames", type=int, default=50, help="frames after the init frame (0 = all)")
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--ip", default="10.8.100.230")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    d = otb_src.load(a.seq, a.target_px)
    model = make_model(a.tracker)
    g0 = d["gt"][0]
    tr = Track(model, d["frames"][0], (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2))
    link = BoardLink3(a.ip)
    link.drain()
    assert link.send_template(tr.tmpl), "template not acknowledged (bitstream for this tracker loaded?)"
    assert link.set_position(tr.tx, tr.ty), "position not acknowledged"

    n = len(d["frames"]) - 1 if a.frames == 0 else min(a.frames, len(d["frames"]) - 1)
    rows, pred = [], [tr.center()]
    agree = lost = 0
    fpga_us, rtt_us = [], []
    t_start = time.perf_counter()
    for i in range(1, n + 1):
        while time.perf_counter() < t_start + (i - 1) / a.fps:
            time.sleep(0.0005)
        fp, o, roi = tr.crop(d["frames"][i])
        bx, by, z, good = model.match(roi)
        send = fp if a.crop == "fpga" else roi
        res, t0, t1 = link.track(i, send)
        old = (tr.tx, tr.ty)
        tr.update(o, bx, by, good)
        if res is None:
            lost += 1
            pred.append(tr.center())
            rows.append([i, o[0], o[1], "", "", "", "", tr.tx, tr.ty, z, int(good), 0, "", ""])
            continue
        if a.crop == "fpga":
            exp_o, exp_xy = o, (tr.tx, tr.ty)
        else:
            exp_o = (0, 0)
            exp_xy = (bx + model.MARGIN, by + model.MARGIN) if good else (res["x"], res["y"])
        tracked = bool(res["flags"] & F_TRACKED) and bool(res["flags"] & F_COMPLETE)
        ok = tracked and (res["roi_x"], res["roi_y"]) == exp_o and res["score"] == z and \
            bool(res["flags"] & F_GOOD) == good and (res["x"], res["y"]) == exp_xy
        agree += ok
        pred.append(tr.center())
        f_us = ((res["t_result"] - res["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6
        rt = (res["t_recv_ns"] - t1) / 1e3
        fpga_us.append(f_us)
        rtt_us.append(rt)
        rows.append([i, o[0], o[1], res["roi_x"], res["roi_y"], res["x"], res["y"], tr.tx, tr.ty, z,
                     int(good), int(ok), round(f_us, 2), round(rt, 1)])

    with open(os.path.join(a.out, "frames.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "model_roi_x", "model_roi_y", "fpga_roi_x", "fpga_roi_y", "fpga_x", "fpga_y",
                    "model_x", "model_y", "model_score", "model_good", "agree", "fpga_after_last_row_us", "rtt_us"])
        w.writerows(rows)
    pred = np.array(pred)
    gt_c = d["gt"][:n + 1, :2] + d["gt"][:n + 1, 2:] / 2
    m = otb_src.metrics.compute(pred, gt_c, d["scale"])
    sent = "whole scaled frame" if a.crop == "fpga" else f"{model.ROI}x{model.ROI} ROI"
    lines = [f"# P3 board check: {a.tracker}, crop {a.crop}, {a.seq}, {n} frames", "",
             f"command: `python3 check3.py --tracker {a.tracker} --crop {a.crop} --seq {a.seq} --frames {a.frames} "
             f"--target-px {a.target_px:g} --fps {a.fps:g} --out {a.out}`", "",
             "| metric | value |", "|---|---|",
             f"| sent per frame | {sent} ({d['frames'][0].shape[1]}x{d['frames'][0].shape[0]} scaled) |",
             f"| frames | {n} (no result: {lost}) |",
             f"| FPGA = model | {agree}/{n} |",
             f"| FPGA: last row in -> result (us) | p50 {q(fpga_us,50):.1f}, max {max(fpga_us) if fpga_us else float('nan'):.1f} |",
             f"| round trip, last row sent -> result (us) | p50 {q(rtt_us,50):.0f}, p99 {q(rtt_us,99):.0f} |",
             f"| P@20 (information only) | {m['prec20']:.1f} |"]
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
