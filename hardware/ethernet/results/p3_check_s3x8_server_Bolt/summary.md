# P3 board check: s3x8, crop server, Bolt, 349 frames

command: `python3 check3.py --tracker s3x8 --crop server --seq Bolt --frames 0 --target-px 16 --fps 30 --out /home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet/results/p3_check_s3x8_server_Bolt`

| metric | value |
|---|---|
| sent per frame | 72x72 ROI (257x145 scaled) |
| frames | 349 (no result: 0) |
| FPGA = model | 349/349 |
| FPGA: last row in -> result (us) | p50 624.6, max 662.2 |
| round trip, last row sent -> result (us) | p50 702, p99 731 |
| P@20 (information only) | 1.4 |
