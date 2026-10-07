# P3 demo run: s3x8, crop fpga, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --out ../results/recheck_20261006/dash_s3x8_walking --workers 4`

| metric | value |
|---|---|
| frames tracked | 411 |
| FPGA = model | 411/411 checked (411 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 29.7 |
| FPGA compute after the last row (us) | p50 458.8, max 648.1 |
| network round trip, last row sent -> result (us) | p50 516, p99 650, max 699 |
| P@20 (information only) | 100.0 |
| success AUC, fixed box size (information only) | 52.1 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
