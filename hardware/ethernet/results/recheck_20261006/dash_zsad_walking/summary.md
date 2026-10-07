# P3 demo run: zsad, crop fpga, Walking

command: `python3 demo.py --tracker zsad --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --out ../results/recheck_20261006/dash_zsad_walking --workers 4`

| metric | value |
|---|---|
| frames tracked | 411 |
| FPGA = model | 411/411 checked (411 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 30.0 |
| FPGA compute after the last row (us) | p50 0.0, max 2.5 |
| network round trip, last row sent -> result (us) | p50 75, p99 130, max 150 |
| P@20 (information only) | 95.9 |
| success AUC, fixed box size (information only) | 53.2 |

Scaling on the server; 80x80 ROI crop in the FPGA; tracking on the DE2-115 (ZSAD 16x16).
