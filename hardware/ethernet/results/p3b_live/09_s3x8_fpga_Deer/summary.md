# P3 demo session: s3x8, crop fpga, Deer

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking2", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 40, "corr_L": 16, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 3146 |
| FPGA = model | 3146/3146 checked (3146 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 34.7 |
| FPGA compute after the last row (us) | p50 520.5, max 621.9 |
| network round trip, last row sent -> result (us) | p50 587, p99 672, max 1152 |
| OSTrack requests / applied | 78 / 65 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 9.6, max 31.1 |
| OSTrack time per request (ms), GPU calls per request | p50 31.7, 2.00 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
