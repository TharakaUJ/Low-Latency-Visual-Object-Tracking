# P3 board check: zsad, crop fpga, Bolt, 349 frames

command: `python3 check3.py --tracker zsad --crop fpga --seq Bolt --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_fpga_Bolt`

| metric | value |
|---|---|
| sent per frame | whole scaled frame (257x145 scaled) |
| frames | 349 (no result: 0) |
| FPGA = model | 349/349 |
| FPGA: last row in -> result (us) | p50 0.0, max 2.4 |
| round trip, last row sent -> result (us) | p50 75, p99 121 |
| P@20 (information only) | 1.1 |
