# P3 demo session: zsad, crop server, Dancer

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Dancer", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 44, "corr_L": 48, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 17170 |
| FPGA = model | 17170/17170 checked (17170 frames) |
| rejected matches (hold) | 7153 |
| display rate, last 300 frames (fps) | p50 59.7 |
| FPGA compute after the last row (us) | p50 2.5, max 7.7 |
| network round trip, last row sent -> result (us) | p50 75, p99 123, max 190 |
| OSTrack requests / applied | 390 / 305 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 3.4, max 14.4 |
| OSTrack time per request (ms), GPU calls per request | p50 28.9, 1.75 |

Scaling + 80x80 ROI crop on the server; tracking on the DE2-115 (ZSAD 16x16).
