# P3 demo run: s3x8, crop fpga, webcam0

command: `python3 demo.py --tracker s3x8 --crop fpga --source webcam --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --out ../results/recheck_20261006/demo_s3x8_webcam`

| metric | value |
|---|---|
| frames tracked | 3532 |
| FPGA = model | 3532/3532 |
| rejected matches (hold) | 0 |
| FPGA compute after the last row (us) | p50 567.4, max 648.3 |
| network round trip, last row sent -> result (us) | p50 646, p99 714, max 830 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
