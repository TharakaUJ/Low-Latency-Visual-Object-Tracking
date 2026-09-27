# Tiny-CNN accelerator: architecture and results

This is the layer-pipelined FPGA implementation of `tinycnn_qat_int4.onnx`
(a 16x16x3 -> 2-logit anomaly classifier: 4 int4 conv layers, global average
pool, FC head) on the DE2-115 (Cyclone IV E, `EP4CE115F29C7`). It answers
the question `instructions.md` asked -- whether real-time streaming
anomaly detection is achievable on this board -- with a measured **yes**:
**79.51 fps at 640x480, bit-exact, 0 mismatches, on real hardware**, at
50 MHz, with timing closure. See `progress_log.md` for the full dated
history (every gate, every bug found and fixed, with root causes); this
file is the summary.

This is the second-generation datapath. The first pass landed at 40.18 fps
(1037 cycles/tile, `COUT_PAR=1`, one output channel issued per cycle); a
follow-on optimization pass (see "The COUT_PAR=2 optimization pass" below)
reclaimed wasted FPGA area and doubled per-layer channel parallelism,
reaching 524 cycles/tile without changing the layer-pipelined architecture
described below.

## Why a new design, not a modification of `fpga_cnn_pipeline/`

The existing `fpga_cnn_pipeline/` project targets a different (larger)
model and uses one shared, time-multiplexed compute engine: every layer of
every patch takes its turn on the same hardware, serialized. That design
measured **~1 fps** and never closed timing at 50 MHz (see
`fpga_cnn_pipeline/docs/review_findings.md`, findings B18/B19 -- a LAB-area
overrun and a timing failure that needed several MAC-pipeline rewrites and
still didn't fully close). `fpga_cnn_pipeline/` was left untouched; this is
a new, independent tree (`tiny_cnn/`), reusing only what already worked
there (the TFLite-style fixed-point requant math, the ONNX-parsing helpers,
the Avalon-slave/firmware/host code shape) by import or copy, never by
editing the original files.

## The core architectural difference: layer pipelining, not time-multiplexing

Each of the 4 conv layers gets its **own** hardware engine
(`rtl/conv_layer.sv`, instantiated 4 times with different parameters in
`rtl/tcnn_core.sv`). All 4 engines run **concurrently**, each working on a
**different tile** at any given moment, connected by double-buffered
handshake FIFOs (`rtl/fmap_pingpong.sv`) between every stage:

```
tile_feeder -> L0in fmap -> conv_layer(L0) -> fmap -> conv_layer(L1) -> fmap
            -> conv_layer(L2) -> fmap -> conv_layer(L3) -> fmap -> gap_head -> result_sink
```

While L3 works on tile N, L2 is already working on tile N+1, L1 on N+2, and
L0 is gathering tile N+3's input window. This is what turns 4 layers' worth
of latency into a single steady-state **throughput** number: once the
pipeline fills (a one-time warmup, paid once per run, not once per
tile), a new result comes out every **524 cycles** (79.51 fps measured on
the board; see "The COUT_PAR=2 optimization pass" below), not every
(sum of all 4 layers' individual latencies) cycles.

Each layer's internal parallelism (`CIN_PAR`, `NPASS`, `COUT_PAR` -- how
many input channels it processes per cycle, how many passes it needs over
the input channels, and how many output channels it issues per cycle) was
chosen so every layer takes almost exactly the same number of cycles per
tile -- see the per-layer schedule table below. That balance is what lets
ALL 4 layers run at the same rate concurrently without one layer becoming a
bottleneck that starves or backs up the others.

| Layer | CIN->COUT | IN->OUT (stride) | CIN_PAR | NPASS | COUT_PAR | measured cycles/tile |
|---|---|---|---|---|---|---|
| L0 | 3->16  | 16->8 (s2) | 3  | 1 | 2 | 520 |
| L1 | 16->16 | 8->8  (s1) | 16 | 1 | 2 | 522 |
| L2 | 16->32 | 8->4  (s2) | 8  | 2 | 2 | 521 |
| L3 | 32->32 | 4->4  (s1) | 16 | 2 | 2 | 522 |

`gap_head.sv` (global average pool + FC head) is a simple sequential FSM,
not pipelined at all -- at ~110 cycles/tile of actual work against a
~512-cycle/tile budget, it has enormous slack and adds no bottleneck.

## Fixed-point arithmetic (bit-exact, shared by Python and RTL)

Every conv layer, the GAP, and the FC head use the same TFLite-style
requantization as `fpga_cnn_pipeline`: `out = clamp(round_half_up((acc *
M0) >> shift) + zero_point, 0, 255)`, with `M0`/`shift` computed once at
generation time (`gen_tcnn.py`, via `fpga_cnn_pipeline/onnx_to_rtl.py`'s
`quantize_multiplier()`) and baked into ROMs (or, for GAP/head, into
`tcnn_core.sv`'s localparams -- these were not machine-generated as SV in
this pass, a known simplification, see "What's left" below). This is
verified bit-exact at 3 separate levels: `ref/int_model.py` (the Python
golden model) against onnxruntime running the real quantized ONNX graph
(Gate P0, 99.98% within +-1 LSB, 100% argmax agreement on 10,000 patches);
every RTL module against `int_model.py`'s per-layer dumps (Gate U1-U3,
per-layer conv_layer gates, Gate C1/F1/S1, all in Verilator simulation);
and finally the real board against the same expected values (Gate P4,
1000/1000 tiles and 200 real frames, 0 mismatches).

## Key implementation details worth remembering

- **Issue order inside a tile is pass-major, channel-minor** (`p =
  icnt/COUT, co = icnt%COUT`), not the more obvious channel-major order.
  This keeps a given output channel's two accumulate operations (for
  `NPASS=2` layers) far enough apart in time (`COUT` cycles) to clear the
  MAC pipeline's latency, avoiding a read-after-write hazard on the
  per-channel accumulator -- this exact hazard was the root cause of
  `fpga_cnn_pipeline`'s B19 timing bug, and designing the issue order
  around it from the start avoided rediscovering it here.
- **Gather/issue overlap**: while the issuer works through the current
  pixel's `(COUT/COUT_PAR)*NPASS` MAC-group operations, the gatherer is
  already fetching the NEXT pixel's 3x3 window in the background. This is
  what keeps the one-time gather latency from being paid on every single
  pixel.
- **Bias/mult/shift ride the adder tree's own tag bus**, arriving
  pre-aligned with the sum they belong to regardless of the adder tree's
  actual pipeline depth -- no hand-timed parallel delay chain to get wrong
  if the tree's depth ever changes.
- **Frame replay from on-chip memory**: the real JTAG UART link measured at
  only ~623 B/s (see `progress_log.md`'s board bring-up entry) would make
  streaming full video over the wire hopeless. Instead, `frame_player.sv`
  holds one small strip (640x48 RGB, uploaded once) and replays it as many
  full 640x480 frames (row `r` -> strip row `r % 48`), so the fps
  measurement is never limited by the slow debug link -- only by the
  accelerator itself.
- **`result_sink.sv`'s cross-frame mismatch check**: frame 0's results are
  stored; every later frame's results are compared against them, and any
  difference increments `RES_MISMATCH`. This is specifically there to catch
  timing-related corruption on real silicon that a bit-exact simulation
  can never see -- and it reported 0 across all 200 real board frames.

## The COUT_PAR=2 optimization pass

The first-generation datapath (40.18 fps, 1037 cycles/tile, `COUT_PAR=1`)
fit at 88% LE with only 42/532 embedded multipliers used -- every MAC lane
was built out of general logic. A follow-on pass reclaimed that wasted area
and reinvested it into doubling per-layer throughput:

1. **Fix the actual LE hog first.** A Quartus per-entity resource report
   (`quartus_map`'s "Resource Utilization by Entity") showed `result_sink`
   alone used ~24k ALUTs and ~33k registers -- more than the entire CNN
   datapath (`tcnn_core`, ~42k ALUTs). Its `result_ram` read
   (`result_ram[addr] !== word` on the same cycle as the write-decision
   logic) did not synthesize as a synchronous RAM read, so Quartus built a
   second 2048x16-entry copy entirely out of registers plus a 2048:1 mux to
   read it combinationally. Rewriting the read as a registered
   `always_ff` (one cycle of latency on the mismatch-compare and the
   Avalon read-back port) let both copies infer as M9K block RAM instead,
   for the same bit-exact behavior.
2. **Move MAC lanes onto embedded multipliers, narrow the adder trees.**
   `adder_tree.sv` grows its running-sum width by 1 bit per level (capped at
   the final accumulator width) instead of carrying a fixed 24-bit value
   through every level, and `conv_layer.sv`'s product register now carries a
   `(* multstyle = "dsp"|"logic" *)` attribute per lane (an
   `N_DSP_LANES` parameter controls the split) so most multiplies land on
   the chip's otherwise-idle 9-bit embedded multipliers. This alone dropped
   LE usage from 88% to 32% with **no change in cycles/tile or behavior**
   (a pure area-reclaiming pass, verified bit-exact against every existing
   testbench).
3. **Issue COUT_PAR=2 output channels per cycle in every layer.** Each
   `conv_layer` now has `COUT_PAR` independent sub-lanes (own weight ROM
   read port, own product/adder-tree/accumulate/requant chain), sharing the
   same gathered activation window. This roughly halves `OPS_PER_PIX =
   (COUT/COUT_PAR)*NPASS`, and therefore cycles/tile, at the cost of
   `COUT_PAR` times the MAC lanes and requant pipelines. Because the
   embedded-multiplier headroom (490 free after step 2) exceeds what
   doubling needs, LE usage only rose to 50%.
4. **Feed the gather side twice as fast.** With `OPS_PER_PIX` down to 8 for
   L0/L1 (16 channels / `COUT_PAR=2`), the original 10-cycle serial 3x3
   window gather (1 tap/cycle) no longer fit inside the per-pixel issue
   budget. `fmap_pingpong.sv` gained a second read port (a byte-identical
   mirror of each bank, written on every producer write, so it costs extra
   M9K but no extra write-port contention) so `conv_layer.sv`'s gather now
   fetches 2 taps/cycle, a 6-cycle gather.
5. **First compile failed timing** (-4.30ns setup, Fmax 41 MHz) because the
   new 2-tap-per-cycle gather computed each tap's padding/range check and
   its capture-destination index combinationally in the same cycle it
   latched the pixel data. Registering that address/range arithmetic one
   cycle earlier (so only a small mux feeds the `win_next` write) restored
   positive slack (+4.62ns) with one extra pipeline cycle of gather latency,
   fully absorbed by the same gather/issue overlap described above.

None of this changed the packed weight-ROM file format, `gen_tcnn.py`, or
`ref/int_model.py` -- each `COUT_PAR` sub-lane simply loads its own copy of
the same per-layer weight ROM and selects which output-channel group it
services via its `CO_BASE` offset.

## What's left (explicitly out of this pass's scope)

- **GAP/head requant constants are hand-copied localparams** in
  `tcnn_core.sv`, not read from `gen/tcnn_pkg.sv` at generate time. Fine
  for one fixed `--cin-par` configuration; revisit before ever regenerating
  with different parameters.
- **Clock is still 50 MHz.** Post-`COUT_PAR=2` timing closes with +4.62ns
  setup slack in the worst corner (Fmax 65.02 MHz) -- there is room for a
  PLL to raise the clock (e.g. ~60 MHz -> ~94 fps) that was not pursued
  this pass.
- **Further COUT_PAR increase (e.g. 4, ~260 cycles/tile)**: would need
  ~1550 MAC lanes total, beyond the board's 532 embedded multipliers, and
  the single-pixel-per-cycle raster ingest (`tile_feeder.sv`) caps frame
  throughput near ~162 fps regardless of compute speed -- diminishing
  returns past `COUT_PAR=2` without also widening ingest.
- **Live video**: tapping a real camera/TV RGB stream into `tile_feeder`
  instead of the strip-replay test harness, and drawing results back onto
  a display -- not attempted; this project proved the compute pipeline,
  not a full application.

## Result summary (see `progress_log.md` for exact commands/dates)

| Gate | What | Result |
|---|---|---|
| P0 | golden model vs onnxruntime | 99.98% within +-1 LSB, 100% argmax |
| U1-U3 | requant/adder-tree/fmap_pingpong units | PASS, bit-exact |
| L0-L3 | per-layer conv_layer | PASS, 520-522 cycles/tile |
| C1 | full core, 1000 tiles, simulation | PASS, 524 cycles/tile steady state |
| F1 | full system, 640x480 x2 frames, simulation | PASS, 0 mismatches, ~78.7 fps |
| S1 | Avalon register map, simulation | PASS |
| P2 | Quartus fit + timing (Slow 1200mV 85C) | PASS, +4.62ns setup / +0.29ns hold, 50% LE, 95% multipliers |
| P4 | real board, 200 frames @ 640x480 | **PASS, 79.51 fps, 0 mismatches (240,000 tiles)** |
| — | real board, full frame vs `ref/int_model.py` | **PASS, 1200/1200 tiles bit-exact** |

Superseded first-generation (`COUT_PAR=1`) results, for reference:

| Gate | What | Result |
|---|---|---|
| L0-L3 | per-layer conv_layer | PASS, 1032-1034 cycles/tile |
| C1 | full core, 1000 tiles, simulation | PASS, 1037 cycles/tile steady state |
| F1 | full system, 640x480 x2 frames, simulation | PASS, 0 mismatches, ~40 fps |
| P2 | Quartus fit + timing (Slow 1200mV 85C) | PASS, +2.04ns setup / +0.33ns hold, 88% LE, 8% multipliers |
| P4 | real board, 1000 tiles + 200 frames @ 640x480 | PASS, 40.18 fps, 0 mismatches |
