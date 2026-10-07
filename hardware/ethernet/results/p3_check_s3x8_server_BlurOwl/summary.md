# P3 board check: s3x8, crop server, BlurOwl, 630 frames

command: `python3 check3.py --tracker s3x8 --crop server --seq BlurOwl --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_s3x8_server_BlurOwl`

| metric | value |
|---|---|
| sent per frame | 72x72 ROI (137x103 scaled) |
| frames | 630 (no result: 0) |
| FPGA = model | 630/630 |
| FPGA: last row in -> result (us) | p50 574.1, max 672.5 |
| round trip, last row sent -> result (us) | p50 651, p99 724 |
| P@20 (information only) | 99.8 |
