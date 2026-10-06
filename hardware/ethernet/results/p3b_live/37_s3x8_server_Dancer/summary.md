# P3 demo session: s3x8, crop server, Dancer

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Dancer", "tracker": "zsad", "crop": "server", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 44, "corr_L": 48, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 974 |
| FPGA = model | 974/974 checked (974 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 36.7 |
| FPGA compute after the last row (us) | p50 536.2, max 659.3 |
| network round trip, last row sent -> result (us) | p50 603, p99 701, max 705 |
| OSTrack requests / applied | 22 / 17 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 2.9, max 5.8 |
| OSTrack time per request (ms), GPU calls per request | p50 32.1, 1.94 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
