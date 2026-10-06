# P3 board check: zsad, crop fpga, Jumping, 312 frames

command: `python3 check3.py --tracker zsad --crop fpga --seq Jumping --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_zsad_fpga_Jumping`

| metric | value |
|---|---|
| sent per frame | whole scaled frame (168x138 scaled) |
| frames | 312 (no result: 0) |
| FPGA = model | 312/312 |
| FPGA: last row in -> result (us) | p50 0.0, max 2.1 |
| round trip, last row sent -> result (us) | p50 64, p99 97 |
| P@20 (information only) | 99.4 |
