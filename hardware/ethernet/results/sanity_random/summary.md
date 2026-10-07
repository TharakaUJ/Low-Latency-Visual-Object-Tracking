# P1 loopback: 10 frames 640x480 random, fps target 30.0

command: `python3 eth_loopback.py --ip 10.8.100.230 --port 1234 --width 640 --height 480 --fps 30.0 --frames 10 --pattern random --pool 16 --seed 0 --wait 1.0 --out results/sanity_random`

| metric | value |
|---|---|
| frames sent | 10 |
| results received | 10 (lost 0, duplicate 0, other packets 0) |
| frames OK (all rows + checksum) | 10 |
| incomplete frames | 0 (missing rows total 0) |
| bad rows reported by FPGA | 0 |
| checksum mismatches | 0 |
| achieved frame rate | 30.0 fps over 0.30 s |
| pixel throughput | 73.7 Mbit/s (on the wire ~82.7) |
| host send time per frame (us) | p50 2283, p99 2302 |
| RTT last row sent -> result (us) | p50 572, p95 619, p99 622, max 623 |
| first row sent -> result (us) | p50 2855, p99 2921, max 2924 |
| FPGA first row -> last row (us) | p50 2772, p99 2772 |
| FPGA last row -> result (us) | p50 0.000, max 0.000 (P1 has no compute) |

Times: host send/receive stamps are CLOCK_REALTIME ns (receive = kernel SO_TIMESTAMPNS); FPGA times are its 125 MHz counter.
