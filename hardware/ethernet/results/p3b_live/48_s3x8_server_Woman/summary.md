# P3 demo session: s3x8, crop server, Woman

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Boy", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 17.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 11, "corr_L": 8, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 1877 |
| FPGA = model | 1877/1877 checked (1877 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 17.0 |
| FPGA compute after the last row (us) | p50 540.7, max 634.2 |
| network round trip, last row sent -> result (us) | p50 612, p99 705, max 721 |
| OSTrack requests / applied | 170 / 166 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 25.6, max 58.6 |
| OSTrack time per request (ms), GPU calls per request | p50 28.6, 1.70 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
