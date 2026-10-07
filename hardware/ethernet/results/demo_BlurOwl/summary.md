# P2 demo run: BlurOwl

command: `python3 demo_zsad.py --source otb --seq BlurOwl --roi 80 --target-px 16.0 --fps 30.0 --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --out ../results/demo_BlurOwl`

| metric | value |
|---|---|
| frames tracked | 630 |
| FPGA = model | 630/630 |
| rejected matches (hold) | 7 |
| FPGA compute after the last row (us) | p50 2.5, max 6.6 |
| network round trip, last row sent -> result (us) | p50 78, p99 157, max 167 |
| P@20 (information only) | 98.9 |
| success AUC, fixed box size (information only) | 79.8 |

Scaling + 80x80 ROI crop run on the server; tracking runs on the DE2-115 FPGA (ZSAD 16x16).
