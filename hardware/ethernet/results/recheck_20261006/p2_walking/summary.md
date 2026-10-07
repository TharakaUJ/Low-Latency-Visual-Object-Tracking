# P2 board check: Walking, 50 frames, ROI 80, target 16 px, 30 fps

command: `python3 p2_board_check.py --seq Walking --frames 50 --roi 80 --target-px 16 --fps 30 --out ../results/recheck_20261006/p2_walking`

| metric | value |
|---|---|
| frames | 50 (no result: 0) |
| FPGA = model | 50/50 |
| rejected matches (hold) | 0 |
| FPGA compute, last row in -> result (us) | p50 2.5, max 5.6 |
| round trip, last row sent -> result (us) | p50 77, p99 129, max 135 |
| transport = round trip - FPGA compute (us) | p50 74 |
| P@20 over these frames (information only) | 100.0 |

Scaling and ROI crop run on the server; the FPGA runs the existing ZSAD matcher on the 80x80 ROI.
