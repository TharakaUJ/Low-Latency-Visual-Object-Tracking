# Progress log

Dated entries, one per executed step: what was run, result, artifacts.

## 2026-09-26 — Phase 0: generator + golden model

- `gen_tcnn.py tinycnn_qat_int4.onnx --outdir gen --cin-par 3,16,8,16`:
  4 conv layers extracted via `fpga_cnn_pipeline/onnx_to_rtl.py`'s
  `find_conv_chain()`/`quantize_multiplier()`. All 4 layers land at exactly
  1024 cycles/tile with CIN_PAR=[3,16,8,16] (NPASS=[1,1,2,2]) — matches the
  plan's schedule table. GAP requant: M0=1140694085, shift=33.
- `ref/int_model.py`: bit-exact integer model that unpacks the same
  lane-packed `w_L*.hex` ROM format the RTL will read (not the ONNX tensors
  directly), so a packing bug in `gen_tcnn.py` would be caught here.
- **Gate P0**: `ref/check_agreement.py` (5000 random + 5000 real-image-crop
  patches) — within ±1 LSB: 99.98%, argmax agreement: 100.00%. **PASS**
  (gate: ≥99.5% both). Report: `results/P0/agreement.txt`.
- `ref/make_vectors.py`: 1000 tiles + expected logits (`vectors/tiles*.hex`),
  per-layer dump of tile 0, 10,005 requant vectors, a 640×48 strip from
  `002675.jpg` with its 1200-tile stride-16 640×480 expected CSV (replayed
  `row % 48`), and a small 64×48 synthetic strip/frame for quick sim.

## 2026-09-26 — Phase 1: RTL units (adder_tree, requant_pipe, fmap_pingpong, conv_layer)

- `rtl/adder_tree.sv`: recursive-generate N-input signed adder tree, register
  every 2 combinational levels, tag/valid ride along. **U2**: 5000 random
  N=27 vectors back-to-back, bit-exact. PASS.
- `rtl/requant_pipe.sv`: 4-stage TFLite requant (register/multiply/round/shift+clamp).
  **U1**: all 10,005 `vectors/requant_vectors.txt` vectors back-to-back, bit-exact. PASS.
- `rtl/fmap_pingpong.sv`: 2-bank double-buffered feature map, start/done
  handshake. **U3**: 500 tiles with random producer/consumer stalls, in
  order, bit-exact. PASS. (Hit a Verilator-2-state gotcha along the way:
  `@(negedge rst_n)` never fires when rst_n is already 0 at time 0 in 2-state
  sim — fixed the testbench to `wait(rst_n)` instead.)
- `rtl/conv_layer.sv`: the layer-pipelined conv stage (gather/issue overlap,
  pass-major/channel-minor issue order, per-channel acc_mem, tag-carried
  bias/mult/shift). **Gate: tb_conv_layer, 8 tiles back-to-back per layer,
  bit-exact against `vectors/tile0_layer{K}.hex`, all 4 layers:**

  | Layer | CIN→COUT | measured cycles/tile | target | gate (≤1056) |
  |---|---|---|---|---|
  | L0 | 3→16 | 1032 | 1024 | PASS |
  | L1 | 16→16 | 1034 | 1024 | PASS |
  | L2 | 16→32 | 1033 | 1024 | PASS |
  | L3 | 32→32 | 1034 | 1024 | PASS |

  Two real RTL bugs found and fixed via simulation:
  1. `win_slice` was strided by a fixed 32 regardless of `CIN_PAR`, leaving
     most of a 256-entry array unassigned by its `always_comb` — resized it
     to exactly `CIN_PAR*9` entries (no gaps).
  2. (testbench-only, not RTL) the fake fmap read port was combinational
     (0-cycle) while `conv_layer`'s gather logic assumes the same 1-cycle
     sync-read latency the real `fmap_pingpong` provides — fixed the
     testbench's model to register the read.
  Also (testbench-only) a 64-bit `word` variable silently aliased when
  parsing a 128-bit (COUT=16) hex line via `$fscanf %h` — widened to 256 bits.

Next: `gap_head.sv`, `tcnn_core.sv` (wire 4 layers + gap_head via
fmap_pingpong), `tile_feeder.sv`/`frame_player.sv`/`result_sink.sv`,
`tcnn_avalon_slave.sv`, then the C1/F1/S1 gates, then Quartus (P2).

## 2026-09-26 — Phase 1 continued: gap_head, tcnn_core, Gate C1 (the core proof)

- `rtl/gap_head.sv`: sequential FSM (huge slack vs. the ~1024-cycle/tile
  budget, so no per-op pipelining needed here) — sums L3's 16 spatial
  positions per channel, requantizes the sum (folding the /16 average into
  the fixed-point multiplier), then a serial 32→2 FC + requant, sharing one
  `requant_pipe` instance throughout. One deliberate deviation from the plan:
  reads L3's output from a normal `fmap_pingpong` consumer port rather than
  tapping L3's raw per-channel stream directly — costs one small buffer
  (16×32 B) and is negligible against the layers' ~1024-cycle budget, and
  was far simpler to get right under time pressure. **Standalone gate**: 8
  tiles back-to-back from `vectors/tile0_layer3.hex`, logits bit-exact
  against `vectors/tiles_expected.hex` line 0. PASS.
- `rtl/tcnn_core.sv`: wires the L0-input fmap, all 4 `conv_layer`s, the 4
  `fmap_pingpong`s between them (including after L3, into `gap_head`), and
  `gap_head`. Exposes the L0-input producer port and the result stream.

### Gate C1 (tb_core.sv) — **PASS, the architecture's core claim proven**

Pushed all 1000 tiles from `vectors/tiles.hex` through the L0-input port
back-to-back (as fast as `wr_ready` allows), checked every emitted
`(logit0,logit1)` pair **in order** against `vectors/tiles_expected.hex`:

```
PASS 1000/1000 tiles, min_gap=1037 max_gap=1037 cycles
```

Bit-exact on all 1000 tiles, and the steady-state gap between consecutive
results is **exactly 1037 cycles, every time** (not just an average) — the
4-stage pipeline (L0‖L1‖L2‖L3‖gap_head, each on a different tile
concurrently) has fully converged to a fixed-rate steady state, gated only
by the slowest stage (each conv layer, ~1024 cycles + ~11-cycle gather
warmup — see conv_layer.sv's header). This is comfortably inside the
Phase 1 gate (≤1056 cycles/tile).

**At 50 MHz this is 50e6/1037 ≈ 48,216 tiles/s.** For a 640×480 frame at
stride 16 (non-overlapping 16×16 tiles, 40×30 = 1200 tiles/frame):
48,216/1200 ≈ **40.2 fps** — above the project's ≥39 fps target, and roughly
**40× faster than the old shared-engine design's measured ~1 fps**
(fpga_cnn_pipeline/docs/progress_log.md), still purely from RTL simulation
(no Quartus timing closure yet — see Phase 2 below for what that number
would need to survive unmodified on real silicon).

Next: `tile_feeder.sv` (band buffering + tile extraction from a raster
pixel stream), `frame_player.sv` (replays an on-chip strip as a full frame),
`result_sink.sv` (result RAM + mismatch/cycle counters), `tcnn_avalon_slave.sv`,
then Gate F1 (full 640×480 replay) and Gate S1 (Avalon register map), then
Phase 2 (Quartus).

## 2026-09-26/27 — Phase 1 finished: tile_feeder, frame_player, result_sink, Gate F1

- `rtl/tile_feeder.sv`: 2-band (16-line) buffer, extracts non-overlapping
  16×16 tiles (stride 16) from a raster pixel stream into the L0-input fmap.
- `rtl/frame_player.sv`: replays an uploaded strip (≤48 lines, on-chip RAM)
  as any number of full frames, row r → strip row `r % strip_h`.
- `rtl/result_sink.sv`: stores frame 0's results at a fixed pitch
  (`band*40+tcol`, independent of runtime width); every later frame's
  results are compared against frame 0's and any difference increments
  `res_mismatch` — the check that would catch a timing violation on real
  hardware, which bit-exact simulation cannot.
- `rtl/tcnn_top_sim.sv`: wires frame_player → tile_feeder → tcnn_core → result_sink.

Two more real bugs found and fixed via Gate F1:
1. `tile_feeder`'s band-tag counter free-ran across the whole test instead
   of wrapping every `frame_h/16` bands — every tile after frame 0 landed on
   the wrong `result_ram` address (all 12 tiles in the small test showed
   `res_mismatch`, even though the actual computed values were fine).
2. (testbench-only) the very first strip-upload write raced the first
   `clk` edge and was silently dropped in this simulator; inserting one
   throwaway `@(posedge clk)` before the upload loop fixed it. Confirmed
   RTL-side (not a hardware bug): every other address uploaded correctly on
   the very same run.

### Gate F1 — **PASS at full 640×480 resolution, 2 frames, 0 mismatches**

Small smoke test first (64×48, 12 tiles/frame, 2 frames): `PASS 12/12 rows,
0 mismatches`. Then the real target size, `002675.jpg` resized to 640×480,
uploaded as a 640×48 strip, replayed as 2 full frames (stride 16, 1200
tiles/frame):

```
uploaded 30720 strip words
loaded 1200 expected result rows
cycles=2502735 tiles_done=2400 res_mismatch=0 min_gap=1037 max_gap=1037
PASS 1200/1200 rows, 0 mismatches
```

All 1200 tile positions bit-exact against `ref/int_model.py` (via
`make_vectors.py`'s expected CSV), identical results on both replayed
frames (0 mismatches), steady-state gap constant at 1037 cycles throughout.
**2,502,735 cycles / 2 frames = 1,251,368 cycles/frame → at 50 MHz,
50e6/1,251,368 ≈ 39.96 fps.** This is the full end-to-end architecture
proof, still purely in RTL simulation (Verilator, no synthesis/timing yet):
**≈40 fps vs. the old design's measured ~1 fps — a ~40× improvement,**
above the ≥39 fps project target.

**Not yet done** (at the time of writing above): `tcnn_avalon_slave.sv` (the
Avalon register-map wrapper, Gate S1), Phase 2 (Quartus fit + `quartus_sta`
timing closure at 50 MHz — the old project needed several iterations here,
see `fpga_cnn_pipeline/docs/review_findings.md` B18/B19), and Phases 3-4
(firmware, host tool, real board bring-up). Paused here to report the P1
result to the user before committing to a Quartus cycle (each build is
~20-40 minutes and, per the old project's history, may need more than one
RTL iteration to close timing).

## 2026-09-27 — Gate S1: tcnn_avalon_slave.sv

- `rtl/tcnn_avalon_slave.sv`: 32-bit word-addressed Avalon-MM register map
  (5-bit address, 19 registers) per the plan's table — ID/VERSION/SCRATCH/
  CTRL/STATUS/FRAME_W/FRAME_H/STRIP_H/NFRAMES/STRIP_ADDR/STRIP_DATA/
  RES_ADDR/RES_DATA/CYCLES/TILES_DONE/RES_MISMATCH/MIN_GAP/MAX_GAP/
  FEED_STALL. Instantiates `frame_player`/`tile_feeder`/`tcnn_core`/
  `result_sink` directly (rather than reusing `tcnn_top_sim`) so it can also
  see `px_valid`/`px_ready`/`player_busy` for STATUS.busy and FEED_STALL,
  which `tcnn_top_sim`'s port list doesn't expose. STATUS.done latches
  across the whole run (`run_done_seen_since_start`), since `player_busy`
  alone drops as soon as the last pixel is fed — well before the pipeline
  drains and `result_sink` actually asserts `run_done`.
- `tb/tb_slave.sv` (**Gate S1**, styled on
  `fpga_cnn_pipeline/tb/tb_cnn_slave.sv`'s bus-functional-model tasks):
  register readback, strip upload through STRIP_ADDR/STRIP_DATA (address
  auto-increments on the RTL side), run 2 frames of the 64×48 vectors via
  CTRL.start, read every result back through RES_ADDR/RES_DATA, check
  against the expected CSV and the counters.

One real RTL bug found and fixed: `STRIP_DATA`'s auto-increment bumped
`strip_addr_reg` in the same cycle it also (one cycle later, once
`strip_wr_en` reaches `frame_player`) drove the actual RAM write address —
so every uploaded word landed one slot past where it belonged. Every
result came out self-consistent between the two replayed frames
(`RES_MISMATCH` stayed 0) but wrong against the expected CSV, which is what
exposed it. Fixed by capturing the address into a separate register
(`strip_wr_addr_r`) at write time, before the increment.

```
S1a (registers) done, errors so far=0
S1b: uploaded 3072 strip words
S1b: loaded 12 expected result rows
S1b: cycles=29607 tiles_done=24 res_mismatch=0 min_gap=1037 max_gap=1037
S1b PASS 12/12 rows
PASS
```

## 2026-09-27 — Phase 3: firmware and host tool

- `firmware/src/main.c`: NiosV command-loop firmware, same UART-helper/resync
  pattern as `fpga_cnn_pipeline/firmware/src/main.c`, fronting
  `tcnn_avalon_slave`'s register map. Commands: `P`/`I`/`W`/`E`/`U`/`R`/`G`/`X`
  per the plan (ping, identify, scratch, echo, strip upload, run N frames,
  read back N result words, soft reset). `cmd_upload()` re-seeds STRIP_ADDR
  once per row rather than once per whole strip, since `tcnn_avalon_slave`
  addresses the strip at a fixed pitch of `MAX_W=640` (see `frame_player.sv`)
  while the uploaded image is only `W` pixels wide — the same row-by-row
  addressing `tb/tb_slave.sv` already uses in simulation.
- Built via `niosv-bsp`/`niosv-app`/`cmake`/`make` against
  `quartus/tcnn_test/tcnn_test_sys.sopcinfo`. **Links successfully: 35.11 KB
  program size, 23.04 KB free for stack+heap**, comfortably inside the 64 KB
  on-chip RAM Phase 2's system already provides (no repeat of the old
  project's 32 KB-too-small issue).
- `host/tcnn_link.py`: `TcnnLink` transport class, same
  `juart-terminal`-subprocess/pump-thread/resync pattern as
  `fpga_cnn_pipeline/host/cnn_link.py`'s `CnnLink` (including the
  `--no-quit-on-ctrl-d` workaround for a byte-0x04-kills-the-link behavior
  that project found on real hardware). CLI: `ping`, `id`, `echo`, `upload`,
  `bench` (prints fps = frames·50e6/CYCLES, tiles/s, gap stats, mismatches),
  `check` (reads results back and compares against `ref/int_model.py` run on
  the same replayed frame, using the same strip-repeat convention
  `ref/make_vectors.py`'s `gen_strip_and_frame()` uses for its expected
  CSVs), `tiles` (repacks `vectors/tiles.hex`'s 1000 tiles on the fly into
  640×48 strips of 120 tiles/9 strips, matching the plan's board-side
  bit-exact test), `abort`. Verified: imports `ref/int_model.py` correctly
  and the whole module byte-compiles clean.

**Live board status:** a JTAG cable and a board (`020F70DD`, matching the
DE2-115's expected `EP3C120/EP4CE115` shared JTAG ID string per the old
project's own runbook) were detected via `jtagconfig`, with no other JTAG
client (`juart-terminal`/`jtagd`/Signal Tap) running. Programming the board
(`quartus_pgm -m jtag -o "p;output_files/tcnn_test.sof"`) was attempted next
but was **blocked by the harness's auto-mode permission classifier** as a
real-world hardware transaction requiring explicit user approval — this is
a session-policy stop, not a technical or design problem. **Phase 4 (program
the board, run `tiles`/`bench --frames 200`, confirm ≥39 fps with 0
mismatches on real silicon) has NOT been performed.** Firmware and host
tooling are complete, built, and ready — `quartus/tcnn_test/output_files/
tcnn_test.sof` and `firmware/app/app.elf` are both in place. The user needs
to either grant that permission or run the programming step themselves.

**Phase 1 is now fully complete and gated** (U1, U2, U3, all 4 conv_layer
gates, C1, F1, S1 — all PASS). Proceeding into Phase 2 (Quartus fit +
`quartus_sta` timing closure at 50 MHz).

## 2026-09-27 — Phase 2 (Quartus) and board bring-up begin

Phase 2 (Quartus fit + timing closure) and Phase 3 (firmware + host tool)
were completed in this pass — see the fuller entries a fresh continuation
session would find by reading `quartus/tcnn_test/output_files/*.rpt` and
`firmware/`, `host/tcnn_link.py` directly; the short version: **Gate P2
passed** (Slow 1200mV 85C: setup slack +2.342 ns, hold slack +0.284 ns, TNS
0.000 in every corner — the exact thing `fpga_cnn_pipeline` never achieved),
at 88% LE usage (over the plan's <=60% target, but fits and closes timing;
user explicitly chose to proceed rather than trim `CIN_PAR` first). Firmware
built at 35.11 KB (well inside the 64 KB on-chip RAM).

### Board bring-up: `.sof` programmed, firmware downloaded, link verified

`quartus_pgm` + `niosv-download` succeeded; `ping`/`id` over the JTAG UART
confirmed the link (`TCID=0x54434e31`, `VERSION=0x0000000a`).

**Bug 1 (host, not RTL): `tcnn_link.py`'s `upload()` sent the whole strip
(up to 92160 B) as one blocking `write()`.** This didn't just make the
transfer slow -- when the transfer took longer than the CLI's timeout and
got killed, the firmware was left stuck forever inside `cmd_upload()`'s
`recv_all()`, waiting for bytes that would never arrive, so it stopped
responding to every later command (including basic `ping`) until the board
was reprogrammed. Fixed by sending one row (`w*3` bytes) per `write()`,
matching firmware's own per-row `recv_all(row_buf, w*3)` boundary. Measured
real JTAG UART throughput this way: **~623 B/s** -- much slower than the
~12 KB/s the old project's docs assumed, so `upload()`'s default timeout was
raised from 60 s to 300 s (a 640x48 strip takes roughly 148 s to upload;
this only happens once per bench run, not once per frame, which is the
entire reason `frame_player` replays from on-chip memory in the first
place).

**Bug 2 (real RTL bug in `frame_player.sv`, found running the 9-strip
`tiles` test back-to-back): its `P_DONE` state only left for `P_IDLE` on a
`start` pulse, never directly for `P_RUN`.** Since `tcnn_avalon_slave`'s
`CTRL.start` is only asserted for a single cycle, that one pulse was
consumed entirely by the `P_DONE -> P_IDLE` transition -- `frame_player`
then sat in `P_IDLE` forever, having received no pixels, and every SECOND
`R` command silently produced zero pixels: `STATUS.done` never set,
firmware's spin-loop (`RUN_DONE_SPIN_MAX`) ran to its limit before replying,
which took longer than the host's 120 s `run()` timeout. Every Phase 1 gate
had only ever exercised ONE top-level run per testbench invocation (fresh
reset each time), so this never showed up until strip 2 of the board's
`tiles` test. Fixed by making the `P_DONE` case handle `start` exactly like
`P_IDLE` does (load `frame_w`/`strip_h`, reset the address generators, and
go straight to `P_RUN`), and added a regression to `tb/tb_slave.sv`: run
`test_run()` twice in a row within one simulation. Confirmed failing before
the fix's logic (reasoned from the FSM, not by re-running a broken copy)
and **passing after**, back-to-back, bit-exact both times:

```
S1b PASS 12/12 rows
S1b PASS 12/12 rows
PASS
```

This RTL fix requires a Quartus re-synthesis (`qsys-generate` + recompile)
before reprogramming the board.

### Rebuild after the `frame_player.sv` fix -- Gate P2 still holds

`qsys-generate` (picks up `tcnn_avalon_slave`'s fileset, which includes
`frame_player.sv`) followed by `quartus_sh --flow compile tcnn_test`
completed successfully (0 errors, 23m38s). New `tcnn_test.sof` timestamp
02:57:36 (previous build: 01:59:34).

```
Slow 1200mV 85C Model Setup 'CLOCK_50': Slack 2.042, TNS 0.000
Slow 1200mV 85C Model Hold  'CLOCK_50': Slack 0.329, TNS 0.000
Total logic elements : 100,307 / 114,480 (88%)
Total memory bits    : 1,919,232 / 3,981,312 (48%)
Embedded Multiplier 9-bit elements : 42 / 532 (8%)
```

Setup slack moved slightly (+2.342 ns -> +2.042 ns) and hold slack moved
slightly the other way (+0.284 ns -> +0.329 ns) -- both expected, small
shifts from one FSM's next-state logic changing, and both still comfortably
positive. LE/memory/multiplier usage essentially unchanged. **Gate P2 still
passes.** This `.sof` (not the earlier one) is the one to program onto the
board going forward.

## 2026-09-27 — Phase 2: Quartus build, Gate P2 (timing PASS, area over budget)

Built `tiny_cnn/quartus/tcnn_test/` by copying and adapting
`fpga_cnn_pipeline/quartus/cnn_test/`'s `build_system.tcl`, `.qsf`, `.sdc`,
top-level, and component `.tcl` (`tcnn_avalon_slave_hw.tcl`, fileset listing
every `rtl/*.sv` file plus `gen/tcnn_pkg.sv`). System: Nios V/m, 64 KB
on-chip RAM, JTAG UART, sysid, `tcnn_avalon_slave_0` at `0x00032000`, one
50 MHz clock domain throughout (no PLL/CDC — matches the plan's target).
Device: EP4CE115F29C7, Cyclone IV E.

Getting a clean `quartus_sh --flow compile` took several real, distinct
synthesis-only bugs, none of which Verilator's simulation could have caught
(all Phase 1 gates were re-run bit-exact after every fix below, before each
recompile):

1. **`genvar i` declared inline in a `for` loop** (`adder_tree.sv`) —
   Quartus's Verilog parser rejects `for (genvar i = 0; ...)`; needs a
   separate `genvar i;` declaration before the loop. (Verilator accepts the
   inline form.)
2. **A `parameter string` used directly as `$readmemh`'s filename argument
   is unconditionally rejected** by Quartus Prime 25.1's synthesis
   elaborator ("has an aggregate value", error 10686) — confirmed with a
   minimal isolated repro outside this project; true regardless of
   whether the parameter has a default, what that default is, or how it's
   declared (single vs. separate `parameter string` statements). Only a
   literal string token (or a preprocessor macro that expands to one)
   works. Fixed by removing `ROM_FILE`/`BIAS_FILE`/`MULT_FILE`/
   `SHIFT_FILE`/`HW_FILE`/`HB_FILE` as module parameters entirely:
   `conv_layer.sv` now takes a `LAYER` (0..3) parameter and selects the
   right `gen/tcnn_paths.svh` `` `TCNN_* `` literal macro via a
   `generate case (LAYER)`; `gap_head.sv` (only one instance) uses its
   macros unconditionally. `gen_tcnn.py` was extended to also emit these
   per-file literal-path macros (`` `TCNN_W_L0 ``, etc., alongside the
   existing `` `TCNN_GEN ``), and `tcnn_core.sv`/`tb_conv_layer.sv`/
   `tb_gap_head.sv` were updated to the new `.LAYER(k)` interface.
3. **Two `always_ff` blocks each writing a variable-indexed array element
   of the same array** (`bst[2]` in `tile_feeder.sv`, one process indexed
   by `fill_ptr` and the other by `drain_ptr`; `gathering`/`gphase` in
   `conv_layer.sv`, one process in the gather logic and one in the tile
   FSM) is rejected by Quartus as "Can't resolve multiple constant
   drivers" (error 10028), even though the two writers are mutually
   exclusive by construction. Verilator schedules both processes and never
   flagged it. Fixed by merging each pair into a single `always_ff` (no
   behavior change — every statement is unchanged, just consolidated).
4. **Large arrays read with a "select array, then register" pattern
   (`(sel) ? mem0[addr] : mem1[addr]`, registered) are not recognized by
   Quartus's RAM inference as a synchronous read** — it reported
   `fmap_pingpong`'s `mem0`/`mem1`, `tile_feeder`'s `band0`/`band1`
   (16×640 deep), and `frame_player`'s `strip_mem` (640×48 deep, and
   genuinely combinationally read via a bare `assign`) all "uninferred due
   to asynchronous read logic", register-izing hundreds of thousands of
   bits and blowing the design's register budget ("Cannot convert all
   sets of registers into RAM megafunctions", error 276003). Fixed with
   the standard tool-friendly idiom — read each bank into its **own**
   register first, then mux the two already-registered values:
   - `fmap_pingpong.sv`: `mem0_q`/`mem1_q`, muxed combinationally into
     `rd_data`.
   - `tile_feeder.sv`: `band0_q`/`band1_q`, muxed into a one-cycle-delayed
     `l0in_wr_en`/`l0in_wr_addr`/`l0in_wr_data` pipeline (added a
     `D_FLUSH` state so the last pixel's delayed write lands before
     `l0in_wr_done` fires).
   - `frame_player.sv`: converted from a purely combinational
     `assign px_data = strip_mem[...]` to a registered read behind a
     1-deep output skid buffer (`px_data_q`/`px_valid_q`), so it still
     honors `px_ready` backpressure with a real synchronous memory read;
     `done` now fires when the last skid-buffered pixel is actually
     drained to the consumer, not merely fetched into the skid register.

After every fix, Gates U1–U3, all 4 conv_layer per-layer gates, gap_head,
C1, F1, and S1 were re-run and stayed bit-exact (F1/S1's total cycle count
shifted from 2,502,735/29,607 to 2,502,737/29,609 — 2 extra cycles overall
from the two new pipeline stages in `tile_feeder`/`frame_player`; steady
state `min_gap`/`max_gap` unchanged at 1037).

### Gate P2 result

```
Fitter Status : Successful
Device : EP4CE115F29C7, Cyclone IV E
Total logic elements       : 100,309 / 114,480 ( 88% )
  combinational functions  :  71,836 / 114,480 ( 63% )
  dedicated logic registers:  62,938 / 114,480 ( 55% )
Total memory bits          : 1,919,232 / 3,981,312 ( 48% )
Embedded Multiplier 9-bit  :        42 /       532 (  8% )

Slow 1200mV 85C Model Setup 'CLOCK_50' : slack = +2.342 ns, TNS = 0.000
Slow 1200mV 85C Model Hold  'CLOCK_50' : slack = +0.284 ns, TNS = 0.000
(every other corner/check -- 0C, Fast, recovery, removal, min pulse width,
 both clocks -- also non-negative; TNS = 0.000 everywhere)
```

**Timing closes at 50 MHz** in the Slow 85°C corner with real margin (the
plan's actual project goal, and the old design's B19 failure point) — a
genuine, meaningful win: the layer-pipelined architecture not only
simulates ~40× faster than the old shared-engine design, it also **fits
and closes timing** on real silicon, which the old design never achieved.
All 4 conv_layer instances' weight/bias/mult/shift ROMs (and the head's
`hw`/`hb`) were confirmed mapped to `altsyncram` (M9K) primitives in the
Fitter RAM Summary, with their `$readmemh` contents captured into
per-instance `.mif` files during synthesis (zero "no driver or initial
value" warnings for any of them, versus several before fix #2 above).

**Not met: the plan's ≤60% LE budget check** — this build uses 88% of the
device's logic elements, well over budget, though it still fits (the
device has headroom left, and multiplier/M9K usage are comfortably low at
8%/48%). This is very likely dominated by conv_layer's fully-parallel
`CIN_PAR` lane count per layer (up to 16 lanes × 9 taps = 144 parallel
8×4-bit multiply/adder-tree paths for L1/L3) — the plan's own "Later" section
anticipated this tradeoff in the other direction (increasing `CIN_PAR`
later to hit a smaller cycle-per-tile target would cost even more area).
Reducing area (e.g. lower `CIN_PAR` with more `NPASS` for the heavier
layers, trading some throughput for LEs) is the natural next lever, per the
plan's own per-layer schedule table, but is a design-space change beyond
this pass's scope. Recorded here for the user's decision, not attempted
further in this pass.

**Gate P2 verdict: PARTIAL PASS** — timing closure (the project's stated
core goal, and the specific failure this new architecture set out to fix)
is fully met; the LE-budget check is not. `.sof` is at
`quartus/tcnn_test/output_files/tcnn_test.sof`, ready to program if the
user wants to proceed to Phase 4 board bring-up despite the area overage
(the design *does* fit, just at 88% rather than the target ≤60%).

**Not yet done**: Phases 3-4 (firmware `main.c`, host `tcnn_link.py`, real
board bring-up) — need the user's physical board and are out of scope for
this pass.

## 2026-09-27 — Board bring-up: link verified, frame_player fix found, rebuilt, board re-tested

Programmed the board (`quartus_pgm`) and downloaded firmware
(`niosv-download`); `ping`/`id` over the JTAG UART confirmed the link
(`TCID=0x54434e31`, `VERSION=0x0000000a`).

**Bug 1 (host, not RTL): `tcnn_link.py`'s `upload()` sent the whole strip
(up to 92160 B) as one blocking `write()`.** When a transfer took longer
than the CLI's timeout and got killed, the firmware was left stuck forever
inside `cmd_upload()`'s `recv_all()`, so it stopped responding to every
later command (even `ping`) until the board was reprogrammed. Fixed by
sending one row (`w*3` bytes) per `write()`, matching firmware's own
per-row `recv_all(row_buf, w*3)` boundary. Measured real JTAG UART
throughput this way: **~623 B/s** — much slower than the ~12 KB/s the old
project's docs assumed. `upload()`'s default timeout was raised from 60s to
300s (a 640x48 strip takes ~148s to upload; this happens once per bench
run, not once per frame — the entire reason `frame_player` replays from
on-chip memory).

**Bug 2 (real RTL bug in `frame_player.sv`): its `P_DONE` state only left
for `P_IDLE` on a `start` pulse, never directly for `P_RUN`.** Since
`tcnn_avalon_slave`'s `CTRL.start` is asserted for a single cycle, that
pulse was entirely consumed by the `P_DONE -> P_IDLE` transition —
`frame_player` then sat in `P_IDLE` forever having streamed no pixels, so
every SECOND top-level `R` command silently produced zero pixels:
`STATUS.done` never set, firmware's spin-loop ran to its limit before
replying, which took longer than the host's `run()` timeout. Every Phase 1
gate had only ever exercised one top-level run per testbench invocation
(fresh reset each time), so this never surfaced until strip 2 of the
board's `tiles` test (9 strips = 9 separate runs). Fixed by making
`P_DONE` handle `start` exactly like `P_IDLE` (load `frame_w`/`strip_h`,
reset the address generators, go straight to `P_RUN`). Added a regression
to `tb/tb_slave.sv`: `test_run()` called twice in one simulation. Passes
bit-exact both times after the fix:

```
S1b PASS 12/12 rows
S1b PASS 12/12 rows
PASS
```

Rebuilt Quartus (`qsys-generate` + `quartus_sh --flow compile`, ~23m38s,
0 errors) — **Gate P2 still holds**:

```
Slow 1200mV 85C Setup slack: +2.042 ns (was +2.342 ns)
Slow 1200mV 85C Hold  slack: +0.329 ns (was +0.284 ns)
LE 88%, memory bits 48%, multipliers 8% -- unchanged
```

Reprogrammed the board with the fixed `.sof`/`.elf`; `ping`/`id` confirmed
the link again. Then ran the full 9-strip, 1000-tile bit-exact test — the
exact scenario (9 consecutive top-level runs) that silently failed before
the fix:

```
tiles: 1000 tiles, 0 mismatches
exit=0
```

**1000/1000 tiles bit-exact, 0 mismatches, on real hardware**, confirming
the fix holds for repeated runs, not just simulation. Proceeding to the
project's actual goal: `bench --frames 200` at 640x480 (Gate P4, target
>=39 fps with 0 mismatches).

## 2026-09-27 — Gate P4: board proof at 640x480, 200 frames — PASS

```
bench: 640x480, 200 frames, cycles=248893937 fps=40.18 tiles/s=48213
tiles_done=240000 (expect 240000) res_mismatch=0
min_gap=1037 max_gap=1037 feed_stall=187375966 status=0x00000002 wall=5.26s
```

**40.18 fps, bit-exact, 0 mismatches across 200 real-hardware frames** —
above the plan's >=39 fps target, and the steady-state gap (1037
cycles/tile) matches Gate C1/F1's RTL simulation numbers exactly, meaning
the design behaves identically on real silicon as it did in Verilator.
`feed_stall` is large (187M of 249M cycles) but purely informational per
the register map's own description — it just means `frame_player` often
has a pixel ready before `tile_feeder` can accept it (expected, since
`tile_feeder` only drains a band at a time), and it does not affect
correctness or the measured cycle count/fps, which come from
`result_sink`'s own tile-to-tile gap measurement.

**Gate P4 (the project's stated goal): PASS.** The layer-pipelined
architecture sustains **>=39 fps at 640x480 with stride-16 tiles, bit-exact
results, zero mismatches**, on the real DE2-115 board — roughly **40x
faster than the old shared-engine design's measured ~1 fps**
(`fpga_cnn_pipeline/docs/progress_log.md`), and it does so while also
closing timing at 50 MHz in the Slow 1200mV 85C corner, which the old
design never achieved.

**All phases of `docs/implementation_plan.md` are now complete**: P0
(generator/golden model), P1 (RTL units, all gates U1-U3/conv_layer/C1/F1/S1),
P2 (Quartus fit + timing closure, 88% LE / 48% memory / 8% multipliers),
P3 (firmware 35.11 KB, host `tcnn_link.py`), P4 (board bring-up, 1000-tile
bit-exact + 200-frame >=39fps bench). Two real bugs were found and fixed
specifically during board bring-up (host upload chunking; `frame_player`'s
P_DONE->P_RUN restart bug) that no simulation gate had caught, since every
Phase 1 testbench only ever exercised a single top-level run per fresh
reset -- worth remembering for any future protocol/FSM work: exercise
restart/re-run paths explicitly, not just fresh-reset paths.

Not done (out of this plan's scope, per its own "Later" section): reducing
`CIN_PAR` to bring LE usage under the 60% target, and the 512/256-cycle
faster-interval follow-on.
