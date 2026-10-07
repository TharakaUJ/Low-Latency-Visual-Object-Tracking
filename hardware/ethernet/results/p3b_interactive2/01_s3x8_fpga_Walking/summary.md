# P3 demo session: s3x8, crop fpga, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_interactive2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Jumping", "tracker": "zsad", "crop": "fpga", "cam": 0, "fps": 15.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 10, "corr_L": 15, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 1300 |
| FPGA = model | 1300/1300 checked (1300 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 28.2 |
| FPGA compute after the last row (us) | p50 380.8, max 617.2 |
| network round trip, last row sent -> result (us) | p50 439, p99 650, max 691 |
| OSTrack requests / applied | 7 / 5 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.2, max 2.0 |
| OSTrack time per request (ms), GPU calls per request | p50 13.9, 1.00 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
