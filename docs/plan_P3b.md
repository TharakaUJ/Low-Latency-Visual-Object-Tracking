# P3b: S-3x8 speed test, server corrections, demo control panel

Status: DONE except part B (2026-10-07). A: speed test done (+ S-3x8 cut-frame drain fix, 5f1d6a7). C + D: OSTrack corrections and control panel done (510785a). B (ROI 96): not needed for now (user, 2026-10-07: "no need for 96x96 for now")
Builds on P3a (board-tested 2026-10-06, commit f93e85b). OTB is the main input; the webcam is a secondary option.

## Part A: S-3x8 full speed (measurement only, no RTL change)
Question: how many frames per second can the S-3x8 bitstream track, with every result still equal to the bit-exact model?
- Known so far: the core needs about 0.92 ms per 72×72 ROI (800 clocks per line), so the core ceiling is about 1080 ROI/s. The link and the FIFO (two ROI frames) may limit it earlier.
- **A1, server crop** (only the 72×72 ROI goes over the link): sweep the send rate (30, 60, 120, 250, 500, 750, 1000, 1200 fps, then line rate). For each rate record:
  - results per second
  - incomplete or dropped frames
  - FPGA = model count
  - result latency (last row to result, and round trip)
  - LEDR17 overrun
- **A2, FPGA crop** (full frames over the link; Walking is 768×576, about 0.44 MB per frame, so about 2000 fps at most on 1 Gb/s): same sweep.
- Repeat the same sweep for ZSAD, for comparison.
- Output: a table and a plot of rate vs. results/s and latency. The maximum sustained rate is the highest rate with 0 drops and 100 % FPGA = model.
- One command: `make speed TRACKER=s3x8 CROP=server|fpga`.
- If you want more speed after this (for example parallel L1 units), that is a separate RTL plan.

## Part B: larger search area (RTL rebuild): **needs your choice**
At the moment ZSAD uses an 80×80 ROI (±32 px of motion per frame) and S-3x8 uses 72×72 (±24 px).
- A larger ROI costs:
  - line-buffer and FIFO memory
  - S-3x8 time per ROI (candidates grow roughly with ROI², so about 1.8× at 96)
  - P@20 changes away from the measured E48 setup (that was at ROI 72), so the demo no longer matches the research number exactly
- Steps:
  1. Update the parameters and the model.
  2. Run the testbench (`make sim-*`).
  3. Build and check timing.
  4. Re-run the board check and Part A on the new bitstream.

## Part C: server corrections, made visible
The RTL already accepts template chunks (0x5AA6) and a position command (0x5AA7) at any time, so no RTL change is expected. Step 1 checks this in simulation.
- **Correction loop in demo.py:** every N frames the "server" produces a correction. It is applied to the FPGA L frames (or ms) later, as a new position and, optionally, a new template.
- **Correction source: needs your choice**
  - (a) OTB ground truth, delayed: an oracle that stands in for OSTrack
  - (b) the real OSTrack on the server GPU, which is the start of P4
- **Shown on the dashboard:**
  - a "correction" marker on the timeline and the plots
  - a flash or banner on the video when a correction is requested (frame k) and when it is applied (frame k+L)
  - the old and new template side by side
  - the jump of the box
  - a count of corrections, and the drift (FPGA box vs. corrected box) just before each one
- The bit-exact check must follow the template changes (each frame is checked with the template that was active on the FPGA).

## Part D: control panel (web page)
Controls on the page instead of command-line flags. They take effect without restarting:
- **Source:** OTB sequence list, or webcam. Restart, pause and loop buttons.
- **fps** (frame send rate).
- **Corrections:**
  - on/off
  - every N frames
  - latency L (frames or ms)
  - position only, or position + template
- **Re-select target:** draw a box (already works); on OTB, a "reset to ground truth" button.
- **Tracker:** shown read-only. Switching between ZSAD and S-3x8 means reprogramming (about 10 s over JTAG). A button that runs `make program-*` is possible if you want it.
- **Implementation:** a small JSON endpoint in demo.py that the page posts to; the main loop reads the settings each frame. Every change is logged to `frames.csv`, so runs can be reproduced.

## Order and checkpoints
1. **Part A.** Report the table (checkpoint).
2. **Part C step 1:** simulate a template/position update in the middle of a stream.
3. **Parts C and D** in demo.py and dash.py, tested with `--no-board`, then on the board. Screenshot and report (checkpoint).
4. **Part B,** after your ROI choice. Then re-run A (checkpoint).

Commits go to the board repo `ethernet-demo`, with no co-author line.

## Choices (user, 2026-10-06)
1. ROI 96×96 (recommended) for both trackers; S-3x8 is the priority.
2. Real OSTrack on the server GPU (the start of P4).
3. Position + template. User idea, kept for later as an experiment: when the request frame is old, update only the template and rely on a larger ROI.
4. Tracker-switch button that reprograms the board from the page: yes.

## Correction details (added after the choices)
- Use the locked hardware system rule **K3** (common/linksim.py, E45 simulate_lazy, decision 2026-10-06_E53_k3_for_hardware):
  - The request goes out at frame s = N, 2N, …, with the FPGA's position edge(s).
  - OSTrack runs ost-gated τ 0.6 (E49 GatedHeavy, .venv-heavy, separate process).
  - At s + L the correction is an offset, not a jump: p ← p_fpga(s+L) + heavy(s) − edge(s). The template is re-cut from frame s at heavy(s).
- This already handles part of the stale-position concern in choice 3, because the motion since frame s is kept.
- Default N, L = 30, 6 (the research L6N30). Both can be changed on the page.
- If OSTrack takes longer than L frames (about 27 ms per call, so normally it doesn't), the correction is applied when it is ready, and the delay is shown and logged.
- The loop is lockstep: frame t is sent, its result comes back, the corrections due at t are sent (position + template), then frame t+1 is sent. So the FPGA position is exact.
- With ROI 96 the demo is no longer the exact measured E53 setup (ROI 72). The ROI-72 bitstream stays available to compare against.
- The GPU is shared with E56 if it is still running. OSTrack in the demo uses about 1 GB.

## Open choices (answered above)
1. ROI size: for example S-3x8 72 → 96 (±40 px) and ZSAD 80 → 96? Or another size? Both trackers, or only S-3x8?
2. Correction source: (a) delayed ground truth now and OSTrack later, or (b) OSTrack straight away?
3. Correction content: position only, position + template, or both selectable (my suggestion: selectable)?
4. Should the tracker-switch button reprogram the board from the page?
