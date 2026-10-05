# P2 line-rate stress: Walking crops, mode inflight, 5000 frames 80x80

command: `python3 p2_stress.py --seq Walking --mode inflight --frames 5000 --roi 80 --out ../results/p2_stress_inflight`

| metric | value |
|---|---|
| frames sent / results | 5000 / 5000 |
| complete / incomplete (rows lost) | 5000 / 0 (0 rows missing) |
| tracked | 5000 (tracker timeouts 0) |
| FPGA = model (tracked frames) | 5000/5000 |
| send rate | 4380 frames/s over 1.14 s; tracked results/s 4380 |
| FPGA: first row -> last row in (us) | p50 110.6, max 299.2 |
| FPGA: last row in -> result (us) | p50 46.2, p99 53.6, max 53.9 |
| FPGA: first row in -> result (us) | p50 156.8, max 334.0 |
| round trip, last row sent -> result (us) | p50 90, p99 109, max 136 |
