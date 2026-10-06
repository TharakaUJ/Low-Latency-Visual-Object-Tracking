# P3 demo session: s3x8, crop fpga, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_interactive3 --workers 4` (settings at the end of the session: {"source": "webcam", "seq": "Walking", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 30.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 30, "corr_L": 6, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 288 |
| FPGA = model | 288/288 checked (288 frames) |
| rejected matches (hold) | 0 |
| display rate, last 288 frames (fps) | p50 29.9 |
| FPGA compute after the last row (us) | p50 423.9, max 593.0 |
| network round trip, last row sent -> result (us) | p50 476, p99 639, max 644 |
| OSTrack requests / applied | 4 / 4 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.1, max 1.4 |
| OSTrack time per request (ms), GPU calls per request | p50 20.3, 1.50 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
