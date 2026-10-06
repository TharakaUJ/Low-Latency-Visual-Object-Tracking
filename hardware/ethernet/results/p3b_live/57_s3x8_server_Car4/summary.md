# P3 demo session: s3x8, crop server, Car4

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Car4", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 17, "corr_L": 11, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 85 |
| FPGA = model | 85/85 checked (85 frames) |
| rejected matches (hold) | 0 |
| display rate, last 85 frames (fps) | p50 41.9 |
| FPGA compute after the last row (us) | p50 613.5, max 632.0 |
| network round trip, last row sent -> result (us) | p50 661, p99 698, max 702 |
| OSTrack requests / applied | 5 / 4 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.5, max 2.0 |
| OSTrack time per request (ms), GPU calls per request | p50 17.4, 1.00 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
