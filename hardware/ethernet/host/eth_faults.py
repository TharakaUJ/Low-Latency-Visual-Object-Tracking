#!/usr/bin/env python3
"""Fault injection on the board: send host/fault_cases.py over UDP, compare with row_model.py.

  python3 eth_faults.py --out results/faults
Cases marked testbench-only (bad Ethernet FCS) are skipped: a normal socket cannot send them.
"""
import argparse, os, socket, time
from fault_cases import build_cases, expected
from row_model import CHECKED, PORT, RES, parse_result, row_packet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="10.8.100.230")
    ap.add_argument("--gap-us", type=float, default=20.0, help="pause between packets")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    s.bind(("", 0))
    s.settimeout(0.05)

    def drain(t=0.3):
        got, t_end = [], time.time() + t
        while time.time() < t_end:
            try:
                d, _ = s.recvfrom(2048)
                if len(d) == RES.size:
                    got.append(parse_result(d))
            except socket.timeout:
                pass
        return got

    # warm-up: closes any frame the board still has open, then a 1-row frame of our own
    s.sendto(row_packet(0xEEEEEEEE, 0, 4, 1, b"\0\0\0\0"), (a.ip, PORT))
    warm = drain()
    assert warm and warm[-1]["frame_id"] == 0xEEEEEEEE, warm

    cases = [c for c in build_cases() if c["board"]]
    exp = expected(cases, board=True)
    lines = [f"# P1 fault injection on the board ({len(cases)} cases)", "",
             f"command: `python3 eth_faults.py --ip {a.ip} --gap-us {a.gap_us} --out {a.out}`", "",
             "| case | expected results | got | verdict |", "|---|---|---|---|"]
    n_fail = 0
    for case, e in zip(cases, exp):
        for dport, payload, _ in case["packets"]:
            s.sendto(payload, (a.ip, dport))
            t = time.perf_counter() + a.gap_us * 1e-6
            while time.perf_counter() < t:
                pass
        g = drain(0.2)
        ok = (len(g) == len(e)
              and all(all(gi[f] == ei[f] for f in CHECKED) for gi, ei in zip(g, e))
              and all(gi["t_rx_start"] <= gi["t_rx_end"] <= gi["t_result"] for gi in g))
        n_fail += not ok
        fmt = lambda rs: "; ".join(f"fid {r['frame_id']:#x} fl{r['flags']} rows {r['rows_seen']} bad {r['rows_bad']} "
                                   f"cks {r['checksum']}" for r in rs)
        lines.append(f"| {case['name']} | {fmt(e)} | {'same' if ok else fmt(g)} | {'PASS' if ok else 'FAIL'} |")
    lines += ["", f"**{len(cases) - n_fail}/{len(cases)} cases pass.**"]
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
