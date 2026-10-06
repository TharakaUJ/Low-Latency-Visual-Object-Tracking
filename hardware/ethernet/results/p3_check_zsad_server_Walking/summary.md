# P3 board check: zsad, crop server, Walking, 411 frames

command: `python3 check3.py --tracker zsad --crop server --seq Walking --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_server_Walking`

| metric | value |
|---|---|
| sent per frame | 80x80 ROI (282x212 scaled) |
| frames | 411 (no result: 0) |
| FPGA = model | 411/411 |
| FPGA: last row in -> result (us) | p50 2.5, max 5.6 |
| round trip, last row sent -> result (us) | p50 73, p99 133 |
| P@20 (information only) | 95.9 |
