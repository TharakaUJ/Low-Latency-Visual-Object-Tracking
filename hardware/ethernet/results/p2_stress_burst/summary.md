# P2 line-rate stress: Walking crops, mode burst, 2000 frames 80x80

command: `python3 p2_stress.py --seq Walking --mode burst --frames 2000 --roi 80 --out ../results/p2_stress_burst`

| metric | value |
|---|---|
| frames sent / results | 2000 / 2000 |
| complete / incomplete (rows lost) | 1015 / 985 (29608 rows missing) |
| tracked | 1015 (tracker timeouts 0) |
| FPGA = model (tracked frames) | 1015/1015 |
| send rate | 7844 frames/s over 0.25 s; tracked results/s 3981 |
| FPGA: first row -> last row in (us) | p50 102.0, max 205.6 |
| FPGA: last row in -> result (us) | p50 97.6, p99 113.7, max 117.5 |
| FPGA: first row in -> result (us) | p50 198.8, max 224.7 |
| round trip, last row sent -> result (us) | p50 144, p99 187, max 257 |
