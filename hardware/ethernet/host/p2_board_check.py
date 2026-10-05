#!/usr/bin/env python3
"""P2 board check: track an OTB sequence through the board (closed loop: the board result moves the
ROI) and compare every frame with the bit-exact Python model on the same crop.

  python3 p2_board_check.py --seq Walking --frames 50 --out results/p2_sanity_Walking
FPGA = model means: same score (min ZSAD, saturated 16 bit), same good flag, and when good the same
(x, y). When the match is rejected the FPGA repeats its last good position (template_match's hold
logic), which the host ignores, so x, y are not compared then.
"""
import argparse, csv, os, time
import numpy as np

import otb_src
from board_link import BoardLink, FCLK, F_COMPLETE, F_GOOD, F_TRACKED
from zsad_model import ZsadTracker, match, SCORE_SAT


def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--frames", type=int, default=50, help="frames after the init frame (0 = all)")
    ap.add_argument("--roi", type=int, default=80)
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--ip", default="10.8.100.230")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    d = otb_src.load(a.seq, a.target_px)
    g0 = d["gt"][0]
    tr = ZsadTracker(d["frames"][0], (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2), a.roi)
    link = BoardLink(a.ip)
    link.drain()
    assert link.send_template(tr.tmpl), "template ack missing or wrong checksum"

    n = len(d["frames"]) - 1 if a.frames == 0 else min(a.frames, len(d["frames"]) - 1)
    rows, pred = [], [tr.center()]
    agree = lost = 0
    fpga_us, rtt_us, transport_us = [], [], []
    t_start = time.perf_counter()
    for i in range(1, n + 1):
        t_due = t_start + (i - 1) / a.fps
        while time.perf_counter() < t_due:
            time.sleep(0.0005)
        rx, ry, crop = tr.crop(d["frames"][i])
        mx, my, mz, mgood = match(crop, tr.tmpl)
        res, t0, t1 = link.track(i, crop)
        if res is None:
            lost += 1
            pred.append(tr.center())
            rows.append([i, rx, ry, "", "", "", "", mx, my, min(mz, SCORE_SAT), int(mgood), 0, "", "", ""])
            continue
        tracked = bool(res["flags"] & F_TRACKED) and bool(res["flags"] & F_COMPLETE)
        good = bool(res["flags"] & F_GOOD)
        ok = tracked and res["score"] == min(mz, SCORE_SAT) and good == mgood and \
            (not good or (res["x"], res["y"]) == (mx, my))
        agree += ok
        pred.append(tr.update(rx, ry, res["x"], res["y"], good and tracked))
        f_us = ((res["t_result"] - res["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6
        rt = (res["t_recv_ns"] - t1) / 1e3
        fpga_us.append(f_us)
        rtt_us.append(rt)
        transport_us.append(rt - f_us)
        rows.append([i, rx, ry, res["x"], res["y"], res["score"], int(good), mx, my, min(mz, SCORE_SAT),
                     int(mgood), int(ok), round(f_us, 2), round(rt, 1), res["flags"]])

    with open(os.path.join(a.out, "frames.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "roi_x", "roi_y", "fpga_x", "fpga_y", "fpga_score", "fpga_good", "model_x",
                    "model_y", "model_score", "model_good", "agree", "fpga_compute_us", "rtt_us", "flags"])
        w.writerows(rows)
    pred = np.array(pred)
    gt_c = d["gt"][:n + 1, :2] + d["gt"][:n + 1, 2:] / 2
    m = otb_src.metrics.compute(pred, gt_c, d["scale"])
    lines = [f"# P2 board check: {a.seq}, {n} frames, ROI {a.roi}, target {a.target_px:g} px, {a.fps:g} fps", "",
             f"command: `python3 p2_board_check.py --seq {a.seq} --frames {a.frames} --roi {a.roi} "
             f"--target-px {a.target_px:g} --fps {a.fps:g} --out {a.out}`", "",
             "| metric | value |", "|---|---|",
             f"| frames | {n} (no result: {lost}) |",
             f"| FPGA = model | {agree}/{n} |",
             f"| rejected matches (hold) | {sum(1 for r in rows if r[6] == 0)} |",
             f"| FPGA compute, last row in -> result (us) | p50 {q(fpga_us,50):.1f}, max {max(fpga_us) if fpga_us else float('nan'):.1f} |",
             f"| round trip, last row sent -> result (us) | p50 {q(rtt_us,50):.0f}, p99 {q(rtt_us,99):.0f}, max {max(rtt_us) if rtt_us else float('nan'):.0f} |",
             f"| transport = round trip - FPGA compute (us) | p50 {q(transport_us,50):.0f} |",
             f"| P@20 over these frames (information only) | {m['prec20']:.1f} |",
             "", "Scaling and ROI crop run on the server; the FPGA runs the existing ZSAD matcher on the 80x80 ROI."]
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
