# P1 loopback: 1000 frames 640x480 random, fps target 30.0

command: `python3 eth_loopback.py --ip 10.8.100.230 --port 1234 --width 640 --height 480 --fps 30.0 --frames 1000 --pattern random --pool 16 --seed 0 --wait 1.0 --out ../results/recheck_20261006/loopback_fps30`

| metric | value |
|---|---|
| frames sent | 1000 |
| results received | 1000 (lost 0, duplicate 0, other packets 0) |
| frames OK (all rows + checksum) | 1000 |
| incomplete frames | 0 (missing rows total 0) |
| bad rows reported by FPGA | 0 |
| checksum mismatches | 0 |
| achieved frame rate | 30.0 fps over 33.30 s |
| pixel throughput | 73.7 Mbit/s (on the wire ~82.7) |
| host send time per frame (us) | p50 2292, p99 2639 |
| RTT last row sent -> result (us) | p50 584, p95 629, p99 647, max 673 |
| first row sent -> result (us) | p50 2883, p99 2948, max 3498 |
| FPGA first row -> last row (us) | p50 2772, p99 2802 |
| FPGA last row -> result (us) | p50 0.000, max 0.000 (P1 has no compute) |

Times: host send/receive stamps are CLOCK_REALTIME ns (receive = kernel SO_TIMESTAMPNS); FPGA times are its 125 MHz counter.
