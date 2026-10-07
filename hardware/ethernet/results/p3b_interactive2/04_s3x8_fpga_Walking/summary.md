# P3 demo session: s3x8, crop fpga, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_interactive2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 30.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 30, "corr_L": 6, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 1268 |
| FPGA = model | 1268/1268 checked (1268 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 29.1 |
| FPGA compute after the last row (us) | p50 352.2, max 628.6 |
| network round trip, last row sent -> result (us) | p50 411, p99 648, max 682 |
| OSTrack requests / applied | 1 / 1 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.0, max 1.0 |
| OSTrack time per request (ms), GPU calls per request | p50 16.1, 1.00 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
