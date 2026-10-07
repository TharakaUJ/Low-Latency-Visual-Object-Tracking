# P3 demo session: zsad, crop fpga, Jumping

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_interactive2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "BlurOwl", "tracker": "zsad", "crop": "server", "cam": 0, "fps": 15.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 10, "corr_L": 15, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 551 |
| FPGA = model | 551/551 checked (551 frames) |
| rejected matches (hold) | 19 |
| display rate, last 300 frames (fps) | p50 15.0 |
| FPGA compute after the last row (us) | p50 0.0, max 2.1 |
| network round trip, last row sent -> result (us) | p50 87, p99 126, max 139 |
| OSTrack requests / applied | 24 / 22 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.1, max 9.4 |
| OSTrack time per request (ms), GPU calls per request | p50 14.2, 1.00 |

Scaling on the server; 80x80 ROI crop in the FPGA; tracking on the DE2-115 (ZSAD 16x16).
