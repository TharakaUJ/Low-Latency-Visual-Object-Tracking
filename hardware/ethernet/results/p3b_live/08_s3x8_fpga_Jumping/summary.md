# P3 demo session: s3x8, crop fpga, Jumping

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Deer", "tracker": "s3x8", "crop": "fpga", "cam": 0, "fps": 60.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 40, "corr_L": 6, "corr_mode": "pos+tmpl"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 2838 |
| FPGA = model | 2838/2838 checked (2838 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 36.3 |
| FPGA compute after the last row (us) | p50 331.7, max 614.9 |
| network round trip, last row sent -> result (us) | p50 391, p99 606, max 691 |
| OSTrack requests / applied | 70 / 69 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 0.9, max 6.0 |
| OSTrack time per request (ms), GPU calls per request | p50 15.9, 1.03 |

Scaling on the server; 72x72 ROI crop in the FPGA; tracking on the DE2-115 (S-3x8 int8 CNN).
