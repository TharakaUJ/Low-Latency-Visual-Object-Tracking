#!/usr/bin/env python3
"""P2 line-rate stress test: real 80x80 crops of an OTB sequence (taken along the model's own track),
sent at line rate by the C helper burst_send (one sendmmsg per frame). Checks every result against
the bit-exact model and reports the tracker time when rows arrive at line rate.

  python3 p2_stress.py --mode inflight --frames 5000 --out results/p2_stress_inflight
  python3 p2_stress.py --mode burst    --frames 2000 --out results/p2_stress_burst
"""
import argparse, os, struct, subprocess
import numpy as np

import otb_src
from board_link import BoardLink, FCLK, F_COMPLETE, F_GOOD, F_TRACKED, FIELDS, RES
from zsad_model import ZsadTracker, match, SCORE_SAT

HERE = os.path.dirname(os.path.abspath(__file__))


def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--mode", choices=["inflight", "burst"], default="inflight")
    ap.add_argument("--frames", type=int, default=5000)
    ap.add_argument("--roi", type=int, default=80)
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--ip", default="10.8.100.230")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    exe = os.path.join(HERE, "burst_send")
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(exe + ".c"):
        subprocess.run(["gcc", "-O2", "-o", exe, exe + ".c"], check=True)

    # crops along the model's own track (cycled to the requested count)
    d = otb_src.load(a.seq, a.target_px)
    g0 = d["gt"][0]
    tr = ZsadTracker(d["frames"][0], (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2), a.roi)
    crops, exp = [], []
    for f in d["frames"][1:]:
        rx, ry, c = tr.crop(f)
        x, y, z, good = match(c, tr.tmpl)
        crops.append(c)
        exp.append((x, y, min(z, SCORE_SAT), good))
        tr.update(rx, ry, x, y, good)
    idx = [k % len(crops) for k in range(a.frames)]
    fbin = os.path.join(a.out, "frames.bin")
    np.stack([crops[k] for k in idx]).astype(np.uint8).tofile(fbin)

    link = BoardLink(a.ip)
    link.drain()
    assert link.send_template(tr.tmpl), "template ack missing"
    del link

    fid0 = 0x10000000
    obin = os.path.join(a.out, "log.bin")
    p = subprocess.run([exe, a.ip, "1234", fbin, str(a.frames), str(a.roi),
                        "0" if a.mode == "inflight" else "1", str(fid0), obin],
                       capture_output=True, text=True)
    print(p.stderr.strip())

    raw = np.fromfile(obin, dtype=np.uint8).reshape(-1, 56)
    sends, res = {}, {}
    for r in raw:
        b = r.tobytes()
        if b[0:1] == b"S":
            fid, = struct.unpack_from("<I", b, 8)
            t0, t1 = struct.unpack_from("<qq", b, 16)
            sends[fid] = (t0, t1)
        elif b[0:1] == b"R":
            v = dict(zip(FIELDS, RES.unpack_from(b, 8)))
            v["t_recv"], = struct.unpack_from("<q", b, 48)
            if v["magic"] == 0x3CC3:
                res[v["frame_id"]] = v

    n = a.frames
    agree = tracked = complete = incomplete = timeouts = 0
    missing_rows = 0
    rx_us, after_us, total_us, rtt_us = [], [], [], []
    for k in range(n):
        fid = fid0 + k
        v = res.get(fid)
        if v is None:
            continue
        x, y, z, good = exp[idx[k]]
        is_t = bool(v["flags"] & F_TRACKED)
        complete += bool(v["flags"] & F_COMPLETE)
        incomplete += not (v["flags"] & F_COMPLETE)
        timeouts += bool(v["flags"] & 16)
        missing_rows += a.roi - v["rows_seen"]
        tracked += is_t
        if is_t:
            g = bool(v["flags"] & F_GOOD)
            agree += v["score"] == z and g == good and (not g or (v["x"], v["y"]) == (x, y))
            rx_us.append(((v["t_rx_end"] - v["t_rx_start"]) & 0xFFFFFFFF) / FCLK * 1e6)
            after_us.append(((v["t_result"] - v["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6)
            total_us.append(((v["t_result"] - v["t_rx_start"]) & 0xFFFFFFFF) / FCLK * 1e6)
            rtt_us.append((v["t_recv"] - sends[fid][1]) / 1e3)
    t_first = min(t for t, _ in sends.values())
    t_last = max(t for _, t in sends.values())
    dur = (t_last - t_first) / 1e9
    lines = [f"# P2 line-rate stress: {a.seq} crops, mode {a.mode}, {n} frames {a.roi}x{a.roi}", "",
             f"command: `python3 p2_stress.py --seq {a.seq} --mode {a.mode} --frames {n} --roi {a.roi} --out {a.out}`", "",
             "| metric | value |", "|---|---|",
             f"| frames sent / results | {n} / {len(res)} |",
             f"| complete / incomplete (rows lost) | {complete} / {incomplete} ({missing_rows} rows missing) |",
             f"| tracked | {tracked} (tracker timeouts {timeouts}) |",
             f"| FPGA = model (tracked frames) | {agree}/{tracked} |",
             f"| send rate | {n / dur:.0f} frames/s over {dur:.2f} s; tracked results/s {tracked / dur:.0f} |",
             f"| FPGA: first row -> last row in (us) | p50 {q(rx_us,50):.1f}, max {max(rx_us) if rx_us else float('nan'):.1f} |",
             f"| FPGA: last row in -> result (us) | p50 {q(after_us,50):.1f}, p99 {q(after_us,99):.1f}, max {max(after_us) if after_us else float('nan'):.1f} |",
             f"| FPGA: first row in -> result (us) | p50 {q(total_us,50):.1f}, max {max(total_us) if total_us else float('nan'):.1f} |",
             f"| round trip, last row sent -> result (us) | p50 {q(rtt_us,50):.0f}, p99 {q(rtt_us,99):.0f}, max {max(rtt_us) if rtt_us else float('nan'):.0f} |"]
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
