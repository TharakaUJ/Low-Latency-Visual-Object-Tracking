#!/usr/bin/env python3
"""P3 speed test: send an OTB sequence to the board at increasing frame rates (C sender speed_send,
fps 0 = line rate) and check every tracked result against the bit-exact host model.

  python3 speed3.py --tracker s3x8 --crop server --out ../results/speed_s3x8_server
  python3 speed3.py --tracker s3x8 --crop fpga   --out ../results/speed_s3x8_fpga
The loaded bitstream must match --tracker. The sequence is cycled to fill each rate step.

Checks per tracked result (each result is checked on its own, so dropped frames do not shift the rest):
  server crop: the ROI crops are cut along the model's own track; FPGA score/good/position = model.
  fpga crop:   the model runs on the ROI at the origin the FPGA reports (score/good/position = model),
               and that origin = the RTL rule applied to the previous result (checked when the previous
               frame has a complete tracked result).
Maximum sustained rate = highest step with every frame complete, tracked and FPGA = model.
"""
import argparse, csv, os, struct, subprocess, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np

import otb_src
from board_link3 import BoardLink3, FCLK, RES, FIELDS, F_COMPLETE, F_GOOD, F_TRACKED, F_TIMEOUT, M_FRAME
from trackers import make_model, Track, pad_to

HERE = os.path.dirname(os.path.abspath(__file__))
RATES = "30,60,120,250,500,750,900,1000,1050,1100,1150,1200,1500,2000,3000,0"


def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")


_M = None


def _init(tracker, tmpl):
    global _M
    _M = make_model(tracker)
    _M.set_template(tmpl)


def _match(roi):
    return _M.match(roi)


def build_exe():
    exe = os.path.join(HERE, "speed_send")
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(exe + ".c"):
        subprocess.run(["gcc", "-O2", "-pthread", "-o", exe, exe + ".c"], check=True)
    return exe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["zsad", "s3x8"], default="s3x8")
    ap.add_argument("--crop", choices=["fpga", "server"], default="server")
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--rates", default=RATES, help="frames/s per step, 0 = line rate")
    ap.add_argument("--seconds", type=float, default=3.0, help="per step (at least --min-frames)")
    ap.add_argument("--min-frames", type=int, default=300)
    ap.add_argument("--max-frames", type=int, default=6000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ip", default="10.8.100.230")
    ap.add_argument("--keep", action="store_true", help="keep sends/results .bin per step (debug)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    exe = build_exe()

    model = make_model(a.tracker)
    d = otb_src.load(a.seq, a.target_px)
    g0 = d["gt"][0]
    c0 = (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2)
    tr = Track(model, d["frames"][0], c0)
    tmpl, t0x, t0y = tr.tmpl, tr.tx, tr.ty
    seq = [pad_to(f, model.ROI) for f in d["frames"][1:]]
    pool = ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.tracker, tmpl))

    if a.crop == "server":
        # ROI crops along the model's own track, with the expected result of each
        crops, exp = [], []
        for f in seq:
            _, o, roi = tr.crop(f)
            bx, by, z, good = model.match(roi)
            crops.append(roi)
            exp.append((bx, by, z, good))
            tr.update(o, bx, by, good)
        src = crops
    else:
        src = seq
    H, W = src[0].shape
    print(f"{a.tracker} crop {a.crop}: {a.seq} {len(src)} frames of {W}x{H} ({W * H} B, {H} rows)")

    link = BoardLink3(a.ip)
    cache = {}                      # fpga crop: (frame index, ox, oy) -> model result
    steps, fid0 = [], 0x20000000
    for rate in [float(r) for r in a.rates.split(",")]:
        n = int(min(a.max_frames, max(a.min_frames, a.seconds * rate if rate > 0 else a.max_frames)))
        idx = [k % len(src) for k in range(n)]
        fbin = os.path.join(a.out, "frames.bin")
        np.stack([src[k] for k in idx]).astype(np.uint8).tofile(fbin)
        link.drain()
        assert link.send_template(tmpl), "template not acknowledged (bitstream for this tracker loaded?)"
        assert link.set_position(t0x, t0y), "position not acknowledged"
        link.drain(0.02)
        sb, rb = os.path.join(a.out, "sends.bin"), os.path.join(a.out, "results.bin")
        p = subprocess.run([exe, a.ip, "1234", fbin, str(n), str(H), str(W), str(rate), str(fid0), sb, rb],
                           capture_output=True, text=True)
        print(p.stderr.strip())
        snd = np.fromfile(sb, dtype=np.uint8).reshape(-1, 24)
        sends = {struct.unpack_from("<I", r)[0]: struct.unpack_from("<qq", r, 8) for r in map(bytes, snd)}
        res = {}
        for r in map(bytes, np.fromfile(rb, dtype=np.uint8).reshape(-1, 56)):
            v = dict(zip(FIELDS, RES.unpack_from(r)))
            v["t_recv"], = struct.unpack_from("<q", r, 48)
            if v["magic"] == M_FRAME:
                res[v["frame_id"]] = v

        # model results for every tracked frame
        def is_tr(v):
            return v is not None and (v["flags"] & F_TRACKED) and (v["flags"] & F_COMPLETE)
        todo = {}
        for k in range(n):
            v = res.get(fid0 + k)
            if is_tr(v) and a.crop == "fpga":
                key = (idx[k], v["roi_x"], v["roi_y"])
                if key not in cache and key not in todo:
                    todo[key] = np.ascontiguousarray(
                        src[idx[k]][v["roi_y"]:v["roi_y"] + model.ROI, v["roi_x"]:v["roi_x"] + model.ROI])
        for key, r in zip(todo, pool.map(_match, todo.values(), chunksize=8)):
            cache[key] = r

        st = dict(rate=rate, frames=n, results=len(res), complete=0, incomplete=0, tracked=0, timeouts=0,
                  agree=0, origin_checked=0, origin_ok=0)
        after, total, rx, rtt, mism = [], [], [], [], []
        for k in range(n):
            v = res.get(fid0 + k)
            if v is None:
                continue
            st["complete"] += bool(v["flags"] & F_COMPLETE)
            st["incomplete"] += not (v["flags"] & F_COMPLETE)
            st["timeouts"] += bool(v["flags"] & F_TIMEOUT)
            if not is_tr(v):
                continue
            st["tracked"] += 1
            if a.crop == "server":
                bx, by, z, good = exp[idx[k]]
                ok = v["score"] == z and bool(v["flags"] & F_GOOD) == good and \
                    (not good or (v["x"], v["y"]) == (bx + model.MARGIN, by + model.MARGIN))
            else:
                bx, by, z, good = cache[(idx[k], v["roi_x"], v["roi_y"])]
                ok = v["score"] == z and bool(v["flags"] & F_GOOD) == good and \
                    (not good or (v["x"], v["y"]) == (v["roi_x"] + bx + model.MARGIN, v["roi_y"] + by + model.MARGIN))
                pv = res.get(fid0 + k - 1) if k > 0 else None
                if k == 0 or is_tr(pv):
                    tx, ty = (t0x, t0y) if k == 0 else (pv["x"], pv["y"])
                    off = (model.ROI - 16) // 2
                    eo = (int(np.clip(tx - off, 0, W - model.ROI)), int(np.clip(ty - off, 0, H - model.ROI)))
                    st["origin_checked"] += 1
                    st["origin_ok"] += eo == (v["roi_x"], v["roi_y"])
            st["agree"] += ok
            if not ok and len(mism) < 5:
                mism.append(k)
            rx.append(((v["t_rx_end"] - v["t_rx_start"]) & 0xFFFFFFFF) / FCLK * 1e6)
            after.append(((v["t_result"] - v["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6)
            total.append(((v["t_result"] - v["t_rx_start"]) & 0xFFFFFFFF) / FCLK * 1e6)
            if fid0 + k in sends:
                rtt.append((v["t_recv"] - sends[fid0 + k][1]) / 1e3)
        ts = list(sends.values())
        dur = (max(t for _, t in ts) - min(t for t, _ in ts)) / 1e9 if len(ts) > 1 else float("nan")
        st.update(send_fps=n / dur, tracked_fps=st["tracked"] / dur,
                  rx_us_p50=q(rx, 50), after_us_p50=q(after, 50), after_us_p99=q(after, 99), after_us_max=max(after, default=float("nan")),
                  total_us_p50=q(total, 50), total_us_max=max(total, default=float("nan")),
                  rtt_us_p50=q(rtt, 50), rtt_us_p99=q(rtt, 99),
                  clean=int(st["results"] == n and st["tracked"] == n and st["agree"] == n and st["origin_ok"] == st["origin_checked"]),
                  first_mismatch_frames=" ".join(map(str, mism)))
        steps.append(st)
        print(f"rate {'line' if rate == 0 else int(rate)}: sent {st['send_fps']:.0f}/s, results {st['results']}/{n}, "
              f"tracked {st['tracked']}, FPGA=model {st['agree']}/{st['tracked']}, origin {st['origin_ok']}/{st['origin_checked']}, "
              f"incomplete {st['incomplete']}, timeouts {st['timeouts']}, after last row p50 {st['after_us_p50']:.0f} us, "
              f"rtt p50 {st['rtt_us_p50']:.0f} us{'  CLEAN' if st['clean'] else ''}")
        if a.keep:
            for f in ("sends", "results"):
                os.replace(os.path.join(a.out, f + ".bin"), os.path.join(a.out, f"{f}_{int(rate)}.bin"))
            np.save(os.path.join(a.out, f"idx_{int(rate)}.npy"), np.array(idx))
        fid0 += 0x00100000
    for f in ("frames.bin", "sends.bin", "results.bin"):
        if os.path.exists(os.path.join(a.out, f)):
            os.remove(os.path.join(a.out, f))

    with open(os.path.join(a.out, "steps.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(steps[0]))
        w.writeheader()
        w.writerows(steps)
    clean = [s for s in steps if s["clean"]]
    best = max(clean, key=lambda s: s["send_fps"]) if clean else None
    sent = "whole scaled frame" if a.crop == "fpga" else f"{model.ROI}x{model.ROI} ROI"
    lines = [f"# P3 speed test: {a.tracker}, crop {a.crop}, {a.seq} ({sent}, {W}x{H})", "",
             f"command: `python3 speed3.py --tracker {a.tracker} --crop {a.crop} --seq {a.seq} --rates {a.rates} "
             f"--seconds {a.seconds:g} --min-frames {a.min_frames} --max-frames {a.max_frames} --out {a.out}`", "",
             f"**Maximum clean rate: {best['send_fps']:.0f} frames/s** (every frame complete, tracked, FPGA = model)" if best
             else "**No clean step.**", "",
             "| target fps | sent fps | frames | results | tracked | FPGA = model | origin ok | incomplete | timeouts | tracked/s | "
             "FPGA rows in (us) | FPGA last row -> result p50/p99/max (us) | round trip p50/p99 (us) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in steps:
        lines.append(f"| {'line' if s['rate'] == 0 else int(s['rate'])} | {s['send_fps']:.0f} | {s['frames']} | {s['results']} | "
                     f"{s['tracked']} | {s['agree']}/{s['tracked']} | "
                     f"{'-' if a.crop == 'server' else str(s['origin_ok']) + '/' + str(s['origin_checked'])} | "
                     f"{s['incomplete']} | {s['timeouts']} | {s['tracked_fps']:.0f} | {s['rx_us_p50']:.0f} | "
                     f"{s['after_us_p50']:.0f} / {s['after_us_p99']:.0f} / {s['after_us_max']:.0f} | {s['rtt_us_p50']:.0f} / {s['rtt_us_p99']:.0f} |")
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))

    plot(a.out, a.tracker, a.crop)


PLOT_PY = os.path.expanduser("~/Documents/Object_tracking_test/object_tracking/.venv/bin/python")


def plot(out, tracker, crop):
    """speed.png from steps.csv (the system matplotlib is broken on the server: then use the research venv)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except (ImportError, AttributeError):
        subprocess.run([PLOT_PY, os.path.abspath(__file__), "--plot-only", out, tracker, crop], check=True)
        return
    steps = [{k: float(v) if k != "first_mismatch_frames" else v for k, v in r.items()}
             for r in csv.DictReader(open(os.path.join(out, "steps.csv")))]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    x = [s["send_fps"] for s in steps]
    ax[0].plot(x, x, "k:", label="sent")
    ax[0].plot(x, [s["tracked_fps"] for s in steps], "o-", label="tracked")
    ax[0].plot(x, [s["agree"] / max(1, s["frames"]) * s["send_fps"] for s in steps], "x--", label="tracked and FPGA = model")
    ax[0].set(xlabel="sent frames/s", ylabel="results/s", xscale="log", title=f"{tracker} crop {crop}: throughput")
    ax[0].legend()
    ax[1].plot(x, [s["after_us_p50"] for s in steps], "o-", label="FPGA last row -> result p50")
    ax[1].plot(x, [s["total_us_p50"] for s in steps], "s-", label="FPGA first row -> result p50")
    ax[1].plot(x, [s["rtt_us_p50"] for s in steps], "^-", label="round trip p50")
    ax[1].set(xlabel="sent frames/s", ylabel="us", xscale="log", title="latency (tracked frames)")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "speed.png"), dpi=110)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 5 and sys.argv[1] == "--plot-only":
        plot(*sys.argv[2:])
    else:
        main()
