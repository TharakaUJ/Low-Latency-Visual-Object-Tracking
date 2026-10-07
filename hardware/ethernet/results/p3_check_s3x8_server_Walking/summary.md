# P3 board check: s3x8, crop server, Walking, 411 frames

command: `python3 check3.py --tracker s3x8 --crop server --seq Walking --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_s3x8_server_Walking`

| metric | value |
|---|---|
| sent per frame | 72x72 ROI (282x212 scaled) |
| frames | 411 (no result: 0) |
| FPGA = model | 411/411 |
| FPGA: last row in -> result (us) | p50 544.1, max 578.2 |
| round trip, last row sent -> result (us) | p50 625, p99 659 |
| P@20 (information only) | 100.0 |
