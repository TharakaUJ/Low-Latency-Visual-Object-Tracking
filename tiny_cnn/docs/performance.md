# Resource utilization and speed

Measured numbers for the Tiny-CNN accelerator (`tinycnn_qat_int4.onnx`,
16x16x3 patch -> 2 logits) on the DE2-115 (Cyclone IV E, `EP4CE115F29C7`),
50 MHz system clock. See `architecture.md` for the design and
`progress_log.md` for the full dated history behind every number here.

## FPGA resource utilization (Quartus Prime 25.1std, Fitter report)

| Resource | Used | Available | % |
|---|---|---|---|
| Total logic elements | 100,309 | 114,480 | **88%** |
| -- combinational functions | 71,836 | 114,480 | 63% |
| -- dedicated logic registers | 62,938 | 114,480 | 55% |
| Total memory bits | 1,919,232 | 3,981,312 | 48% |
| Embedded 9-bit multipliers | 42 | 532 | 8% |
| Total pins | 32 | 529 | 6% |
| PLLs | 0 | 4 | 0% |

The design **fits and closes timing at 88% LE**, over the project plan's
originally-set <=60% target, but with no failed placement and positive
timing margin (see below). LE usage is dominated by the fully-parallel MAC
lane counts chosen to hit ~1024 cycles/tile on every layer (up to 16
channels x 9 taps = 144 parallel 8x4-bit multiply-accumulate lanes for
L1/L3). Memory (M9K) and multiplier usage are both comfortably low --
lowering `CIN_PAR` (trading some throughput for area via a larger `NPASS`)
is the natural next lever if LE headroom is ever needed for other logic on
the same FPGA, and was deliberately not pursued in this project.

## Timing closure (`quartus_sta`, every corner)

| Corner | Setup slack | Hold slack | TNS |
|---|---|---|---|
| **Slow 1200mV 85C** (worst case, the one that matters) | **+2.042 ns** | **+0.329 ns** | 0.000 |
| Slow 1200mV 0C | +3.846 ns | +0.293 ns | 0.000 |
| Fast 1200mV 0C | +10.924 ns | +0.108 ns | 0.000 |

All checks (setup, hold, recovery, removal, minimum pulse width) are
non-negative in every corner, on both `CLOCK_50` and the JTAG debug clock
(`altera_reserved_tck`). **This is real, positive timing margin at 50 MHz
in the worst-case corner** -- the specific thing the earlier
shared-engine design (see `architecture.md`) never achieved.

## Per-layer cycle budget (RTL simulation, Verilator, bit-exact)

Every layer was independently tuned (`CIN_PAR`/`NPASS`, see
`architecture.md`'s schedule table) to land close to the same cycles/tile,
so all 4 layers can run concurrently on different tiles without one
becoming a bottleneck:

| Layer | CIN->COUT | measured cycles/tile |
|---|---|---|
| L0 | 3->16  | 1032 |
| L1 | 16->16 | 1034 |
| L2 | 16->32 | 1033 |
| L3 | 32->32 | 1034 |

## End-to-end throughput

| Measurement | Where | Value |
|---|---|---|
| Steady-state gap between results | Gate C1 (sim, 1000 tiles) | 1037 cycles, constant |
| Steady-state gap between results | Gate F1 (sim, 640x480 x2 frames) | 1037 cycles, constant |
| Steady-state gap between results | **Gate P4 (real board, 640x480 x200 frames)** | **1037 cycles, constant** |
| Frames per second | Gate F1 (sim) | ~39.96 fps |
| **Frames per second** | **Gate P4 (real board)** | **40.18 fps** |
| Tiles per second | Gate P4 (real board) | 48,213 tiles/s |
| Bit-exact correctness | Gate P4 (real board) | 240,000/240,000 tiles, 0 mismatches |
| Bit-exact correctness | Gate P4 tiles test (real board) | 1000/1000 tiles, 0 mismatches |

The real-hardware steady-state gap (1037 cycles/tile) matches the RTL
simulation's number exactly, and the measured fps (40.18) is consistent
with 50e6 / 1037 / (1200 tiles/frame at 640x480) -- i.e. the accelerator
behaves identically on real silicon as it does in simulation, with no
timing-related corruption (which `result_sink`'s cross-frame mismatch
check, comparing frame 0's results against every later frame's, is
specifically designed to catch and reported 0 of, across all 200 frames).

## Comparison to the earlier (shared-engine) design

| | Old (`fpga_cnn_pipeline`, larger model) | New (this project) |
|---|---|---|
| Architecture | 1 shared, time-multiplexed engine | 4 concurrent, layer-pipelined engines |
| Measured fps | ~1 fps | **40.18 fps (real hardware)** |
| Timing closure @ 50 MHz | Never achieved (best: -16.7 ns slack) | **Achieved (+2.04 ns slack, Slow 85C)** |

~40x faster, and the timing closure the old design's B18/B19 findings
never resolved.

## Firmware / link

| | Value |
|---|---|
| Firmware image size | 35.11 KB (of 64 KB on-chip RAM) |
| Measured JTAG UART link throughput | ~623 B/s (one-time strip upload only, not per-frame) |
| Strip upload time (640x48 RGB, 92,160 B) | ~148 s, once per bench run |
