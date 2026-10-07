# P3 board check: s3x8, crop fpga, BlurOwl, 630 frames

command: `python3 check3.py --tracker s3x8 --crop fpga --seq BlurOwl --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_s3x8_fpga_BlurOwl`

| metric | value |
|---|---|
| sent per frame | whole scaled frame (137x103 scaled) |
| frames | 630 (no result: 0) |
| FPGA = model | 630/630 |
| FPGA: last row in -> result (us) | p50 534.2, max 625.2 |
| round trip, last row sent -> result (us) | p50 602, p99 698 |
| P@20 (information only) | 99.8 |
