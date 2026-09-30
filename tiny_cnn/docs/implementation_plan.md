# Plan: layer-pipelined Tiny-CNN accelerator on DE2-115 (tile interval 1024 cycles)

## Context

`tiny_cnn/tinycnn_qat_int4.onnx` is a new, much smaller anomaly classifier than the one the existing
`fpga_cnn_pipeline/` was built for. It takes a 16×16×3 uint8 patch and returns 2 uint8 logits:
- 4 conv layers: 3→16 (stride 2), 16→16, 16→32 (stride 2), 32→32
- global average pool (4×4), then FC 32→2
- ~396k MACs per patch; 16,624 int4 weights (~8 KB)

The old design used one shared, time-multiplexed engine, register-array feature maps with dynamic muxes, and a
12 KB/s JTAG-UART data path. It reached ~1 fps and never met timing at 50 MHz (see
`fpga_cnn_pipeline/docs/review_findings.md`, entries B18 and B19).

Goal: prove on the board that a layer-pipelined architecture sustains **one tile per ~1024 cycles**.
- That is ≈48.8k tiles/s at 50 MHz, or **≈40 fps** on 640×480 with non-overlapping 16×16 tiles (stride 16, 1,200 tiles/frame).
- Frames are replayed from on-chip memory, so the JTAG link does not limit the measurement.

Decisions made with the user:
- stride 16
- tile interval of 1024 cycles first; push to 512 or 256 later
- the host decides which logit means "anomalous"
- new code lives in a new `tiny_cnn/` tree, and `fpga_cnn_pipeline/` stays untouched (reuse from it by import or copy only)

Verified facts about the model:
- Every bias scale equals exactly `in_scale*w_scale` (so bias can be added as an integer).
- All weight and activation zero-points are 0; the logits zero-point is 123.
- Input `patches` expects `pixel/255.0` floats.
- The pooling requant multiplier is `relu_3_scale/(16*view_scale) = 0.13279`.
- onnxruntime runs the model fine (venv at repo root: `venv/bin/python`).

Each phase ends with a gate. Record every gate result in `tiny_cnn/docs/progress_log.md`, dated, with the command and
output, in the same style as `fpga_cnn_pipeline/docs/progress_log.md`. **Do not start a phase until the previous
gate passes.**

---

## Directory layout (new)

```
tiny_cnn/
  gen_tcnn.py            ONNX -> gen/ (packed ROMs, json, sv package)
  gen/                   generated (tcnn.json, tcnn_pkg.sv, tcnn_paths.svh, *.hex)
  ref/int_model.py       bit-exact integer model (4 conv + GAP + head)
  ref/check_agreement.py int_model vs onnxruntime gate
  ref/make_vectors.py    test vectors for all testbenches
  rtl/                   adder_tree.sv, requant_pipe.sv, fmap_pingpong.sv, conv_layer.sv,
                         gap_head.sv, tcnn_core.sv, tile_feeder.sv, frame_player.sv,
                         result_sink.sv, tcnn_avalon_slave.sv
  tb/                    tb_*.sv (Verilator)
  Makefile               make sim TEST=<name>, make sim_all
  quartus/tcnn_test/     Quartus + Platform Designer project (copied/adapted from fpga_cnn_pipeline/quartus/cnn_test)
  firmware/              Nios V app (src/main.c, app/CMakeLists.txt, bsp/)
  host/tcnn_link.py      host CLI
  docs/progress_log.md, docs/architecture.md
```

---

## Architecture (the contract the RTL must implement)

### Dataflow
```
strip RAM (640x48 RGB, Avalon-writable) -> frame_player (raster, replays strip rows r % SH)
 -> tile_feeder (2x16-line band buffer, emits 16x16 tiles) -> fmap_pingpong L0in
 -> conv_layer L0 -> fmap L1in -> conv_layer L1 -> fmap L2in -> conv_layer L2 -> fmap L3in
 -> conv_layer L3 -> gap_head (GAP, requant, FC 32x2, requant) -> result_sink (result RAM, counters)
```
- All stages run at the same time on different tiles.
- One clock: 50 MHz `CLOCK_50`.
- Stages hand off through `valid`/`ready` signals (stall allowed, no data drop), and every layer boundary uses a pair of buffers (`fmap_pingpong`).

### Per-layer schedule (tile interval = 1024 cycles per layer)
| Layer | CIN→COUT | IN_W→OUT_W | stride | CIN_PAR | NPASS | lanes | cycles/tile = OUT_W²·COUT·NPASS |
|---|---|---|---|---|---|---|---|
| L0 | 3→16 | 16→8 | 2 | 3 | 1 | 27 | 64·16·1 = 1024 |
| L1 | 16→16 | 8→8 | 1 | 16 | 1 | 144 | 64·16·1 = 1024 |
| L2 | 16→32 | 8→4 | 2 | 8 | 2 | 72 | 16·32·2 = 1024 |
| L3 | 32→32 | 4→4 | 1 | 16 | 2 | 144 | 16·32·2 = 1024 |

All layers use kernel 3×3 and pad 1. `CIN_PAR`, `NPASS` and `STRIDE` must be **parameters** of `conv_layer.sv`, so that
changing the tile interval later only means regenerating with different `CIN_PAR` values.

### Data formats (fixed; the generator, the Python model and the RTL must all agree)
- **Feature-map word:** all channels of one pixel. Channel `c` sits at bits `[8c+7:8c]`, as uint8.
- **Buffer address:** `y*W + x`.
- **Input pixel word:** 24 bits, `[7:0]=R`, `[15:8]=G`, `[23:16]=B` (channel 0 = R, as in ONNX NCHW).
  - **Note:** this is the reverse of the old `PIX={0,R,G,B}` register.
- **Window register:** `win[tap][ci]`, with `tap = ky*3+kx` (0..8) and `ci` 0..CIN-1.
- **Pass slice:** pass `p` uses channels `ci ∈ [p*CIN_PAR, (p+1)*CIN_PAR)`.
- **MAC lane:** `j = tap*CIN_PAR + (ci - p*CIN_PAR)`.
- **Weight ROM** `w_L{k}.hex`:
  - address `co*NPASS + p` (depth `COUT*NPASS`)
  - word width `CIN_PAR*9*4` bits
  - lane `j` at bits `[4j+3:4j]`: `w[co][p*CIN_PAR+ci_l][ky][kx]`, two's-complement int4
  - one hex word per line, MSB first
- **Tables per layer**, indexed by `co`, 32-bit hex, one per line:
  - `b_L{k}.hex`: int32 bias
  - `m_L{k}.hex`: M0
  - `s_L{k}.hex`: shift
- **Head tables:**
  - `hw.hex`: 64 int4 values, order `o*32+i`
  - `hb.hex`: 2 int32 values
  - head M0/shift and GAP M0/shift go into `tcnn_pkg.sv` as scalar localparams (`HEAD_M0_0`, `HEAD_SH_0`, …, `GAP_M0`, `GAP_SH`, `LOGIT_ZP=123`)
- **File paths:** `gen/tcnn_paths.svh` holds `` `define TCNN_GEN "<absolute path to tiny_cnn/gen/>" ``.
  - All `$readmemh` calls use `` {`TCNN_GEN,"w_L0.hex"} ``.
  - Absolute paths work in Verilator and Quartus alike, which avoids the old copy-hex-into-cwd problem.

### Arithmetic (bit-exact, identical in `int_model.py` and the RTL)
- **Conv:** `acc = bias[co] + Σ x*w` (x uint8, w int4, padding = 0).
- **Requant:** `y = (acc*M0 + (1<<(sh-1))) >>> sh` (floor, arithmetic), then `out = clamp(y + zp, 0, 255)`.
  - This is the same as `fpga_cnn_pipeline/ref/int_model.py::requant`.
  - M0 and sh come from `quantize_multiplier()` in `fpga_cnn_pipeline/onnx_to_rtl.py` (real = M0·2^-sh; **no extra +31**, see old finding B1).
- **GAP:** `s[c] = Σ_{16 px} relu3[c]` (≤4080), then `view[c] = requant(s[c], GAP_M0, GAP_SH, 0)`.
  - `GAP_M0`/`GAP_SH` come from `quantize_multiplier(relu_3_scale/(16*view_scale))`.
- **Head:** `acc_o = hb[o] + Σ_i view[i]*hw[o][i]`, then `logit_o = requant(acc_o, HEAD_M0_o, HEAD_SH_o, 123)`.
- **Widths:** accumulator 24-bit signed is enough (max |acc| < 2^20). Requant product is 24×32 → 56 bits.

### Modules
1. **`adder_tree.sv`** — `#(N, W_IN, REG_EVERY=2, TAG_W)`.
   - Signed sum of N inputs, with a pipeline register every `REG_EVERY` levels.
   - Carries `valid` and `tag[TAG_W-1:0]` alongside, so callers never compute latency by hand.
   - Build it with generate loops over levels (`n_l = ceil(n_{l-1}/2)`); no recursion.
2. **`requant_pipe.sv`** — about 6 registered stages, same `valid`/`tag` passthrough:
   - (1) register the inputs and compute `rnd = 1<<(sh-1)`
   - (2)–(3) `acc*M0`, with `(* multstyle="dsp" *)` and 2 registers for retiming
   - (4) `+rnd`
   - (5) `>>> sh`
   - (6) `+zp`, then clamp
   - Do not reuse `fpga_cnn_pipeline/rtl/requant.sv` as-is: its 64-bit multiply and variable shift are in 2 stages, which is a timing risk. Copy its arithmetic and comments, including the `$signed` slice note (old finding B12).
3. **`fmap_pingpong.sv`** — `#(WORD_W, DEPTH)`: 2 banks of simple dual-port M9K RAM (sync read, 1-cycle latency).
   - Each bank has a state: FREE → WRITING → FULL → READING → FREE.
   - Each bank has a tag register (`tile_row[4:0]`, `tile_col[5:0]`, `last_in_frame`).
   - Producer side: `wr_acquire` (only allowed when `can_acquire_wr`, i.e. the next bank is FREE; returns `wr_bank`), then `wr_en/wr_bank/wr_addr/wr_data`, then `wr_commit(bank)` → FULL. The tag is written at acquire.
   - Consumer side: `rd_acquire` (only when `can_acquire_rd`, i.e. the next bank is FULL; returns `rd_bank` and `rd_tag`), then `rd_addr` → `rd_data`, then `rd_release` → FREE.
   - Use round-robin pointers for each side so tile order is kept.
   - Writes carry an explicit bank index, because the tail of tile t can still be writing while tile t+1 has been acquired.
4. **`conv_layer.sv`** — `#(LAYER, CIN, COUT, IN_W, STRIDE, CIN_PAR)`. Two cooperating FSMs plus a datapath.
   - **Gatherer.** For each output pixel (oy, ox) of the tile:
     - Read the 9 taps from the input fmap at `(oy*S+ky-1, ox*S+kx-1)`; an out-of-range tap becomes 0.
     - Store them in `win_next` (write-side enables only, never a read-side dynamic mux).
     - Set `win_next_valid`.
     - It acquires the input bank at tile start and **releases it right after the last pixel's gather**, so the upstream layer can refill it early.
     - Budget: 9 reads + latency ≤ 16 cycles (L0/L1) or 64 cycles (L2/L3). The window for the next pixel is always ready in time.
   - **Issuer.**
     - Copy `win_next` → `win_cur` when the current pixel is finished and `win_next_valid` is set.
     - Then issue `COUT*NPASS` ops, one per cycle: ROM address `co*NPASS+p`, operand slice `win_cur[*][p*CIN_PAR +: CIN_PAR]` (a 2:1 mux at most), and tag `{first=p==0, last=p==NPASS-1, co, pix_addr, out_bank, tile_last}`.
     - At the first op of a tile, acquire the output bank. If no bank is free, stall.
   - **Datapath.**
     - Sync weight ROM (M9K, `$readmemh`), registered together with the operand slice.
     - `CIN_PAR*9` products `$signed({1'b0,a}) * $signed(w)`, registered.
     - `adder_tree`.
     - Accumulate stage: `acc <= first ? bias[co]+sum : acc+sum`. That is the only feedback loop, a single adder; the passes of one `co` arrive on consecutive cycles.
     - On `last`, send the result to `requant_pipe` with the per-`co` M0/sh/bias tables (small sync ROMs; delay their read to line up with the op).
     - Output collector: a shift register of COUT bytes. On `co==COUT-1`, write the full word to the output fmap at `pix_addr`. On the last pixel, commit the output bank.
5. **`gap_head.sv`** — reads the L3 output stream directly (serial per `co`, 16 px × 32 ch), with no fmap in between.
   - Keeps 32 accumulators of 12 bits each.
   - At tile end, copies them to a shadow set so the next tile can start accumulating.
   - A small FSM then runs:
     - 32× GAP requant, storing `view[32]`
     - 2 × (32 serial MACs + bias), then head requant (one shared `requant_pipe` is fine, ~110 cycles per tile)
   - Emits `{tag, logit0, logit1}` with `valid`/`ready`.
6. **`tcnn_core.sv`** — L0in fmap, L0..L3 with the three fmaps between them, and `gap_head`.
   - Exposes the L0in producer port and the result stream.
   - Also exports debug counters: tiles in, tiles out, and the cycle count between successive results.
7. **`tile_feeder.sv`** — input: a raster pixel stream (`valid`/`ready`, 24-bit) plus `frame_w`, `frame_h` (multiples of 16).
   - Two band banks of `16×640×24b` in M9K. Fill a bank in raster order; when its 16 rows are done, mark it FULL.
   - For each tile column: acquire an L0in bank, copy 16×16 pixels (1 per cycle) to address `r*16+c`, set the tag `{band, tcol, last_in_frame}`, then commit.
   - Free the band bank after its last tile.
   - Deassert `ready` upstream when both band banks are busy.
8. **`frame_player.sv`** — for `nframes` × H rows × W cols, read strip RAM row `(r % strip_h)` and emit pixels at 1 per cycle whenever `ready` is high.
   - Strip RAM: `640*48` words of 24 bits, true dual-port M9K. Port A is written from Avalon; port B is read by the player.
9. **`result_sink.sv`** — handles each result `{band, tcol, logit0, logit1}`:
   - Frame 0: write `{logit1, logit0}` into the result RAM (2048×16) at `band*40 + tcol`. Always use a fixed pitch of 40 (the maximum W/16 = 40) so the address never depends on runtime W.
   - Frames > 0: compare against the result RAM and increment `RES_MISMATCH` on any difference. This catches corruption from timing violations on the board.
   - Counters: `TILES_DONE`; `CYCLES` (from start to the last result of the last frame); `MIN_GAP`/`MAX_GAP` (cycles between consecutive results after the first 8 of the run); `FEED_STALL` (cycles where the player had data but `tile_feeder` was not ready).
10. **`tcnn_avalon_slave.sv`** — 32-bit, word-addressed register map; all read data is registered (one read-wait cycle, matching `fpga_cnn_pipeline/rtl/cnn_avalon_slave.sv`'s timing).

| Word | Name | R/W | Meaning |
|---|---|---|---|
| 0 | ID | R | `0x54434E31` ("TCN1") |
| 1 | VERSION | R | `[7:0]` interval code (1024→0x0A), `[15:8]` generator version |
| 2 | SCRATCH | RW | |
| 3 | CTRL | W | `[0]` start (pulse), `[1]` soft_reset (pulse) |
| 4 | STATUS | R | `[0]` busy, `[1]` done, `[8]` err_fsm (sticky), `[31:16]` reserved |
| 5 | FRAME_W | RW | multiple of 16, 16..640 |
| 6 | FRAME_H | RW | multiple of 16, 16..480 |
| 7 | STRIP_H | RW | multiple of 16, 16..48 |
| 8 | NFRAMES | RW | 1..65535 |
| 9 | STRIP_ADDR | W | set the strip write pointer (auto-increments on each STRIP_DATA write) |
| 10 | STRIP_DATA | W | `{8'h0, B, G, R}`, written to strip[ptr++] |
| 11 | RES_ADDR | W | result RAM read address |
| 12 | RES_DATA | R | `{16'h0, logit1, logit0}` at RES_ADDR |
| 13 | CYCLES | R | |
| 14 | TILES_DONE | R | |
| 15 | RES_MISMATCH | R | |
| 16 | MIN_GAP | R | |
| 17 | MAX_GAP | R | |
| 18 | FEED_STALL | R | |

The strip address for pixel (row, col) is always `row*640 + col` (fixed pitch). The firmware writes each strip row at that address, even when W < 640.

**Timing rules** (these fix the old B19 failure):
- No combinational path from a RAM output or a dynamic mux straight into a multiplier.
- At most 2 adder levels between registers.
- No mux wider than 2:1 on the MAC operands.
- The per-pixel window is gathered sequentially into registers; never index a flop array with a runtime counter on the read side.

---

## Phase 0 — Generator and golden model (Python)
1. **`tiny_cnn/gen_tcnn.py`.**
   - `sys.path.insert(0, '../fpga_cnn_pipeline')` and import `find_conv_chain`, `quantize_multiplier`, `weight_bits` from `onnx_to_rtl.py`. `find_conv_chain` already handles this graph (Conv → Q/DQ chain, `head.*`, `view_scale`); verify that it returns 4 convs.
   - Assert all weight zero-points are 0 and all bias scales equal `in_scale*w_scale`.
   - Assert that `CIN % CIN_PAR == 0` and that each layer's cycles per tile equal the target interval.
   - Take `CIN_PAR` per layer from a CLI option `--cin-par 3,16,8,16`.
   - Emit everything in the Data formats section above, plus `gen/tcnn.json` with every layer's shapes, `mults`, `shifts` and zero-points, the gap `{m0, sh}`, and the head `{mults, shifts, zp}`.
2. **`tiny_cnn/ref/int_model.py`.**
   - Adapt `fpga_cnn_pipeline/ref/int_model.py`: keep `requant()` and the numpy `conv_layer` as they are.
   - Load from `gen/tcnn.json` and the **packed** `w_L*.hex` files, un-packing with the lane formula. This checks the packing itself.
   - Add `gap()` and the new `head()`.
   - `run(patch, dump=True)` returns the logits plus each layer's output and `view`.
3. **`tiny_cnn/ref/check_agreement.py`.**
   - Copy the old script; import `OrtRef` from `fpga_cnn_pipeline/ref/ort_ref.py` (its constructor takes `model_path`).
   - Read `logits_scale`/zp from the ONNX file (zp = 123 here).
   - Use 5,000 random patches plus 5,000 crops from `fpga_cnn_pipeline/002675.jpg` and `002683.jpg`.
4. **`tiny_cnn/ref/make_vectors.py`** writes to `tiny_cnn/vectors/`:
   - `tiles.hex`: 1000 tiles as 24-bit words (256 per tile, raster order).
   - `tiles_expected.hex`: `logit0 logit1` per line, space-separated (see the `$fscanf` `_` note in the old `make_vectors.py`).
   - Per-layer dumps for tile 0 and for tiles 0–7, as fmap words in hex, one word per line.
   - `requant_vectors.txt`: 10k random `acc m0 sh zp → out` lines, plus ties and extremes.
   - `strip_640x48.hex`: a 640×48 strip made from `002675.jpg` (resize to 640×480, take rows 0–47).
   - `frame_expected.csv`: `band,tcol,logit0,logit1` for the replayed 640×480 frame (row r = strip row r % 48).
   - `strip_tiles_k.hex` plus expected values: the 1000 tiles packed as 640×48 strips, 120 tiles each (9 strips), for the board's bit-exact test.

**Gate P0:**
- `check_agreement.py`: within ±1 LSB on ≥99.5% of patches and argmax agreement ≥99.5%.
- `int_model` loaded from the packed ROMs matches `int_model` loaded directly from the ONNX tensors on 1000 tiles, bit-exact.

## Phase 1 — RTL units and simulation (Verilator)
Use `verilator --binary --timing -Wno-fatal` for every test (iverilog cannot handle packages with array localparams).
- `tiny_cnn/Makefile` gets targets `sim TEST=x` and `sim_all`.
- Every testbench's last output line is `PASS` or `FAIL <n>`.
- The testbenches must drive the DUT through the same `valid`/`ready` protocol the real upstream block uses (see the S4 lesson in the old `docs/simulation.md`).

| ID | TB | Check |
|---|---|---|
| U1 | `tb_requant_pipe` | 10k vectors issued **back-to-back** (a new input every cycle), in order, bit-exact |
| U2 | `tb_adder_tree` | random N ∈ {27,72,144}, back-to-back, tag stays aligned with its data |
| U3 | `tb_fmap_pingpong` | producer/consumer with random stalls; order and tags kept; never writes a non-FREE bank |
| L0–L3 | `tb_conv_layer` (one DUT per layer, via parameters) | load the input fmap from vectors for 8 tiles back-to-back; output fmaps bit-exact; measured steady-state cycles/tile ≤ 1056 |
| C1 | `tb_core` | 1000 tiles pushed through the L0in producer port; logits bit-exact against `tiles_expected.hex`; steady-state interval ≤ 1056 cycles |
| F1 | `tb_feeder_player` | strip replayed to 640×480 ×2 frames: 2,400 results bit-exact against `frame_expected.csv`; frame cycles ≤ 1.27M (≥39 fps @ 50 MHz); `RES_MISMATCH` = 0 |
| S1 | `tb_slave` | Avalon bus-model reads/writes (copy the task style from `fpga_cnn_pipeline/tb/tb_cnn_slave.sv`); ID/SCRATCH; upload a 64×16 strip through STRIP_DATA; run 3 frames; read RES_DATA; counters correct |

Also run `verilator --lint-only -Wall` on `rtl/`, and record every waiver with its reason.

**Gate P1:** every test passes, and C1 and F1 report the measured interval and fps.

## Phase 2 — Quartus standalone system
Build `tiny_cnn/quartus/tcnn_test/` by copying and adapting `fpga_cnn_pipeline/quartus/cnn_test/`: `build_system.tcl`, `cnn_test.qsf` (pins), `cnn_test.sdc`, `cnn_test_top.sv` and `cnn_avalon_slave_hw.tcl`.
- **Component:** `tcnn_avalon_slave_hw.tcl`; its fileset lists every `tiny_cnn/rtl/*.sv` plus `gen/tcnn_pkg.sv`.
- **System:** Nios V/m, 64 KB on-chip RAM, JTAG UART, sysid, and `tcnn_avalon_slave` at `0x00032000`. Keep the explicit base addresses; the old Tcl explains why.
- **Top:** drive LEDG[1] from busy and LEDR[0] from `RES_MISMATCH != 0`. That needs a conduit from the component.
- **Build:** `qsys-script --script=build_system.tcl`, then `qsys-generate tcnn_test_sys.qsys --synthesis=VERILOG --output-directory=tcnn_test_sys`, then `quartus_sh --flow compile tcnn_test`.
  - A full build takes about 20 minutes; run it in the background.
  - **Always re-run qsys-generate after any RTL edit** (Platform Designer snapshots the RTL; old progress log, cont. 13).
- **Checks:**
  - **Slow 1200mV 85C** setup and hold slack ≥ 0 at 50 MHz. Never trust the Fast corner.
  - The RAM Summary shows the `.hex` init file on every ROM.
  - LEs ≤ 60%.
  - M9K count and multiplier count logged.

**Gate P2:** it fits and the Slow 85C corner shows no negative slack. If slack is negative, read the worst path from `quartus_sta`, add a register stage on that path, re-run P1 (all tests), then rebuild.

## Phase 3 — Firmware and host
- **`tiny_cnn/firmware/src/main.c`:** copy the UART helpers and command-loop skeleton from `fpga_cnn_pipeline/firmware/src/main.c`. Commands (each reply starts with a 4-byte magic; little-endian):
  - `P` → `PONG`
  - `I` → `TCID` + ID + VERSION + STATUS
  - `W` u32 → `SCRA`
  - `E` → `ECHO`
  - `U` u16 W, u16 SH, then W·SH·3 bytes RGB → write STRIP_ADDR/STRIP_DATA (pitch 640) → `UACK` + u32 byte checksum
  - `R` u16 W, u16 H, u16 SH, u16 NFRAMES → write the regs, start, poll done (with a spin limit) → `RDON` + CYCLES, TILES_DONE, RES_MISMATCH, MIN_GAP, MAX_GAP, FEED_STALL, STATUS
  - `G` u16 n → `GRES` + n × u16 from RES_DATA
  - `X` → soft reset, `XACK`
- **BSP and app:** create them with the commands in `fpga_cnn_pipeline/docs/bringup_runbook.md` (the `niosv-bsp`, `cmake`, `make` and `niosv-download` steps and their PATH setup), using the new `.sopcinfo`.
- **`tiny_cnn/host/tcnn_link.py`:** copy the `CnnLink` transport class (the `juart-terminal --no-quit-on-ctrl-d` subprocess, pump thread, resync) from `fpga_cnn_pipeline/host/cnn_link.py` with the new magics. CLI:
  - `ping | id | echo --bytes N`
  - `upload IMG --w 640 --sh 48`
  - `bench --w 640 --h 480 --sh 48 --frames 200`: prints cycles, **fps = frames·50e6/CYCLES**, tiles/s, min and max gap, mismatches
  - `check`: reads back the results with `G` and compares them with `ref/int_model` on the replayed frame
  - `tiles`: the 1000-tile bit-exact test, 9 strips of 120 tiles (640×48 each, H=48, 1 frame)
  - `--out results/<phase>/` for logs and CSVs

## Phase 4 — Board proof
1. Program the board with `quartus_pgm -m jtag -o "p;output_files/tcnn_test.sof"`, then load the app with `niosv-download -g`.
2. Check the link: `ping`, `id`, `echo 64KB`.
3. `tiles`: 1000/1000 bit-exact against `tiles_expected.hex`.
4. `upload 002675.jpg`, then `bench --frames 200`: `RES_MISMATCH` = 0, `check` bit-exact, **fps ≥ 39**.
5. Record everything, including tiles/s and the gap distribution, in `progress_log.md`, then write `docs/architecture.md` summarising the design and the measured numbers against the old pipeline.

**Gate P4 (project goal):** on real hardware, ≥39 fps at 640×480 with stride-16 tiles, bit-exact results, zero mismatches across 200 frames.

## Later (not in this plan's scope)
- Interval 512 or 256: regenerate with a larger `CIN_PAR`, and allow 2–4 output channels per cycle in `conv_layer`. For 256, `tile_feeder`'s copy (256 cycles) must go to 2 px/cycle.
- Live video: tap the RGB stream of `hardware/rtl/DE2_115_TV` (640×480) into `tile_feeder` and draw anomaly boxes on VGA.

## Critical files to reuse
- `fpga_cnn_pipeline/onnx_to_rtl.py`: `find_conv_chain`, `quantize_multiplier`, `weight_bits` (import)
- `fpga_cnn_pipeline/ref/int_model.py`: `requant`, `IntModel.conv_layer` (copy and adapt)
- `fpga_cnn_pipeline/ref/ort_ref.py` (`OrtRef`) and `check_agreement.py` (import / copy)
- `fpga_cnn_pipeline/rtl/requant.sv`: arithmetic reference only
- `fpga_cnn_pipeline/tb/tb_cnn_slave.sv`: Avalon bus-model tasks
- `fpga_cnn_pipeline/quartus/cnn_test/*`: qsys build script, qsf pins, sdc, top, component tcl
- `fpga_cnn_pipeline/firmware/src/main.c` and `host/cnn_link.py`: UART helpers and transport
- `fpga_cnn_pipeline/docs/bringup_runbook.md`: toolchain PATH and download commands

## Verification summary
- **P0:** `venv/bin/python tiny_cnn/ref/check_agreement.py` passes.
- **P1:** `make -C tiny_cnn sim_all`: all tests print PASS, with the measured interval ≤ 1056 cycles.
- **P2:** the `quartus_sta` Slow 85C summary shows slack ≥ 0.
- **P4:** `host/tcnn_link.py tiles` prints 1000/1000 and `bench --frames 200` prints fps ≥ 39 with 0 mismatches.
