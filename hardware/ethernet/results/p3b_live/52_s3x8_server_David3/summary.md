# P3 demo session: s3x8, crop server, David3

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Dudek", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 17.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 11, "corr_L": 8, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 495 |
| FPGA = model | 495/495 checked (495 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 17.0 |
| FPGA compute after the last row (us) | p50 542.2, max 636.2 |
| network round trip, last row sent -> result (us) | p50 621, p99 709, max 720 |
| OSTrack requests / applied | 45 / 44 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 14.6, max 49.8 |
| OSTrack time per request (ms), GPU calls per request | p50 15.2, 1.25 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
