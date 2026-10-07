# P1 loopback: 10000 frames 640x480 random, fps target max

command: `python3 eth_loopback.py --ip 10.8.100.230 --port 1234 --width 640 --height 480 --fps 0.0 --frames 10000 --pattern random --pool 16 --seed 0 --wait 2.0 --out results/long_max`

| metric | value |
|---|---|
| frames sent | 10000 |
| results received | 10000 (lost 0, duplicate 0, other packets 0) |
| frames OK (all rows + checksum) | 10000 |
| incomplete frames | 0 (missing rows total 0) |
| bad rows reported by FPGA | 0 |
| checksum mismatches | 0 |
| achieved frame rate | 360.7 fps over 27.72 s |
| pixel throughput | 886.4 Mbit/s (on the wire ~994.4) |
| host send time per frame (us) | p50 2768, p99 2822 |
| RTT last row sent -> result (us) | p50 574, p95 608, p99 612, max 654 |
| first row sent -> result (us) | p50 3357, p99 3383, max 3478 |
| FPGA first row -> last row (us) | p50 2772, p99 2772 |
| FPGA last row -> result (us) | p50 0.000, max 0.000 (P1 has no compute) |

Times: host send/receive stamps are CLOCK_REALTIME ns (receive = kernel SO_TIMESTAMPNS); FPGA times are its 125 MHz counter.
