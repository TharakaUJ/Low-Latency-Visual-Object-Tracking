# P2 demo run: Walking

command: `python3 demo_zsad.py --source otb --seq Walking --roi 80 --target-px 16.0 --fps 30.0 --loop True --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090`

| metric | value |
|---|---|
| frames tracked | 916 |
| FPGA = model | 916/916 |
| rejected matches (hold) | 0 |
| FPGA compute after the last row (us) | p50 2.5, max 53.0 |
| network round trip, last row sent -> result (us) | p50 71, p99 240, max 265 |

Scaling + 80x80 ROI crop run on the server; tracking runs on the DE2-115 FPGA (ZSAD 16x16).
