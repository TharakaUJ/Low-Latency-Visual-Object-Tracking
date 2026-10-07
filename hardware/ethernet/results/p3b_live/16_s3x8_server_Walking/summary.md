# P3 demo session: s3x8, crop server, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 40, "corr_L": 28, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 560 |
| FPGA = model | 560/560 checked (560 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 33.5 |
| FPGA compute after the last row (us) | p50 526.1, max 656.6 |
| network round trip, last row sent -> result (us) | p50 579, p99 702, max 732 |
| OSTrack requests / applied | 14 / 11 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.0, max 1.4 |
| OSTrack time per request (ms), GPU calls per request | p50 16.2, 1.00 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
