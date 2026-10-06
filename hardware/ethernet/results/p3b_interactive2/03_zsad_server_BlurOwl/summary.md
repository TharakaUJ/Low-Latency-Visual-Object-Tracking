# P3 demo session: zsad, crop server, BlurOwl

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_interactive2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 30.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 30, "corr_L": 6, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 299 |
| FPGA = model | 299/299 checked (299 frames) |
| rejected matches (hold) | 5 |
| display rate, last 299 frames (fps) | p50 15.0 |
| FPGA compute after the last row (us) | p50 2.5, max 6.3 |
| network round trip, last row sent -> result (us) | p50 74, p99 121, max 144 |
| OSTrack requests / applied | 29 / 28 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 5.3, max 62.9 |
| OSTrack time per request (ms), GPU calls per request | p50 14.8, 1.29 |

Scaling + 80x80 ROI crop on the server; tracking on the DE2-115 (ZSAD 16x16).
