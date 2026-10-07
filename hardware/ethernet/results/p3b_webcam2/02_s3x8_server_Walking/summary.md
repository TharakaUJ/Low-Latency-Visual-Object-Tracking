# P3 demo session: s3x8, crop server, Walking

command: `python3 demo.py --tracker s3x8 --crop server --source webcam --seq Walking --cam-size 640x480 --cam-exposure 250 --cam-gain 48 --target-px 16.0 --fps 30.0 --corr-n 17 --corr-l 11 --corr-mode pos --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_webcam2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 30.0, "loop": 0, "paused": 0, "corr_on": 1, "corr_N": 17, "corr_L": 11, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 411 |
| FPGA = model | 411/411 checked (411 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 29.3 |
| FPGA compute after the last row (us) | p50 512.1, max 635.0 |
| network round trip, last row sent -> result (us) | p50 560, p99 703, max 710 |
| OSTrack requests / applied | 24 / 23 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 1.6, max 3.2 |
| OSTrack time per request (ms), GPU calls per request | p50 16.8, 1.43 |
| P@20 (information only) | 100.0 |
| success AUC, fixed box size (information only) | 52.1 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
