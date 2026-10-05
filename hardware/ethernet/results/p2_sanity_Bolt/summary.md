# P2 board check: Bolt, 50 frames, ROI 80, target 16 px, 30 fps

command: `python3 p2_board_check.py --seq Bolt --frames 50 --roi 80 --target-px 16 --fps 30 --out ../results/p2_sanity_Bolt`

| metric | value |
|---|---|
| frames | 50 (no result: 0) |
| FPGA = model | 50/50 |
| rejected matches (hold) | 0 |
| FPGA compute, last row in -> result (us) | p50 2.5, max 5.6 |
| round trip, last row sent -> result (us) | p50 106, p99 153, max 155 |
| transport = round trip - FPGA compute (us) | p50 103 |
| P@20 over these frames (information only) | 8.0 |

Scaling and ROI crop run on the server; the FPGA runs the existing ZSAD matcher on the 80x80 ROI.
