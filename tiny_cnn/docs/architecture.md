# Tiny-CNN accelerator: architecture and results

This is the layer-pipelined FPGA implementation of `tinycnn_qat_int4.onnx`
(a 16x16x3 -> 2-logit anomaly classifier: 4 int4 conv layers, global average
pool, FC head) on the DE2-115 (Cyclone IV E, `EP4CE115F29C7`). It answers
the question `instructions.md` asked -- whether real-time streaming
anomaly detection is achievable on this board -- with a measured **yes**:
**40.18 fps at 640x480, bit-exact, 0 mismatches, on real hardware**, at
50 MHz, with timing closure. See `progress_log.md` for the full dated
history (every gate, every bug found and fixed, with root causes); this
file is the summary.

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
pipeline fills (an ~11-cycle warmup, paid once per run, not once per
tile), a new result comes out every **1037 cycles**, not every
(sum of all 4 layers' individual latencies) cycles.

Each layer's internal parallelism (`CIN_PAR`, `NPASS` -- how many input
channels it processes per cycle, and how many passes it needs over the
output channels) was chosen so every layer takes almost exactly the same
number of cycles per tile (~1024, target from the plan; measured
steady-state is 1037 once gather/issue overlap and pipeline latency are
accounted for) -- see the per-layer schedule table below. That balance is
what lets ALL 4 layers run at the same rate concurrently without one layer
becoming a bottleneck that starves or backs up the others.

| Layer | CIN->COUT | IN->OUT (stride) | CIN_PAR | NPASS | measured cycles/tile |
|---|---|---|---|---|---|
| L0 | 3->16  | 16->8 (s2) | 3  | 1 | 1032 |
| L1 | 16->16 | 8->8  (s1) | 16 | 1 | 1034 |
| L2 | 16->32 | 8->4  (s2) | 8  | 2 | 1033 |
| L3 | 32->32 | 4->4  (s1) | 16 | 2 | 1034 |

`gap_head.sv` (global average pool + FC head) is a simple sequential FSM,
not pipelined at all -- at ~110 cycles/tile of actual work against a
~1024-cycle/tile budget, it has enormous slack and adds no bottleneck.

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
  pixel's `COUT*NPASS` MAC operations, the gatherer is already fetching the
  NEXT pixel's 3x3 window in the background. This is what keeps the
  ~11-cycle one-time gather latency from being paid on every single pixel.
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

## What's left (explicitly out of this pass's scope)

- **LE usage is 88%**, over the plan's <=60% target (though the design
  fits and closes timing at 88%). Most likely dominated by the fully
  parallel `CIN_PAR` lane counts (up to 144 parallel 8x4-bit MAC lanes for
  L1/L3). Lowering `CIN_PAR` (trading some throughput for area, per
  NPASS) is the natural next lever and was deliberately not pursued this
  pass -- the user chose to proceed to board bring-up instead.
- **GAP/head requant constants are hand-copied localparams** in
  `tcnn_core.sv`, not read from `gen/tcnn_pkg.sv` at generate time. Fine
  for one fixed `--cin-par` configuration; revisit before ever regenerating
  with different parameters.
- **Faster intervals (512/256 cycles/tile)**: the plan's "Later" section
  describes this as a follow-on -- regenerate with larger `CIN_PAR` and
  extend `conv_layer`/`tile_feeder` to move more than 1 pixel/cycle.
- **Live video**: tapping a real camera/TV RGB stream into `tile_feeder`
  instead of the strip-replay test harness, and drawing results back onto
  a display -- not attempted; this project proved the compute pipeline,
  not a full application.

## Result summary (see `progress_log.md` for exact commands/dates)

| Gate | What | Result |
|---|---|---|
| P0 | golden model vs onnxruntime | 99.98% within +-1 LSB, 100% argmax |
| U1-U3 | requant/adder-tree/fmap_pingpong units | PASS, bit-exact |
| L0-L3 | per-layer conv_layer | PASS, 1032-1034 cycles/tile |
| C1 | full core, 1000 tiles, simulation | PASS, 1037 cycles/tile steady state |
| F1 | full system, 640x480 x2 frames, simulation | PASS, 0 mismatches, ~40 fps |
| S1 | Avalon register map, simulation | PASS |
| P2 | Quartus fit + timing (Slow 1200mV 85C) | PASS, +2.04ns setup / +0.33ns hold, 88% LE |
| P4 | real board, 1000 tiles + 200 frames @ 640x480 | **PASS, 40.18 fps, 0 mismatches** |
