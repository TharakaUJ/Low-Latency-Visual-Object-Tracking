# Next session: where to start (written 2026-10-06, end of day)

Board repo: `~/Documents/Low-Latency-Visual-Object-Tracking` (branch `ethernet-demo`, nothing pushed). Everything runs from `hardware/ethernet/`: `make help`. Full history: `docs/demo_log.md`.

## State in one paragraph
- **P1 and P2 are done and board-tested.** P1: Ethernet row protocol, 0 errors at 30 fps and at line rate. P2: ZSAD on a server-cropped 80×80 ROI, FPGA = model on every frame, stress-tested.
- **P3 is written but not yet working in simulation.** It adds the ROI crop in the RTL, a position held by the FPGA, a choice of tracker (ZSAD or S-3x8 at build time), and removes the in-flight limit.
  - Both Quartus builds fit:
    - ZSAD: 27 % LE. Its timing failed by 0.94 ns at 125 MHz; fixes are written but not yet rebuilt.
    - S-3x8: 54 % LE, 60 multipliers, timing met.
  - The host S-3x8 model is bit-exact with the 3 E48 RTL reference cases.
  - **The P3 ZSAD testbench fails:**
    - The first FPGA-crop frame never gets a tracker result. The receiver times out after 10 ms (flags 0x31).
    - The next frame loses rows during that stall (21/120 rows).
    - After that, no result packets at all. The tracker side (async FIFO → `zsad_core`) probably stops consuming, which backs up the FIFO and stalls the receiver.

## Start here (simulation, no board needed)
1. **Isolate:** `cd hardware/ethernet/p3_track/tb && SECTIONS=6 TRACKER=zsad PATH=~/tools/mamba/envs/hdl/bin:$PATH SIM=verilator ../../.venv-sim/bin/pytest -q -rA test_p3.py`.
   - Section 6 is server-crop only (frames = 80×80, as in the working P2). If it also fails, the bug is in the P3 changes common to both modes:
     - template chunk/offset words (tag 3), and `zsad_core` setting `sh_pending` at byte 255;
     - the new_frame/tag logic (`p_new || !f_trk_started`);
     - the pending slot (`q_*`, `n_*`, `S_SLOT`).
   - If section 6 passes, the bug is in the crop path:
     - `S_HDR_A/A2/B/S_CTRL`, `p_ox/p_xend`, `beat_pix`, `trk_tlast/tuser`;
     - rows outside the window.
   - A full run takes ~16-22 min; one section takes a few minutes.
2. **Look at the FIFO stream:** add `--trace-fst` to the Verilator `compile_args`, or log `trk_tvalid/trk_tready/trk_tdata/trk_tlast/trk_tuser` and `zsad_core.state/rows_cnt/inorder` from cocotb. For the first FPGA-crop frame, check that each forwarded row is exactly [ctrl, 80 pixels, tlast], with tuser 0, that row 0 carries new_frame = 1, and that `zsad_core` reaches ST_DRAIN.
3. **Then:**
   - full `make sim-zsad`, then `make sim-s3x8` (not run yet; Verilator compile of the 1.9 MB E48 RTL may take a while);
   - `make build-zsad build-s3x8`, then `make timing`. Rebuild both: `row_stats.v` and `fpga_core.v` changed (timing fixes, UDP checksum generator off).
4. **Possible robustness fix to keep:** when a tracker result times out, the receiver currently loses packets while it waits (S_SLOT / S_HDR_A stall). After the bug fix, also consider a shorter timeout or not stalling at all.

## Board tests (plug in the board, ENET0 cable; JTAG via the USB-Blaster)
Do these in order, and stop at the first failure:

| # | command | expect |
|---|---|---|
| 1 | `make jtag` | EP4CE115 listed |
| 2 | `make program-p1 && make loopback FPS=30` (shorter: edit `--frames`) | 0 lost / bad / checksum (regression of P1) |
| 3 | `make faults` | 19/19 |
| 4 | `make program-p2 && cd host && python3 p2_board_check.py --seq Walking --frames 50 --out ../results/p2_recheck` | 50/50 FPGA = model (regression of P2) |
| 5 | only after the P3 sims pass: `make program-zsad && make check TRACKER=zsad CROP=server SEQ=Walking FRAMES=50` | 50/50 |
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
- **One pending result in P3.** A second trackable frame that completes while one is pending stalls the receiver. A short queue would remove this.
- **Board IP 10.8.100.230 is not reserved.**
