# P3 board check: zsad, crop server, Jumping, 312 frames

command: `python3 check3.py --tracker zsad --crop server --seq Jumping --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_server_Jumping`

| metric | value |
|---|---|
| sent per frame | 80x80 ROI (168x138 scaled) |
| frames | 312 (no result: 0) |
| FPGA = model | 312/312 |
| FPGA: last row in -> result (us) | p50 2.5, max 5.1 |
| round trip, last row sent -> result (us) | p50 69, p99 119 |
| P@20 (information only) | 99.4 |
