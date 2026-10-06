# Ethernet HIL demo log

Plan: object_tracking/presentation/demo/plan_P0_P1.md (approved 2026-10-05).

## 2026-10-05
- P0: JTAG OK (USB-Blaster, device 020F70DD = EP4CE115). Branch ethernet-demo created from 9636bf3 (#17).
- Port ENET0, JP1 = 1-2 (RGMII), confirmed by the user. Link: option C (lab LAN 10.8.100.0/24).
- Board IP 10.8.100.230 chosen by me: nmap -sn shows hosts .6-.50 (the DHCP leases look low), plus .199, .215, .216, .240, .245-.248, .254. .230 gives no ping and no ARP reply (INCOMPLETE). Risk: DHCP could still hand it out later.
- verilog-ethernet cloned to hardware/ethernet/third_party/verilog-ethernet @ 77320a9 (upstream marked it deprecated; the code is unchanged).
- P1 step 1: example/DE2-115 copied to hardware/ethernet/p1_echo. Only change: local_ip 10.8.100.230, gateway 10.8.100.254, local_mac 02:00:0a:08:64:e6 (the default 02:00:00:00:00:00 is too generic for a shared LAN). The required IP change follows from option C; the MAC change is minor.
- Build of p1_echo: 5,570 LEs (5 %), 225,792 memory bits (6 %), timing met (worst setup slack 0.022 ns on the PLL clk[1] = 90-degree TX clock), no critical warnings.
- quartus_pgm over JTAG: configuration succeeded. quartus_pgm works.
- First test: no ARP reply from 10.8.100.230 (neigh FAILED), and 0/200 UDP echoes. Ping is not expected to work, because the example has no ICMP. Next: the user checks the cable and link LEDs on ENET0.
- User: ENET0 cable in, link LEDs on and blinking, LEDG all off, HEX all 0 (HEX shows the dest IP of the last UDP reply, so the board has never replied).
- Debug variant of p1_echo (rtl/fpga_core.v; the original is kept as fpga_core.v.echo_orig). LEDG[1:0] = MAC speed (0=10, 1=100, 2=1000), LEDG2 = good RX frame seen, LEDG3 = bad FCS seen, LEDG4 = bad frame seen, LEDG5 = ARP frame seen, LEDG6 = frame to our MAC seen, LEDG7 = TX frame sent (all sticky). HEX7..4 = bad-FCS count, HEX3..0 = good RX frame count (hex).
- Issue: the example quartus.mk rebuild loop uses the bash "let" builtin and hangs forever under /bin/sh (dash). Fix: run "make SHELL=/bin/bash".
- Debug build: timing met (worst 0.032 ns), programmed. Still 0/20 UDP replies and ARP INCOMPLETE. Waiting for the user to read the LEDs.
- Mistake: I ran "pkill -f make -u tharaka" on the server to stop the hung build. It also killed my own SSH command and would have killed any other process of the user's with "make" in its command line.
- LED readout: LEDG1 (speed = 1000), LEDG2 (good RX), LEDG5 (ARP seen). Off: LEDG3/4 (no bad FCS or bad frames), LEDG6 (no unicast to our MAC), LEDG7 (never transmitted). The good-frame count was climbing (0x202).
- Broadcast test: the server sent 4096 UDP broadcasts to 10.8.100.255:1234 over about 5 s. The board count went from 0x202 to 0x373 (+369), which is background traffic only. The broadcasts did not arrive, and 0 replies came back.
- Conclusion: the board's RGMII RX works (1 Gb/s, no FCS errors). But the server's frames, broadcasts included, do not reach the board's wall port. The board is on a different L2 segment or VLAN from the server's eno1. This is not an FPGA fault. The TX path is still untested.
- Hex IP readout (SW15/SW14 select; SW0/SW1 do not work on this board): last RX src 10.8.96.203, dst 239.255.255.250 (SSDP). The board's port appeared to be on 10.8.96.x. The server reaches 10.8.96.0/24 through the router in one hop. I proposed moving the board to 10.8.96.120; not approved and not needed.
- The user re-seated the Ethernet cable and I reflashed. Now ARP resolves (02:00:0a:08:64:e6 REACHABLE), 50/50 unicast echoes and 4096/4096 broadcast echoes come back. The cause was the cable or jack, not the FPGA.
- P1 step 1 PASSED: 2000 echoes of 1024 B random data: 2000 ok, 0 corrupt, 0 lost. RTT p50 121 us, p95 152, p99 158, max 273 (Python socket, single packet in flight, lab LAN).
- P1 step 2: new design hardware/ethernet/p1_rows = p1_echo (with the debug LEDs) + rtl/row_stats.v replacing the UDP echo and FIFO (applied by p1_rows/rows_patch.py). Build: 6,882 LEs (6 %), timing met (worst setup slack 0.055 ns, PLL clk[0]); the only row_stats warnings are intended counter truncations. Hex default view = frames done | rows bad; SW15+SW14 both up = MAC bad-FCS | good counts.
- Protocol addition vs the plan: the downlink header also carries height u16 (magic, frame_id, row, width, height), so the FPGA knows when a frame ends; the result has 40 bytes (adds flags, height, width; x/y/score = 0). Duplicate rows are not detected (no row bitmap).
- No RTL simulation: there is no iverilog on the server and Questa has no license. Tested on the board directly.
- Host script hardware/ethernet/host/eth_loopback.py. First version measured RTT ~10.8 ms: an artifact of the busy-wait pacing holding the Python GIL (receiver thread waited for the 5 ms switch interval). Fixed: kernel SO_TIMESTAMPNS receive stamps, sleep-based pacing, and an fps formula over N-1 intervals.
- SANITY (10 frames 640x480, 30 fps; results/sanity_random and sanity_ramp): 10/10 results, all 480 rows, 0 bad rows, 0 checksum mismatches, for both patterns. 73.7 Mbit/s pixels. RTT from the last row sent to the result: p50 ~571 us (max 623). The host enqueues a frame in ~2.29 ms but the FPGA receives it over ~2.77 ms (line rate), so ~490 us of the RTT is the NIC queue draining. FPGA last row -> result = 0 cycles (no compute in P1).
- The user approved the long runs and said they will install iverilog (sudo needs a password, so I did not).
- LONG 30 fps (results/long_fps30, 333 s): 10000/10000 results, all frames complete, 0 bad rows, 0 checksum mismatches, 0 lost, 30.0 fps, 73.7 Mbit/s pixels (~83 on the wire). RTT from the last row sent: p50 573, p95 614, p99 645, max 736 us. From the first row sent: p50 2857, max 4506 us.
- LONG max rate (results/long_max, run uncapped as in the plan, 27.7 s): 10000/10000, 0 bad, 0 mismatches, 0 lost, 360.7 fps, 886 Mbit/s pixels (~994 on the wire = gigabit line rate). RTT from the last row: p50 574, p99 612, max 654 us. The FPGA receives a frame in 2772 us (line rate); the link, not the FPGA, is the limit.
- Note: my "wait until done" loop used pgrep -f with a pattern that matched its own command line, so it never ended. I killed exactly those 2 PIDs (70684, 70773).
- P1 DONE. Regenerate: make -C hardware/ethernet/p1_rows SHELL=/bin/bash; quartus_pgm --mode=jtag -o "P;hardware/ethernet/p1_rows/fpga/fpga.sof"; python3 hardware/ethernet/host/eth_loopback.py --fps 30 --frames 10000 --out results/long_fps30 (and --fps 0 for max).
- The user asked for fault injection (and installed iverilog 11.0 and verilator 4.038).
- Python reference model host/row_model.py (same rules as rtl/row_stats.v). Shared cases host/fault_cases.py: 20 cases (skipped, bad, short, long and truncated rows, an empty UDP packet, width 0, row >= height, height 0, an early-ended frame, a bad row with no open frame, a duplicate row (the known limitation), another UDP port, swapped rows, width 1460, frame_id wrap, two interleaved frames, bad Ethernet FCS (testbench only), and a final good frame). Each case ends with a 1-row flush frame.
- cocotb testbench p1_rows/tb/test_p1_rows.py (venv hardware/ethernet/.venv-sim: cocotb 1.9.2, cocotbext-eth 0.1.28, scapy; iverilog). It runs fpga_core (MAC + UDP + row_stats) over a simulated RGMII PHY. First run: 0 results. Testbench bug: the ARP reply to the board was queued behind all case packets, so the board's ARP lookup timed out and its results were dropped. Fixed with an ARP warm-up frame. Then **20/20 cases PASS**, bit-exact against the model, in 14 s.
- Board: host/eth_faults.py (same cases, minus the FCS case) -> **19/19 PASS** (results/faults/summary.md).
- Confirmed: an empty UDP payload is dropped by udp_ip_rx (header early termination) and cannot hang row_stats.
- Run: cd hardware/ethernet/p1_rows/tb && ../../.venv-sim/bin/pytest -q test_p1_rows.py ; python3 hardware/ethernet/host/eth_faults.py --out results/faults
- User decisions for P2: ZSAD first; crop on the server for the demo (in the real system it belongs in the FPGA; say so on screen); source OTB replay now, webcam later (none plugged in yet).

## 2026-10-05 (P2)
- P2 plan (presentation/demo/plan_P2.md) approved by the user. Choices: MJPEG page + MP4, ROI 80x80 (+-32), OTB sequences picked from an offline model run over all of OTB2015 (full table shown), git unstaged + .gitignore (the user staged them; nothing committed). The user will commit the P1 work themselves.
- 2026-10-06 P2 implementation:
  - Offline ZSAD over OTB-100 (host/zsad_offline.py; results/p2_offline/summary.md, all 100 targets): mean P@20 34.7, median 23.9, mean fixed-box AUC 27.1 (information only). Demo picks: Walking (P@20 95.9), Jumping (99.4), BlurOwl (98.9), and Bolt (1.1, the failure case); all four have scaled frames larger than the ROI. Caveat: some top scorers (e.g. Dancer2 67x54) have scaled frames smaller than the 80x80 ROI, so their "ROI" search is a full-frame search.
  - Scale: plan default of 16 px. Note: the research loaders use 20 px (common/otb_loader TARGET_SIZE); --target-px is a flag.
  - RTL hardware/ethernet/p2_zsad: rtl/row_stats.v (P2: tracker FIFO, template packets, waits for the tracker result), rtl/zsad_core.sv (wrapper; uses hardware/rtl/processing/window_buffer, line_buffer, template_match UNCHANGED; RADIUS 0), one axis_async_fifo (16-bit words, frame mode, drop bad), PLL clk2 for the tracker. common/quartus.mk now maps .sv -> SYSTEMVERILOG_FILE (p2 copy only).
  - Tracker clock: started at 62.5 MHz as planned; template_match's Fmax is 47.2 MHz (worst path: sumT, the 256-term template sum) -> 41.67 MHz (50*5/6). No timing exceptions, user files unchanged.
  - 125 MHz timing fixes in row_stats (all mine): staging register before r_shift, registered timeout compare, precomputed last-row flag, frame-size checks registered at the header end. Final: setup slack clk[0] +0.074 ns (slow 85C), tracker clk[2] +2.4 ns, Fmax clk[2] 46.2 MHz, hold OK at all corners. 29,603 LEs (26 %), 292,764 memory bits (7 %), 0 multipliers, 0 critical warnings except 1 in sta (same as P1).
  - Toolchain: iverilog 11 (apt) and 13 cannot compile template_match.sv (whole unpacked-array copies). Installed in user space (no sudo): micromamba at ~/tools/mamba, env hdl = iverilog 13.0 + Verilator 5.052 (conda-forge). The P2 testbench uses Verilator; the P1 testbench still uses icarus (apt).
  - P2 testbench p2_zsad/tb/test_p2_zsad.py (Verilator): 20/20 PASS against host/zsad_model.py (bit-exact ZSAD). Bugs found by it: (1) mine, zsad_core: the frame_done pulse coincided with the first pixel when the FIFO was full, so window_buffer skipped a column (x off by one); fixed with a 1-cycle ST_GAP after each new_frame word. (2) A testbench pacing problem exposed a real limit: row_stats stops RX while it waits for the tracker, so back-to-back ROI frames at line rate overflow the MAC RX FIFO (the rows are dropped and reported as incomplete frames). Limit recorded: one tracked frame in flight; the host paces frames (30 fps, 33 ms apart; the tracker needs ~0.05-0.15 ms). The testbench now waits for each result like the host.
  - Board (p2 sof programmed): host/board_link.py + host/p2_board_check.py. SANITY: Walking, 50 frames at 30 fps: FPGA = model 50/50, FPGA compute after the last row 2.5 us (the tracker keeps up with the Python row sender), round trip p50 82 us / max 134 us, P@20 100 (info). Bolt, 50 frames: 50/50, no rejects (it drifts without rejecting), P@20 8.0. Reject path: 5 pure-noise ROIs, 5/5 agree (score ~18k > 8192, not good). P1 regression on the P2 bitstream: loopback 300/300 frames OK, fault cases 19/19.
- 2026-10-06 P2 sanity checkpoint shown to the user. User: keep 16 px; go ahead with the demo app.
- Demo app host/demo_zsad.py: OTB replay (GT first box) or webcam (box drawn on the web page, or --init-box; untested, no webcam yet). The MJPEG page is bound to the Tailscale IP only (http://100.76.229.14:8090/), and an MP4 is recorded. Overlay: FPGA = model per frame and running count, ZSAD score, FPGA compute vs network round trip, fps, "scaling + ROI crop on the server" note, colour legend. Checked from the laptop over Tailscale: the page streams at ~30 fps.
- Loop check (Jumping, --loop, 3875 frames incl. 103 rejects): FPGA = model 3875/3875. Stopped with SIGINT (first kill hit the bash wrapper PID; the python PID was then stopped by exact PID).
- FULL RUNS (results/demo_<seq>/: summary.md, frames.csv, demo.mp4 (mp4v), demo_h264.mp4, snapshot.jpg), 30 fps, whole sequences:
  | seq | frames | FPGA = model | rejects | FPGA compute p50/max (us) | RTT p50/p99/max (us) | P@20 | AUC |
  | Walking | 411 | 411/411 | 0 | 2.5/6.3 | 81/156/172 | 95.9 | 53.2 |
  | Jumping | 312 | 312/312 | 8 | 2.5/5.7 | 90/153/162 | 99.4 | 70.7 |
  | BlurOwl | 630 | 630/630 | 7 | 2.5/5.9 | 82/152/162 | 98.9 | 79.8 |
  | Bolt | 349 | 349/349 | 0 | 2.5/6.2 | 84/153/156 | 1.1 | 0.9 |
  (numbers from the re-recorded run after shortening the legend; tracking is deterministic and the first recording gave the same P@20/AUC; P@20/AUC are identical to the offline model run.)
- Reading of "FPGA compute": t_result - t_rx_end = time after the LAST row arrives. The tracker consumes pixels as they stream (41.67 Mpx/s), faster than the Python host sends rows, so only the last row plus the pipeline drain remain (~2.5 us). The total tracker work for one 80x80 frame is ~6480 clocks = ~155 us at 41.67 MHz, overlapped with reception.
- 2026-10-06 P2 full results discussed. User: webcam next time; run diagnostic 2 (line-rate stress); update .gitignore (added: results/**/*.mp4, results/**/*.bin, host/burst_send). Three timestamped demo_Walking_2026... result dirs are not mine (probably the user's own runs); left untouched.
- Line-rate stress (host/p2_stress.py + host/burst_send.c, sendmmsg = one call per 80-row frame; crops = 411 real Walking crops along the model's track, cycled):
  - one in flight, 5000 frames: 5000/5000 complete and tracked, FPGA = model 5000/5000. Rows arrive in 119 us p50 (line rate ~101 us). Last row -> result 38.0 us p50 (p99 44.3, max 49.2). First row -> result 156.8 us p50 = the tracker's own time (6480 clocks / 41.67 MHz = 155.5 us), so the tracker, not the link, is the bottleneck. 4186 tracked frames/s (compute limit ~6400/s; the rest is round trip + host turnaround). Round trip after the last row sent 82 us p50, max 187.
  - burst, 2000 frames back to back at ~7840 frames/s offered: 1015 complete + tracked (FPGA = model 1015/1015), 985 incomplete (29,608 rows dropped by the MAC RX FIFO while row_stats waited for the tracker), tracked rate 3981/s, no timeouts, no wrong results. This confirms the one-in-flight limit: overload costs frames (reported as incomplete), never correctness.
- 2026-10-06 (evening) P3a, scope set by the user: crop in the RTL, removing the in-flight limit at the end, S-3x8 swappable with ZSAD, Makefile + docs, commits without co-author. Board unplugged: simulation only. Design notes: object_tracking/presentation/demo/plan_P3a.md.
  - New hardware/ethernet/p3_track: rtl/row_stats.v (P3: ROI crop in the RTL, FPGA-held position, template chunks 0x5AA6 + offset, set position 0x5AA7, 44-byte results, one pending result instead of blocking), rtl/zsad_core.sv (tag-3 offsets), rtl/s3x8_core.sv (wraps E48 s3x8_top.v, unchanged and byte-identical; rows paced to 800 clocks), fpga_core/fpga.v with `TRACKER_S3X8` (s3x8: ROI 72, MARGIN 4, 2048-byte template, clk_trk 62.5 MHz; zsad: ROI 80, MARGIN 0, 256 B, 41.67 MHz). Quartus projects fpga_zsad/, fpga_s3x8/.
  - Host: host/trackers.py (ZsadModel, S3x8Model with the same API; S-3x8 = the E48 integer model in numpy, weights host/models/s3x8_qlayers_8.json), board_link3.py, check3.py, demo.py (--tracker, --crop). The S-3x8 host model is bit-exact with the E48 rtl_case0-2 (features and match).
  - Builds (first RTL version): zsad 30,624 LE (27 %), setup -0.936 ns on clk[0] (fails); s3x8 62,244 LE (54 %), 60 mult (11 %), 406 kbit, all clocks met (clk[0] +0.291, clk_trk +5.27 ns). Timing fixes written but NOT rebuilt: precomputed packet lengths, origin clamp split over two header cycles, UDP checksum generator off.
  - Lint: Verilator clean for both builds.
  - P3 ZSAD testbench (tb/test_p3.py, Verilator): FAILS. Bug 1 found and fixed: the "<12-byte packet = bad" rule also rejected the 6-byte set-position packet. Open bug: for the first FPGA-crop frame the tracker never returns a result (receiver timeout after 10 ms, flags 0x31), the next frame loses rows during that stall, and no results arrive after it. Suspect the tracker side (FIFO -> zsad_core) stops consuming. Debug plan: docs/NEXT_SESSION.md. The s3x8 testbench has not been run yet.
  - Makefile (hardware/ethernet/Makefile: build/program/sim/check/demo for P1-P3) and README.md written. .gitignore: p3 build outputs, sim_build_*, sim_*.log.
  - Stopped here at the user's request ("at a good enough checkpoint stop").

## 2026-10-06 (day) P3a continued
- User: "work on rtl finish the demo implementation" (continue P3a).
- Bug 2 (row_stats, the P3 stall): with the crop in the RTL the tracker finishes while the rows below the ROI still arrive, i.e. before its frame takes the pending slot; the 1-clock result pulse was only accepted while a slot was pending, so it was lost -> 10 ms timeout (flags 0x31) -> receiver stalled -> MAC FIFO overflow (21/120 rows) -> every later cropped frame the same. Fix: latch the result (tag, x, y, score); match it to the pending tag later; latch cleared at each new_frame ctrl word (tags wrap at 16).
- Testbench bug: frame() waited for "n0 + 1 results"; the close result of an incomplete frame counted, so every later wait was one result early (and the back-to-back pair started with the tracker still busy -> 12 rows lost in frame 1019). Fix: wait for the frame's own frame_id (wait_fids). Mismatch dumps added (tb/mismatch_<tracker>_<fid>.npz: ROI, template, origin, exp, got).
- Cosmetic: untracked frames smaller than the ROI reported a negative origin (65526, 65516); now 0.
- ZSAD testbench after these: 28/28 PASS (sim ~4 min).
- Bug 3 (s3x8_core): first S-3x8 run: same score as the model but x one less (frame 1000: 53 vs 54, score 1998; model neighbours 9826/9757, so not a tie). The ROI reached s3x8_top shifted by one column: the registered sof pulse coincided with the first pixel (same bug as P2's zsad_core ST_GAP). Fix: ST_GAP after ST_SOF.
- ZSAD build with the timing fixes: 29,030 LE (25 %), but setup still fails: clk[0] -0.221 ns (row_stats ROI clamp a_y -> p_oy) and clk[1] -0.602 ns (verilog-ethernet rgmii_phy_if rgmii_tx_clk_2 -> TX clock DDIO, 2 ns clk[0]->clk[1] window, 1.56 ns routing = placement; P1/P2 met it at +0.02). Fix for clk[0]: clamp compares moved to S_HDR_A (S_HDR_A2 = mux only; logically equal). For clk[1]: fitter seeds 1/2/3 built in parallel (fpga_zsad, fpga_zsad_s2, fpga_zsad_s3).
- Timing: clk[1] (RGMII TX clock DDIO path) is placement-dependent: ZSAD seed 1 -0.459, seed 2 +0.125, seed 3 -0.757 ns. **ZSAD adopted with seed 2** (fpga_zsad/Makefile adds ../seed_2.qsf): all corners met (worst setup +0.020 clk[0] slow 85C, hold +0.127 fast), 29,028 LE (25 %), 274 kbit, 0 mult. ZSAD testbench on this RTL: 28/28.
- S-3x8 build (default seed) meets all corners: 60,666 LE (53 %), 60 mult (11 %), 388 kbit; seed 2 also met (removed).
- S-3x8 testbench after the sof gap fix: 24/28; crop frames exact. Remaining:
  - after the untracked out-of-order frame the testbench sent the next 112-row frame at once; S-3x8 needs ~0.92 ms per ROI (800 clocks/line), two ROI frames (~10.5 k words) > 8192-word FIFO -> backpressure -> MAC FIFO dropped rows (frame 1011: 96/112). Throughput limit, not logic. Fix: tracker FIFO 16384 words for the S-3x8 build only (ZSAD unchanged).
  - 2nd frame of each back-to-back pair: same score, x +5 (shifted stream) when sof follows done with no idle clocks (frames after a pause are exact). Fix: s3x8_core always drains 256 clocks before sof.
- **Final simulation (all on the same RTL): ZSAD 28/28, S-3x8 28/28** (FPGA = model on every tracked frame: crop at the borders, set-position, out-of-order / incomplete / small / P1 frames, server crop, back-to-back pairs, template mid-frame). Tracker time after the last row: ZSAD 2..13,883 cycles (125 MHz), S-3x8 91,075..207,442 (0.73-1.66 ms; ~0.92 ms per ROI by design).
- **Final builds, all timing corners met (setup/hold, slow 85C/0C, fast 0C):**
  | build | LE | memory bits | mult 9-bit | worst setup slack |
  | ZSAD (seed 2) | 29,028 (25 %) | 274,332 (7 %) | 0 | +0.020 ns clk[0] |
  | S-3x8 (default seed) | 60,718 (53 %) | 527,232 (13 %) | 60 (11 %) | +0.118 ns clk[1] |
- Known limits: S-3x8 throughput ~1 ROI per 0.92 ms (FIFO holds 2 ROI frames; more back to back = dropped rows, reported as incomplete frames, never wrong results). The clk[1] RGMII path is seed-sensitive: a future change can need another seed. A tracker timeout still stalls the receiver (up to 10 ms) at the next cropped frame.
- Not done: board tests (board unplugged). Next session: docs/NEXT_SESSION.md.

## 2026-10-06 (evening) webcam, no-board mode, flash
- Webcam (icSpring 32e6:9211, /dev/video0): first not readable over SSH (ACL only for the desktop user); the user added tharaka to the video group. Formats MJPG/YUYV up to 1280x720 at 30 fps. In this dim room auto exposure (aperture priority) gives 15 fps (MJPG and YUYV alike); manual exposure 25 ms + gain 48 gives 30 fps but a darker image (mean 38 vs 60). Camera controls restored to auto/gain 0 afterwards.
- demo.py: `--no-board` (host model instead of the FPGA; labelled "NO BOARD: host model only, not the FPGA" on screen, "FPGA = model: n/a" in the summary); webcam via V4L2 MJPG, `--cam-size`, `--cam-exposure`, `--cam-gain`, buffer of 1 frame; the overlay names the tracker (it said "ZSAD" for S-3x8 too). OTB Walking no-board: ZSAD P@20 95.9 (= board P2 run), S-3x8 100.0; the S-3x8 Python model runs ~25 fps.
- Webcam no-board run (ZSAD, box drawn on the page): 1070 frames, 5 rejects; user: "yes it works".
- Board: only one of USB-Blaster or Ethernet can be connected (cable length). User chose to write the design to the EPCS64 flash, and asked to back up the factory test-pattern image first so it can be restored when the board is returned.
  - .jic files built (quartus_cpf, EPCS64, SFL for EP4CE115 is installed). ZSAD rebuilt from the final sources to be sure: identical timing and LE count (deterministic).
  - Makefile: flash-backup (examine EPCS64 -> ~/fpga_flash_backup/de2_115_epcs64_factory.pof + sha256, never overwrites), flash-check-backup (verify flash vs backup), flash-zsad / flash-s3x8 (refuse without a backup), flash-restore. README section "Flash".
  - Bug found: `make program-*` never worked (pattern rules are skipped for .PHONY targets: "Nothing to be done"); now static pattern rules, dry-runs OK.
  - Not yet tried on hardware (USB-Blaster not connected): whether examine (IE) and verify/program (IV/IPV) accept the .pof backup format. Checked first in the flash session, before anything is written.

## 2026-10-06 (night) full board test (Ethernet + JTAG both connected) and the dashboard
- User connected both cables (no flash needed). Board tests, results in hardware/ethernet/results/recheck_20261006/ and results/p3_check_*:
  | # | test | result |
  | 1 | JTAG | EP4CE115 (020F70DD); `make program-*` works on hardware after the static-pattern fix |
  | 2 | P1 loopback 1000 frames 30 fps | 1000/1000 OK, 0 lost/bad/checksum; RTT p50 584 us |
  | 3 | P1 faults | 19/19 |
  | 4 | P2 Walking 50 | 50/50 FPGA = model |
  | 5-7 | P3 ZSAD check-all (4 seq x fpga/server crop, full sequences) | 3404/3404 FPGA = model; result 0-3 us after the last row (RTL crop); P@20 Walking 95.9, Jumping 99.4, BlurOwl 98.9, Bolt 1.1 (= P2) |
  | 8-9 | P3 S-3x8 check-all | 3404/3404 FPGA = model; result 0.29-0.67 ms after the last row; LEDR17 (overrun) off (user); P@20 100 / 100 / 99.8 / 1.4 |
  | 10 | live demo S-3x8 RTL crop, Walking loop, on the server monitor | 2231/2231 |
  | 11 | webcam on the board, S-3x8 RTL crop | 3532/3532; user: "webcam works" |
- The monitor is on the server (user logged in on the desktop as tharaka, X11 :1); Firefox opened there from SSH.
- User: do both fixes (30 fps; full-screen page) and "display every possible thing including the templates".
  - 30 fps: the host now follows the FPGA's own result; the bit-exact model check runs in 4 worker processes (every frame still checked, shown with its lag). trackers.py: match() now calls inspect() (same arithmetic; also returns the score map and, for S-3x8, the ROI features). Board runs after the change: S-3x8 and ZSAD Walking 411/411 checked, P@20 unchanged (100.0 / 95.9), display 29.7 / 30.0 fps with 1080p recording.
  - Page: the image is scaled to the window (aspect kept; box drawing maps back); a new box can be drawn at any time to re-select the target (webcam).
  - host/dash.py: 1920x1080 dashboard: camera view (boxes, GT, ROI), FPGA input (whole scaled gray frame + ROI), ROI with the FPGA's best window, model score map (frame shown), template (gray patch; S-3x8 int8 features, 8 ch), ROI features (S-3x8) or best window + |zero-mean diff| (ZSAD), status with decoded flags, rows, origin, FPGA receive time, compute after the last row, round trip, plots of score / FPGA time / round trip / display fps.
  - Webcam dashboard at night: 597/597 checked but display 8.2 fps: the room is darker and auto exposure stretches the camera frames (OTB runs at 30 fps with the same code). Remedy: --cam-exposure 250 --cam-gain 48 (not applied, the user's target was selected).

## 2026-10-06 (late night) P3b part A: speed test (plan_P3b.md, approved "yes go ahead, start with the speed test")
- User choices for P3b: ROI 96 (both, S-3x8 first), real OSTrack corrections (K3 rule, ost-gated 0.6), position + template, tracker-switch button. User idea kept for later: template-only correction with a larger ROI when the request frame is old.
- New tools: host/speed_send.c (paced C sender, sendmmsg per frame, receiver thread with kernel timestamps), host/speed3.py (rate sweep, every tracked result checked against the bit-exact model on its own; FPGA crop also checks the origin rule), `make speed TRACKER=.. CROP=..`. System matplotlib is broken on the server (numpy ABI): plots go through the research .venv.
- Results (Walking, 72x72 / 80x80 ROI; full frame 282x212 = 59.8 kB), results/speed_<tracker>_<crop>_Walking:
  | tracker / crop | max clean rate | limit |
  | S-3x8 server | 1050 fps (1100: 16 % incomplete) | core 72 lines x 800 clk @ 62.5 MHz ≈ 0.92 ms |
  | S-3x8 fpga | 500 fps (750: 4 % incomplete; >= 900 every 2nd frame cut) | next crop needs the previous result; rows arriving before it are lost |
  | ZSAD server | 3000 fps (line rate 6433: 28 % cut) | core ~30 us after the last row |
  | ZSAD fpga | 1629 fps = the link (whole frames at line rate) | Ethernet |
  Latency at normal rates: S-3x8 0.79 ms after the last row, round trip 0.87 ms; ZSAD server 5-30 us / 0.09 ms, ZSAD fpga crop 0-2 us / 0.3 ms.
- ZSAD fpga crop: the first step (30 fps) after programming got 201/300 results (frames lost at the start, probably the link after programming); every later step was complete.
- **Bug found: S-3x8 FPGA crop at 1100-1200 fps gave wrong results flagged complete + tracked** (1100: 208/1650 and 219/1650 on two runs; 1150: 2; 1200: 1). All other steps and all server-crop steps 100 % FPGA = model.
  - Pattern: the frame before was cut (incomplete); FPGA score far below the model's minimum; reported candidate row always 45; no row/column/stream shift and no mix with the previous frame explains it.
  - Cause (from the E48 matcher source): after a cut frame the matcher can be in a candidate-row job (784 clk). s3x8_core drained only 256 clk before sof; sof clears busy/acc but not the adder pipeline, so the tail of the old job accumulates a partial row sum into the new frame and wins the compare.
  - Fix (user: "if it too much of a fix, note it ... otherwise fix it"): s3x8_core drains CUT_DRAIN_CLKS = 1024 after a frame that did not end with done (256 after a finished frame, so full speed is unchanged). Testbench sections 9 (cut mid-ROI), 10 (burst of back-to-back frames, each result checked on its own), 11 (cut at ROI rows 20..68 step 4, each followed by a full frame). The simulation did not reproduce the bug before the fix (sections 9 and 10 passed on the old RTL); the board re-run is the real check.
- Noted for later (not fixed): above the limit throughput collapses (S-3x8 server: 3000 fps sent -> 16 tracked/s) because cut frames still use the tracker; dropping whole frames when the tracker is busy would keep ~1000/s.
- After the fix (board, 2026-10-07 ~00:00): S-3x8 FPGA crop sweep 100 % FPGA = model at every step (1100 fps: 1650/1650; clean max still 500 fps, limited by the result dependency); server crop unchanged (clean 1050). Build: 60,757 LE (53 %), worst setup +0.094 ns. Testbench s3x8 46/46 (sections 1-11). Commit 5f1d6a7 (board repo, no co-author). Copies: presentation/demo/speed/.

## 2026-10-07 (night) P3b parts C + D: OSTrack corrections and the control panel (user: "yes go ahead with part C")
- host/heavy_server.py runs OSTrack-256 in the research .venv-heavy (GPU). It reuses E45 ost() (official weights; peak = score-map max) and the E49 gated query (search at the FPGA position with the heavy's own box size; if the peak < 0.6, search again at the heavy's own box; keep the higher peak). Standalone on Walking: about 13 ms per call after warm-up (the first call takes 270 ms, so init now does one warm-up call); boxes within a few px of GT. Start-up about 5 s.
- host/corrections.py implements the K3 rule as in linksim/E45 simulate_lazy. The request goes out at frame s = multiple of N, with the FPGA position edge(s) and frame s. At s + L, or when the answer arrives if later ("late"), it applies p <- p_fpga + heavy(s) - edge(s), clipped, and in pos+tmpl mode a template re-cut from frame s at heavy(s), the same cut as the initial one.
  - Order per frame: track, then apply the due corrections (set position + template upload, before the next frame), then request. This is the research order.
  - Request ids are unique over the run, so a late answer from an old session cannot match a new one.
- demo.py is restructured into sessions. The control panel on the page has: source (any OTB-100 sequence lazily read, or webcam), tracker, crop, start/switch, restart, pause, reset to GT, loop, fps, and corrections on/off with N, L and mode.
  - A tracker switch runs `make program-<t>`.
  - Each session gets its own folder: frames.csv (with request/applied columns), corrections.csv, summary.md and demo.mp4. controls.csv logs every change.
  - SIGTERM/SIGINT stop cleanly. The page reconnects the stream after a restart.
- dash.py shows:
  - banners for each request and applied correction (bottom of the camera view)
  - the magenta OSTrack box (at its request frame)
  - a magenta frame around a new template, with the previous template next to it
  - request/apply lines on all plots and a plot of the drift at each request
  - a two-line corrections status
- Board tests (S-3x8 bitstream unless noted; results/p3b_*):
  - **try1 (first run, video on):** 119/411 frames had no result (1 s timeouts) from frame 1 on, and 23 mismatches after the correction at frame 306 (FPGA scores differ = FPGA template != host template).
    - Not reproduced in 3 further runs with the same and lighter settings (411/411 each; corrections 8/8 on time).
    - The board was healthy right after (make check 100/100). Other users' jobs were running on the server (a niced tracker process at 100 % CPU, an iverilog vvp at 100 %).
    - Cause unknown (transient packet loss host <-> board; the mismatches follow from a template upload whose ack was lost while the host had already switched templates).
    - Fix for that part: a correction now retries up to 3 times and changes the host's position/template only for what the board acknowledged; otherwise a red banner, counted as "not acknowledged".
  - **try2/try3:** 411/411 FPGA = model, P@20 100. 8 corrections, all on time, drift at the request 0.8-1.2 px (scaled), OSTrack 13.7 ms p50, 1.23-1.25 GPU calls per request (cf. research 1.22-1.25). Display 30.0 fps without video, 27.1 with video.
  - **Interactive (loop, no video):**
    - Session 1 S-3x8 fpga Walking: 1300/1300. N=10, L=15, 15 fps changed live.
    - Session 2: ZSAD switch (board reprogrammed from the page), Jumping: 551/551.
    - Session 3: ZSAD server crop BlurOwl: 299/299.
    - Session 4: back to S-3x8 Walking.
    - Pause/resume OK.
    - Webcam: "cannot open webcam 0", handled on the page; the camera is unplugged (no /dev/video*), so the webcam path through the page is untested.
  - Live now on the server monitor: S-3x8 Walking loop with corrections N=30, L=6 (results/p3b_live); 713/713 at the screenshot, 29.6 fps.
- Notes:
  - OSTrack takes about 5 s to load at demo start, so the first request of the first session comes around frame 180.
  - The demo scales the target to 16 px (research 20 px) and the S-3x8 ROI is still 72 (part B, ROI 96, not started).
- Commit 510785a (board repo, no co-author). Screens: presentation/demo/screens/p3b_*.png.
- User 2026-10-07: "no need for 96x96 for now". Part B (larger ROI) deferred; the demo keeps ROI 72 (S-3x8) / 80 (ZSAD). P3b closed otherwise.
- Webcam test through the page (2026-10-07 ~01:40; user drew the boxes; webcam plugged in again):
  - Page switch OTB -> webcam (in the user's session 59: S-3x8, server crop, N=17, L=11, position only): 991/991 FPGA = model, 58 requests / 56 applied, display 7.7 fps (auto exposure, dark room).
  - Restart with --cam-exposure 250 --cam-gain 48: 210/210, corrections every 17 frames applied on time, display 14.9 fps.
  - Camera alone (demo stopped), 640x480: MJPG and YUYV both 15.0 fps in manual exposure, 7.5-7.8 fps in auto. Manual exposure 5..300 changes neither the rate nor the brightness, so this camera caps itself at 15 fps in low light. The demo is not the limit (OTB runs at 29.6 fps); in a bright room it should give 30.
  - The first target box was on a dark, low-texture area (uniform template, score ~2600 standing still): use a small object with contrast.
