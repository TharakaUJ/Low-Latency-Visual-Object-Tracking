# P3 board check: s3x8, crop fpga, Walking, 100 frames

command: `python3 check3.py --tracker s3x8 --crop fpga --seq Walking --frames 100 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_s3x8_fpga_Walking`

| metric | value |
|---|---|
| sent per frame | whole scaled frame (282x212 scaled) |
| frames | 100 (no result: 0) |
| FPGA = model | 100/100 |
| FPGA: last row in -> result (us) | p50 574.3, max 649.2 |
| round trip, last row sent -> result (us) | p50 626, p99 675 |
| P@20 (information only) | 100.0 |
