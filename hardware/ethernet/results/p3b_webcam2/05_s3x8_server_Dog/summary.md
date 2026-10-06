# P3 demo session: s3x8, crop server, Dog

command: `python3 demo.py --tracker s3x8 --crop server --source webcam --seq Walking --cam-size 640x480 --cam-exposure 250 --cam-gain 48 --target-px 16.0 --fps 30.0 --corr-n 17 --corr-l 11 --corr-mode pos --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_webcam2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Couple", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 30.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 17, "corr_L": 11, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 1275 |
| FPGA = model | 1275/1275 checked (1275 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 29.5 |
| FPGA compute after the last row (us) | p50 543.4, max 663.3 |
| network round trip, last row sent -> result (us) | p50 623, p99 708, max 751 |
| OSTrack requests / applied | 75 / 68 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 6.3, max 24.3 |
| OSTrack time per request (ms), GPU calls per request | p50 29.4, 1.91 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
