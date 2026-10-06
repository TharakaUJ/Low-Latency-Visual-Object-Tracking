# P3b results: tracker speed on the DE2-115, server corrections, demo control panel (2026-10-06/07)

Plan: `plan_P3b.md` (A speed, C corrections, D control panel; B ROI 96 deferred by the user). Board repo `~/Documents/Low-Latency-Visual-Object-Tracking`, branch `ethernet-demo`, commits 5f1d6a7 (speed test + S-3x8 fix) and 510785a (corrections + control panel). Full running log: `demo_log.md`.

## 1. Speed in one table
OTB Walking, real frames over 1 Gb/s Ethernet to the DE2-115. Every tracked result was checked against the bit-exact host model. "Clean" = every frame complete, tracked and FPGA = model.

| tracker (ROI) | crop | max clean rate | what limits it | FPGA: last row in → result | round trip (last row sent → result back) |
|---|---|---|---|---|---|
| **S-3x8** int8 CNN (72×72) | server (only the ROI is sent) | **1050 fps** | tracker core: 72 lines × 800 clocks at 62.5 MHz ≈ 0.92 ms per ROI | 0.79–0.80 ms | 0.84 ms |
| **S-3x8** | FPGA (whole 282×212 frame sent) | **500 fps** | the next crop needs the previous result; rows that arrive before it are lost | 0.54–0.63 ms | 0.74–0.92 ms |
| **ZSAD** 16×16 (80×80) | server | **3000 fps** (lossy at line rate, 6433 fps) | tracker core (~30 µs after the last row) | 5–31 µs | 0.05–0.10 ms |
| **ZSAD** | FPGA | **1629 fps** = the link | Ethernet: whole frames at line rate (59.8 kB each) | 0–2 µs | 0.24–0.30 ms |

- **Where the S-3x8 time goes:** the core needs at least 788 clocks per ROI line; rows are paced to 800 clocks.
- **S-3x8 headroom:** the E48 RTL has Fmax 77 MHz, so about 1300 fps would be possible at a faster clock. More would need parallel L1 units (separate RTL plan).
- **Model check:** at every rate, in all four sweeps, every tracked result is FPGA = model (after the fix in section 3). Frames that are dropped are flagged incomplete, never wrong.
- **Context:** the 30 fps the demo needs is 2 % of the S-3x8 server-crop limit.

## 2. Full sweeps (frames sent per step: 3 s of frames, 300 to 6000)
`sent`: frames/s actually sent. `tracked/s`: complete, tracked results per second. `FPGA t`: last row in → result, p50 µs. `rtt`: round trip p50 µs.

**S-3x8, server crop**

| target fps | sent | tracked / frames | FPGA = model | tracked/s | FPGA t | rtt |
|---|---|---|---|---|---|---|
| 30–1050 (9 steps) | = target | all | all | = target | 792–803 | 833–848 |
| 1100 | 1100 | 2846 / 3300 | 2846/2846 | 949 | 1730 | 1769 |
| 1200 | 1200 | 2749 / 3600 | 2749/2749 | 917 | 1641 | 1699 |
| 1500 | 1500 | 2253 / 4500 | 2253/2253 | 751 | 2017 | 2086 |
| 3000 | 3000 | 1502 / 6000 | 1502/1502 | 751 | 2359 | 2423 |
| line rate | 7566 | 3 / 6000 | 3/3 | 4 | 1615 | 1662 |

**S-3x8, FPGA crop**

| target fps | sent | tracked / frames | FPGA = model | tracked/s | FPGA t | rtt |
|---|---|---|---|---|---|---|
| 30–500 (5 steps) | = target | all | all | = target | 543–631 | 737–918 |
| 750 | 750 | 2249 / 2250 | 2249/2249 | 750 | 543 | 785 |
| 900–1200 | = target | half (every 2nd frame cut) | all | 450–600 | 541–553 | 844–885 |
| 1500 | 1500 | 1500 / 4500 | 1500/1500 | 500 | 812 | 1127 |
| line rate | 1628 | 2001 / 6000 | 2001/2001 | 543 | 869 | 1896 |

**ZSAD, server crop:** clean at every step from 30 to 3000 fps (FPGA t 5–32 µs, rtt 49–97 µs). At line rate (6433 fps) 4330 of 6000 frames were tracked (4643/s), all FPGA = model.

**ZSAD, FPGA crop:** clean at every step up to the link limit of 1629 fps (rtt ~0.3 ms, ~1.1 ms when the link is saturated).
- One exception: the first step (30 fps), run right after programming, got 201/300 results. Probably the link settling; every later step was complete.

## 3. Bug found by the speed test, fixed
- **Symptom:** S-3x8 FPGA crop at 1100 fps gave wrong results flagged as good: 208/1650, reproduced (219/1650 on a re-run). There were also 1–2 at 1150/1200. Every wrong frame followed a cut frame. Its score was below the model's minimum, always on candidate row 45.
- **Cause:** after a frame cut short, the E48 matcher can still be inside a 784-clock candidate-row job. `s3x8_core` waited only 256 clocks before `sof`. `sof` clears busy/acc but not the adder pipeline, so a partial row sum won the next frame.
- **Fix** (`s3x8_core.sv`): after a frame that did not end with `done`, wait `CUT_DRAIN_CLKS` = 1024 clocks. After a finished frame it is still 256, so full speed is unchanged.
- **Checks:**
  - Testbench s3x8: 46/46, with new sections 9 (cut mid-ROI), 10 (back-to-back burst) and 11 (cut at ROI rows 20..68).
  - Build: 60,757 LE (53 %), worst setup +0.094 ns.
  - Board: every step of both S-3x8 sweeps is FPGA = model (1100 fps FPGA crop: 1650/1650).
  - Note: the simulation did not reproduce the bug before the fix; the board run is the evidence.
- **Before/after:** `speed/speed_s3x8_fpga_Walking_before_drainfix/` vs `speed/speed_s3x8_fpga_Walking/`.

## 4. Server corrections (OSTrack) and the control panel
- **The heavy tracker:** real OSTrack-256 on the server GPU (RTX 2080), same configuration as the research loop: E45 `ost()`, E49 gated query τ 0.6.
  - About 14 ms per request (13–16 ms p50).
  - 1.23–1.26 GPU calls per request (research: 1.22–1.25).
  - About 5 s start-up.
- **The rule:** K3, the locked hardware system (decision 2026-10-06_E53_k3_for_hardware).
  - Every N frames: the FPGA position and the frame go to OSTrack.
  - L frames later: the position offset is applied (FPGA position + OSTrack − FPGA position at the request frame), plus, in mode "position + template", a template cut from the request frame.
  - A correction changes the host state only for what the board acknowledged (3 tries).
- **Board runs (all FPGA = model on every frame):**

  | run | frames | corrections | notes |
  |---|---|---|---|
  | S-3x8, FPGA crop, Walking, N 30, L 6, pos+tmpl (2 runs) | 411/411 each | 8/8 on time | drift at request 0.8–1.2 px; P@20 100 |
  | interactive: S-3x8 Walking → ZSAD Jumping (board reprogrammed from the page) → ZSAD server crop BlurOwl → S-3x8 Walking | 1300/1300, 551/551, 299/299 | N/L/fps changed live (N 10, L 15, 15 fps) | pause, loop, restart OK |
  | webcam, S-3x8 server crop, N 17, L 11, position only | 1039/1039 | 61 requested / 60 applied, none late, none rejected | 15 fps (camera limit, see below) |

- **Unexplained run:** the first corrections run lost ~30 % of the board's replies, and then had 23 mismatches after a template upload whose ack was lost. It was not reproduced in any later run. The server was loaded by other users' jobs at the time. The ack-checked corrections above were added because of it.
- **Page:**
  - control panel: source (any OTB-100 sequence or the webcam), tracker, crop, fps, pause, loop, reset to GT, corrections N/L/mode
  - on screen: request/applied banners, the OSTrack box, the previous template, request/apply markers on the plots, the drift plot
  - output: a session folder per run, and `controls.csv`
- **Webcam:** the camera itself delivers 15 fps in the dark room in manual exposure, and 7.5 fps in auto (MJPG and YUYV alike). The manual exposure value does not change the rate or the brightness. The demo is not the limit (OTB: 29.6 fps on the same code). Use a small target with contrast; a dark uniform patch gives a flat template.
- **Display:** 29.6–30 fps for OTB without recording; 27 fps with 1080p recording.

## 5. Regenerate
In `hardware/ethernet/` on the server:
- **Speed sweeps:** `make program-s3x8 && make speed TRACKER=s3x8 CROP=server` (and `CROP=fpga`; ZSAD likewise). Output goes to `results/speed_<tracker>_<crop>_Walking/` (summary.md, steps.csv, speed.png).
- **Testbench:** `make sim-s3x8` (46 checks, ~55 min).
- **Demo:** `make demo TRACKER=s3x8 CROP=fpga SEQ=Walking`, page http://100.76.229.14:8090/. Single scripted run: `cd host && python3 demo.py --tracker s3x8 --seq Walking --once`.

## 6. Open (next session; see NEXT_SESSION.md)
- **Overload:** dropping whole frames when the tracker is busy would keep ~1000/s above the limit instead of collapsing (RTL).
- **S-3x8 speed:** a faster clock (Fmax 77 MHz), or parallel matching (RTL plan).
- **FPGA-crop rate:** crop with the last known position when the result is late (changes the tracking rule).
- **User idea:** template-only correction with a larger ROI when the request frame is old (needs an experiment).
- **Deferred:** the ROI 96 search area (user: not needed for now).
- **Demo vs research setup:** the demo uses a 16 px target (research 20 px); its P@20 numbers are information only.
