# P3 speed test: s3x8, crop fpga, Walking (whole scaled frame, 282x212)

command: `python3 speed3.py --tracker s3x8 --crop fpga --seq Walking --rates 1100,1150 --seconds 3 --min-frames 300 --max-frames 6000 --out ../results/speed_debug_fpga`

**No clean step.**

| target fps | sent fps | frames | results | tracked | FPGA = model | origin ok | incomplete | timeouts | tracked/s | FPGA rows in (us) | FPGA last row -> result p50/p99/max (us) | round trip p50/p99 (us) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1100 | 1100 | 3300 | 3299 | 1650 | 1442/1650 | 1/1 | 1649 | 0 | 550 | 614 | 573 / 711 / 786 | 800 / 977 |
| 1150 | 1150 | 3450 | 3449 | 1725 | 1725/1725 | 1/1 | 1724 | 0 | 575 | 614 | 541 / 692 / 898 | 857 / 1003 |
