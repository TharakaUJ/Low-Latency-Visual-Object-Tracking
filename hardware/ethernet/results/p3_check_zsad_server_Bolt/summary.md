# P3 board check: zsad, crop server, Bolt, 349 frames

command: `python3 check3.py --tracker zsad --crop server --seq Bolt --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_server_Bolt`

| metric | value |
|---|---|
| sent per frame | 80x80 ROI (257x145 scaled) |
| frames | 349 (no result: 0) |
| FPGA = model | 349/349 |
| FPGA: last row in -> result (us) | p50 2.5, max 6.2 |
| round trip, last row sent -> result (us) | p50 73, p99 124 |
| P@20 (information only) | 1.1 |
