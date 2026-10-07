# P2 demo run: Walking

command: `python3 demo_zsad.py --source otb --seq Walking --roi 80 --target-px 16.0 --fps 30.0 --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090`

| metric | value |
|---|---|
| frames tracked | 411 |
| FPGA = model | 411/411 |
| rejected matches (hold) | 0 |
| FPGA compute after the last row (us) | p50 2.5, max 4.3 |
| network round trip, last row sent -> result (us) | p50 67, p99 239, max 251 |
| P@20 (information only) | 95.9 |
| success AUC, fixed box size (information only) | 53.2 |

Scaling + 80x80 ROI crop run on the server; tracking runs on the DE2-115 FPGA (ZSAD 16x16).
