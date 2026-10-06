# P3 demo session: s3x8, crop server, Dog1

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Dog1", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 17, "corr_L": 11, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 3245 |
| FPGA = model | 3245/3245 checked (3245 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 35.8 |
| FPGA compute after the last row (us) | p50 536.3, max 657.4 |
| network round trip, last row sent -> result (us) | p50 597, p99 700, max 709 |
| OSTrack requests / applied | 190 / 189 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 3.6, max 35.0 |
| OSTrack time per request (ms), GPU calls per request | p50 16.7, 1.06 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
