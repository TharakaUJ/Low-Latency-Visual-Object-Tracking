# P3 board check: zsad, crop server, BlurOwl, 630 frames

command: `python3 check3.py --tracker zsad --crop server --seq BlurOwl --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_server_BlurOwl`

| metric | value |
|---|---|
| sent per frame | 80x80 ROI (137x103 scaled) |
| frames | 630 (no result: 0) |
| FPGA = model | 630/630 |
| FPGA: last row in -> result (us) | p50 2.5, max 6.2 |
| round trip, last row sent -> result (us) | p50 73, p99 126 |
| P@20 (information only) | 98.9 |
