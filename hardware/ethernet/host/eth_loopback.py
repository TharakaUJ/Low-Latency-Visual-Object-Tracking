#!/usr/bin/env python3
"""P1 Ethernet loopback test for the DE2-115 row protocol (hardware/ethernet/p1_rows).

Sends grayscale frames as one UDP packet per row, receives one result packet per frame,
and checks rows and pixel checksums. Writes frames.csv and summary.md into --out.

  python3 eth_loopback.py --fps 30 --frames 10000 --out results/fps30
  python3 eth_loopback.py --fps 0  --frames 10000 --out results/max     (fps 0 = as fast as possible)
"""
import argparse, csv, os, socket, struct, sys, threading, time
import numpy as np

MAGIC_DN, MAGIC_UP = 0x5AA5, 0x3CC3
SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)   # Linux x86-64 value
HDR = struct.Struct("<HIHHH")                        # magic, frame_id, row, width, height
RES = struct.Struct("<HHIHHHHIIIIhhI")               # 40 bytes, see rtl/row_stats.v
FCLK = 125e6


def make_frames(n, w, h, pattern, seed):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        if pattern == "ramp":
            f = ((np.arange(w)[None, :] + 3 * np.arange(h)[:, None] + 17 * k) & 0xFF).astype(np.uint8)
        else:
            f = rng.integers(0, 256, (h, w), dtype=np.uint8)
        out.append(f)
    return out


def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="10.8.100.230")
    ap.add_argument("--port", type=int, default=1234)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--pattern", choices=["random", "ramp"], default="random")
    ap.add_argument("--pool", type=int, default=16, help="distinct frames, cycled")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--wait", type=float, default=1.0, help="s to wait for late results")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    frames = make_frames(a.pool, a.width, a.height, a.pattern, a.seed)
    sums = [int(f.astype(np.uint64).sum()) & 0xFFFFFFFF for f in frames]
    pkts = [[HDR.pack(MAGIC_DN, 0, r, a.width, a.height) + f[r].tobytes() for r in range(a.height)]
            for f in frames]

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
    s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)   # kernel RX time (CLOCK_REALTIME)
    s.bind(("", 0))
    sys.setswitchinterval(0.0005)
    s.settimeout(0.2)
    dst = (a.ip, a.port)

    sent = {}          # fid -> (t_first, t_last)
    recv = {}          # fid -> (t_recv, fields)
    dup = [0]
    other = [0]
    stop = threading.Event()

    def rx():
        while not stop.is_set():
            try:
                d, anc, _, _ = s.recvmsg(2048, 64)
            except socket.timeout:
                continue
            t = time.time_ns()
            for lvl, typ, data in anc:
                if lvl == socket.SOL_SOCKET and typ == SO_TIMESTAMPNS:
                    sec, nsec = struct.unpack("qq", data[:16])
                    t = sec * 1_000_000_000 + nsec
            if len(d) != RES.size or struct.unpack_from("<H", d)[0] != MAGIC_UP:
                other[0] += 1
                continue
            f = RES.unpack(d)
            if f[2] in recv:
                dup[0] += 1
            else:
                recv[f[2]] = (t, f)

    th = threading.Thread(target=rx, daemon=True)
    th.start()

    period = 1.0 / a.fps if a.fps > 0 else 0.0
    t_start = time.perf_counter()
    for fid in range(a.frames):
        if period:
            t_due = t_start + fid * period
            dt = t_due - time.perf_counter()
            if dt > 0.002:
                time.sleep(dt - 0.002)      # releases the GIL for the receiver
            while time.perf_counter() < t_due:
                pass
        rows = pkts[fid % a.pool]
        fid_b = struct.pack("<I", fid)
        t0 = time.time_ns()
        for p in rows:
            s.sendto(p[:2] + fid_b + p[6:], dst)
        sent[fid] = (t0, time.time_ns())
    t_send_end = time.perf_counter()
    time.sleep(a.wait)
    stop.set()
    th.join()

    # per-frame table
    rows_out = []
    send_t = [(sent[i][1] - sent[i][0]) / 1e3 for i in range(a.frames)]
    rtt, rtt_first, fpga_rx, fpga_res, missing_rows, bad_rows = [], [], [], [], 0, 0
    lost = incomplete = cks_bad = 0
    for fid in range(a.frames):
        t0, t1 = sent[fid]
        if fid not in recv:
            lost += 1
            rows_out.append([fid, t0, t1, "", "", "", "", "", "", "", "", ""])
            continue
        tr, f = recv[fid]
        _, flags, _, nrows, nbad, h, w, cks, ta, tb, tc, x, y, score = f
        ok = int(cks == sums[fid % a.pool] and nrows == a.height)
        incomplete += int(nrows != a.height)
        cks_bad += int(cks != sums[fid % a.pool])
        missing_rows += a.height - nrows
        bad_rows += nbad
        rtt.append((tr - t1) / 1e3)
        rtt_first.append((tr - t0) / 1e3)
        fpga_rx.append(((tb - ta) & 0xFFFFFFFF) / FCLK * 1e6)
        fpga_res.append(((tc - tb) & 0xFFFFFFFF) / FCLK * 1e6)
        rows_out.append([fid, t0, t1, tr, flags, nrows, nbad, cks, sums[fid % a.pool], ok,
                         (tb - ta) & 0xFFFFFFFF, (tc - tb) & 0xFFFFFFFF])
    with open(os.path.join(a.out, "frames.csv"), "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["frame_id", "t_send_first", "t_send_last", "t_recv", "flags", "rows_seen",
                     "rows_bad", "cks_fpga", "cks_host", "ok", "fpga_rx_cycles", "fpga_res_cycles"])
        wr.writerows(rows_out)

    # rate over the frame starts (N-1 intervals), not including the last frame's send time
    dur = (sent[a.frames - 1][0] - sent[0][0]) / 1e9 if a.frames > 1 else float("nan")
    rate = (a.frames - 1) / dur if a.frames > 1 else float("nan")
    payload_bits = a.frames * a.height * a.width * 8
    wire_bits = a.frames * a.height * (a.width + HDR.size + 8 + 20 + 14 + 4 + 8 + 12) * 8
    lines = [
        f"# P1 loopback: {a.frames} frames {a.width}x{a.height} {a.pattern}, fps target "
        f"{'max' if not period else a.fps}",
        "",
        f"command: `python3 eth_loopback.py {' '.join(f'--{k} {v}' for k, v in vars(a).items())}`",
        "",
        "| metric | value |", "|---|---|",
        f"| frames sent | {a.frames} |",
        f"| results received | {len(recv)} (lost {lost}, duplicate {dup[0]}, other packets {other[0]}) |",
        f"| frames OK (all rows + checksum) | {sum(1 for r in rows_out if r[9] == 1)} |",
        f"| incomplete frames | {incomplete} (missing rows total {missing_rows}) |",
        f"| bad rows reported by FPGA | {bad_rows} |",
        f"| checksum mismatches | {cks_bad} |",
        f"| achieved frame rate | {rate:.1f} fps over {dur:.2f} s |",
        f"| pixel throughput | {payload_bits / a.frames * rate / 1e6:.1f} Mbit/s (on the wire ~{wire_bits / a.frames * rate / 1e6:.1f}) |",
        f"| host send time per frame (us) | p50 {q(send_t,50):.0f}, p99 {q(send_t,99):.0f} |",
        f"| RTT last row sent -> result (us) | p50 {q(rtt,50):.0f}, p95 {q(rtt,95):.0f}, p99 {q(rtt,99):.0f}, max {max(rtt) if rtt else float('nan'):.0f} |",
        f"| first row sent -> result (us) | p50 {q(rtt_first,50):.0f}, p99 {q(rtt_first,99):.0f}, max {max(rtt_first) if rtt_first else float('nan'):.0f} |",
        f"| FPGA first row -> last row (us) | p50 {q(fpga_rx,50):.0f}, p99 {q(fpga_rx,99):.0f} |",
        f"| FPGA last row -> result (us) | p50 {q(fpga_res,50):.3f}, max {max(fpga_res) if fpga_res else float('nan'):.3f} (P1 has no compute) |",
        "",
        "Times: host send/receive stamps are CLOCK_REALTIME ns (receive = kernel SO_TIMESTAMPNS); FPGA times are its 125 MHz counter.",
    ]
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
