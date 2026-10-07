# Next session: where to start (written 2026-10-07, after P3b)

Board repo: `~/Documents/Low-Latency-Visual-Object-Tracking` (branch `ethernet-demo`, nothing pushed; last commits 5f1d6a7 speed test + drain fix, 510785a corrections + control panel). Everything runs from `hardware/ethernet/`: `make help`. Full history: `docs/demo_log.md` (local copy: `presentation/demo/demo_log.md`).

## State
- **P1, P2, P3:** done and board-tested (see demo_log). The S-3x8 bitstream now includes the cut-frame drain fix: testbench 46/46, timing +0.094 ns, 53 % LE.
- **P3b (plan_P3b.md):** done except part B.
  - **A, speed** (`make speed`, Walking, every result checked against the model):

    | tracker | server crop | FPGA crop | latency (last row sent → result) |
    |---|---|---|---|
    | S-3x8 | clean to 1050 fps | clean to 500 fps | ~0.85 ms |
    | ZSAD | clean to 3000 fps | clean to 1629 fps (= the link) | 0.09–0.3 ms |

  - **C + D:** demo page with a control panel and OSTrack-256 corrections (K3, ost-gated 0.6; N, L and mode live). Start with `make demo` or `cd host && python3 demo.py --tracker s3x8 --seq Walking --loop` → http://100.76.229.14:8090/.
  - **B (ROI 96):** not needed for now (user, 2026-10-07).

## Open items (to discuss)
- **Overload behaviour:** above the tracker's limit, cut frames still use the tracker, so throughput collapses (S-3x8 server crop: 3000 fps sent → 16 tracked/s). Dropping whole frames when the tracker is busy would keep ~1000/s. RTL change, not done.
- **S-3x8 headroom:** the core runs at 62.5 MHz with Fmax 77 MHz (~1300 fps). More parallel L1 units would need a separate RTL plan.
- **FPGA-crop limit:** each crop needs the previous result. Cropping with the last known position when the result is late would raise the rate but changes the tracking rule (model must follow).
- **Unexplained transient packet loss** in the first P3b demo run (not reproduced; corrections now commit only when the board acknowledges).
- **Not yet tested through the page:** the webcam (camera was unplugged).
- **User idea for later:** template-only correction with a larger search area when the request frame is old.
- **Demo vs research:** target 16 px (research 20) and the demo is a single run per sequence, not the measured benchmark.
- **ZSAD FPGA-crop speed run:** the first 30 fps step lost 99 frames right after programming (link settling?).
- **Flash workflow** (flash-backup / check / restore) still untested on hardware; only needed if JTAG and Ethernet can't both be connected.
- **Board IP 10.8.100.230 is not reserved.** The RGMII TX clock path depends on placement (ZSAD uses seed 2).
