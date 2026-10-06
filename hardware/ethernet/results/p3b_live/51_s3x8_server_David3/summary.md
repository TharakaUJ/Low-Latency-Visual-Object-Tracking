# P3 demo session: s3x8, crop server, David3

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "David3", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 17.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 11, "corr_L": 8, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 761 |
| FPGA = model | 761/761 checked (761 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 17.0 |
| FPGA compute after the last row (us) | p50 565.5, max 661.1 |
| network round trip, last row sent -> result (us) | p50 635, p99 712, max 1413 |
| OSTrack requests / applied | 69 / 66 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 15.2, max 49.8 |
| OSTrack time per request (ms), GPU calls per request | p50 14.9, 1.21 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
