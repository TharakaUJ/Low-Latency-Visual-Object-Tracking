# Next session: where to start (written 2026-10-06, after the P3 simulation fixes)

Board repo: `~/Documents/Low-Latency-Visual-Object-Tracking` (branch `ethernet-demo`, nothing pushed). Everything runs from `hardware/ethernet/`: `make help`. Full history: `docs/demo_log.md`.

## State in one paragraph
- **P1 and P2 are done and board-tested.** P1: Ethernet row protocol, 0 errors at 30 fps and at line rate. P2: ZSAD on a server-cropped 80×80 ROI, FPGA = model on every frame, stress-tested.
- **P3 is done in simulation, not yet on the board.** ROI crop in the RTL, position held by the FPGA, tracker chosen at build time (ZSAD or S-3x8), no one-in-flight block.
  - Testbench (`make sim-zsad`, `make sim-s3x8`): **ZSAD 28/28, S-3x8 28/28**, FPGA = model on every frame.
  - Builds, all timing corners met: ZSAD 25 % LE (fitter seed 2, `p3_track/seed_2.qsf`), S-3x8 53 % LE, 60 multipliers, 13 % memory.
  - Bugs fixed on 2026-10-06: early tracker result lost with the RTL crop (now latched); S-3x8 stream shifted by one column after `sof` and by 5 columns when `sof` followed `done` (gap + drain); S-3x8 tracker FIFO 16 k words (two ROI frames); testbench waited for the wrong result.

## Board tests (plug in the board, ENET0 cable; JTAG via the USB-Blaster)
Do these in order, and stop at the first failure:

| # | command | expect |
|---|---|---|
| 1 | `make jtag` | EP4CE115 listed |
| 2 | `make program-p1 && make loopback FPS=30` (shorter: edit `--frames`) | 0 lost / bad / checksum (regression of P1) |
| 3 | `make faults` | 19/19 |
| 4 | `make program-p2 && cd host && python3 p2_board_check.py --seq Walking --frames 50 --out ../results/p2_recheck` | 50/50 FPGA = model (regression of P2) |
| 5 | `make program-zsad && make check TRACKER=zsad CROP=server SEQ=Walking FRAMES=50` | 50/50 |
| 6 | `make check TRACKER=zsad CROP=fpga SEQ=Walking FRAMES=50` | 50/50, flags show bit5 (cropped in the RTL) |
| 7 | `make check-all TRACKER=zsad` | all sequences, both modes, FPGA = model on every frame |
| 8 | `make program-s3x8 && make check TRACKER=s3x8 CROP=fpga SEQ=Walking FRAMES=50` | 50/50; LEDR17 (line overrun) stays off |
| 9 | `make check-all TRACKER=s3x8` | as 7 |
| 10 | `make demo TRACKER=s3x8 CROP=fpga SEQ=Walking`, open http://100.76.229.14:8090/ | live view, FPGA = model |
| 11 | webcam: plug it in, `cd host && python3 demo.py --tracker zsad --source webcam --cam 0`, drag the box on the page | tracks; untested so far |

If the board does not answer ARP after programming: check the LEDG LEDs (LEDG1 = 1 Gb/s, LEDG2 = frames received) and re-seat the cable (see README "Setup").

## Open items and limits (to discuss)
- **P3 tracking vs research:** the S-3x8 demo uses its own simple loop (fixed template, ROI clamped at the borders, no DV, no OSTrack). It is not the measured LOCK system. P4 adds the server-side OSTrack corrections and the DV decision.
- **ZSAD:** fixed template, reject above 8192 = hold. The offline OTB-100 P@20 is 34.7 (information only).
- **S-3x8 throughput:** about 0.92 ms per ROI (800 clocks per line). The FIFO holds two ROI frames; faster input drops rows (reported as incomplete frames, never wrong results). Fine at 30 fps.
- **Timing margin:** the RGMII TX clock path (verilog-ethernet `rgmii_phy_if`) depends on placement. ZSAD seeds 1 and 3 fail it, seed 2 passes. An RTL change may need another seed (or a location constraint for that register).
- **Tracker timeout:** when a result times out, the receiver still waits up to 10 ms at the next cropped frame and loses rows meanwhile. A shorter timeout or not waiting at all is possible.
- **Board IP 10.8.100.230 is not reserved.**
