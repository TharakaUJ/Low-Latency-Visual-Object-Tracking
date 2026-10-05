# P2 demo run: Jumping

command: `python3 demo_zsad.py --source otb --seq Jumping --roi 80 --target-px 16.0 --fps 30.0 --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --out ../results/demo_Jumping`

| metric | value |
|---|---|
| frames tracked | 312 |
| FPGA = model | 312/312 |
| rejected matches (hold) | 8 |
| FPGA compute after the last row (us) | p50 2.5, max 5.7 |
| network round trip, last row sent -> result (us) | p50 85, p99 156, max 170 |
| P@20 (information only) | 99.4 |
| success AUC, fixed box size (information only) | 70.7 |

Scaling + 80x80 ROI crop run on the server; tracking runs on the DE2-115 FPGA (ZSAD 16x16).
