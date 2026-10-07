# P3 demo run: s3x8, crop fpga, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/recheck_20261006/demo_s3x8_loop`

| metric | value |
|---|---|
| frames tracked | 2231 |
| FPGA = model | 2231/2231 |
| rejected matches (hold) | 0 |
| FPGA compute after the last row (us) | p50 436.3, max 657.4 |
| network round trip, last row sent -> result (us) | p50 505, p99 671, max 857 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
