# P3 demo session: s3x8, crop fpga, Walking

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --once True --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_try2 --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Walking", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 30.0, "loop": 0, "paused": 0, "corr_on": 1, "corr_N": 30, "corr_L": 6, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 411 |
| FPGA = model | 411/411 checked (411 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 30.0 |
| FPGA compute after the last row (us) | p50 440.8, max 599.0 |
| network round trip, last row sent -> result (us) | p50 495, p99 647, max 652 |
| OSTrack requests / applied | 8 / 8 (late: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 0.8, max 1.4 |
| OSTrack time per request (ms), GPU calls per request | p50 13.7, 1.25 |
| P@20 (information only) | 100.0 |
| success AUC, fixed box size (information only) | 53.9 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
