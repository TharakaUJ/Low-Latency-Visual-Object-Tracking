# P3 demo session: zsad, crop server, Dancer

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Dancer", "tracker": "zsad", "crop": "server", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 44, "corr_L": 48, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 4793 |
| FPGA = model | 4793/4793 checked (4793 frames) |
| rejected matches (hold) | 1976 |
| display rate, last 300 frames (fps) | p50 59.4 |
| FPGA compute after the last row (us) | p50 2.5, max 7.1 |
| network round trip, last row sent -> result (us) | p50 74, p99 121, max 272 |
| OSTrack requests / applied | 108 / 85 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 3.3, max 14.4 |
| OSTrack time per request (ms), GPU calls per request | p50 28.8, 1.74 |

Scaling + 80x80 ROI crop on the server; tracking on the DE2-115 (ZSAD 16x16).
