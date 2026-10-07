# P3 demo session: s3x8, crop fpga, Walking2

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking2", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 9.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 40, "corr_L": 16, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 2241 |
| FPGA = model | 2241/2241 checked (2241 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 35.6 |
| FPGA compute after the last row (us) | p50 500.7, max 651.6 |
| network round trip, last row sent -> result (us) | p50 561, p99 683, max 701 |
| OSTrack requests / applied | 56 / 54 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 2.9, max 32.0 |
| OSTrack time per request (ms), GPU calls per request | p50 16.6, 1.39 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
