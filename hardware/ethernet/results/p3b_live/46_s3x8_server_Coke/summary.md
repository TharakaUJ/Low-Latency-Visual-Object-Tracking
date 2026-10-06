# P3 demo session: s3x8, crop server, Coke

command: `python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking --cam-size 640x480 --target-px 16.0 --fps 30.0 --loop True --corr-n 30 --corr-l 6 --corr-mode pos+tmpl --ip 10.8.100.230 --bind 100.76.229.14 --http-port 8090 --no-video True --out ../results/p3b_live --workers 4` (settings at the end of the session: {"source": "otb", "seq": "Ironman", "tracker": "s3x8", "crop": "server", "cam": 0, "fps": 28.0, "loop": 1, "paused": 0, "corr_on": 1, "corr_N": 31, "corr_L": 17, "corr_mode": "pos"}; changes in controls.csv)

| metric | value |
|---|---|
| frames tracked | 444 |
| FPGA = model | 444/444 checked (444 frames) |
| rejected matches (hold) | 0 |
| display rate, last 300 frames (fps) | p50 27.9 |
| FPGA compute after the last row (us) | p50 543.6, max 634.6 |
| network round trip, last row sent -> result (us) | p50 617, p99 703, max 742 |
| OSTrack requests / applied | 14 / 12 (late: 0; not acknowledged by the board: 0) |
| FPGA vs OSTrack at the request frame (scaled px) | mean 26.0, max 52.4 |
| OSTrack time per request (ms), GPU calls per request | p50 28.3, 1.58 |

Scaling + 72x72 ROI crop on the server; tracking on the DE2-115 (S-3x8 int8 CNN).
