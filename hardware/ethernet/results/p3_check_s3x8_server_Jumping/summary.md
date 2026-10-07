# P3 board check: s3x8, crop server, Jumping, 312 frames

command: `python3 check3.py --tracker s3x8 --crop server --seq Jumping --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_s3x8_server_Jumping`

| metric | value |
|---|---|
| sent per frame | 72x72 ROI (168x138 scaled) |
| frames | 312 (no result: 0) |
| FPGA = model | 312/312 |
| FPGA: last row in -> result (us) | p50 627.0, max 662.6 |
| round trip, last row sent -> result (us) | p50 676, p99 708 |
| P@20 (information only) | 100.0 |
