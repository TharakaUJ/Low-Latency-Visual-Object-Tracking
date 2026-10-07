# P2 demo run: Jumping

command: `python3 demo_zsad.py --source otb --seq Jumping --roi 80 --target-px 16.0 --fps 30.0 --loop True --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/demo_loopcheck`

| metric | value |
|---|---|
| frames tracked | 3875 |
| FPGA = model | 3875/3875 |
| rejected matches (hold) | 103 |
| FPGA compute after the last row (us) | p50 2.5, max 6.4 |
| network round trip, last row sent -> result (us) | p50 88, p99 152, max 236 |

Scaling + 80x80 ROI crop run on the server; tracking runs on the DE2-115 FPGA (ZSAD 16x16).
