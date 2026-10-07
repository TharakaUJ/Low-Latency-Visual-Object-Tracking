# P3 board check: zsad, crop fpga, Walking, 411 frames

command: `python3 check3.py --tracker zsad --crop fpga --seq Walking --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_fpga_Walking`

| metric | value |
|---|---|
| sent per frame | whole scaled frame (282x212 scaled) |
| frames | 411 (no result: 0) |
| FPGA = model | 411/411 |
| FPGA: last row in -> result (us) | p50 0.0, max 2.5 |
| round trip, last row sent -> result (us) | p50 75, p99 130 |
| P@20 (information only) | 95.9 |
