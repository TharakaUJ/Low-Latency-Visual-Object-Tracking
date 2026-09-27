# Resource utilization and speed

Measured numbers for the Tiny-CNN accelerator (`tinycnn_qat_int4.onnx`,
16x16x3 patch -> 2 logits) on the DE2-115 (Cyclone IV E, `EP4CE115F29C7`),
50 MHz system clock. See `architecture.md` for the design (including "The
COUT_PAR=2 optimization pass" that produced these numbers) and
`progress_log.md` for the full dated history.

## FPGA resource utilization (Quartus Prime 25.1std, Fitter report)

| Resource | Used | Available | % |
|---|---|---|---|
| Total logic elements | 57,288 | 114,480 | **50%** |
| Total memory bits | 1,973,920 | 3,981,312 | 50% |
| Embedded 9-bit multipliers | 504 | 532 | **95%** |
| Total pins | 32 | 529 | 6% |
| PLLs | 0 | 4 | 0% |

Compared to the first-generation build (88% LE, 8% multipliers, see
"Superseded first-generation build" below), this build moves almost all MAC
lanes onto the chip's embedded multipliers (`multstyle = "dsp"` on the
product register) and narrows the adder trees to their true bit-growth
(instead of a fixed 24-bit width at every level), which by itself dropped
LE usage from 88% to 32%. That reclaimed headroom was then spent on
`COUT_PAR=2` (2 output channels issued per cycle in every layer, roughly
halving cycles/tile), landing back at 50% LE with the embedded multipliers
now the tighter resource (504/532, 95%). Going further (`COUT_PAR=4`) would
need roughly 1550 MAC lanes total -- more than the board's 532 embedded
multipliers -- so this is close to the practical ceiling for this device
without a wider (>1 pixel/cycle) raster ingest path.

Also fixed in this pass: `result_sink`'s frame-comparison RAM read was not
recognized as a synchronous read by Quartus, so it synthesized as ~33k
registers plus a 2048:1 read mux (~24k ALUTs) instead of block RAM -- more
LEs than the entire 4-layer CNN datapath. Registering that read (1 cycle of
added latency on the mismatch check and the Avalon read-back port, no
behavior change) let it infer as M9K like every other RAM in the design.

## Timing closure (`quartus_sta`, every corner)

| Corner | Setup slack | Hold slack | TNS |
|---|---|---|---|
| **Slow 1200mV 85C** (worst case, the one that matters) | **+4.621 ns** | **+0.289 ns** | 0.000 |
| Slow 1200mV 0C | +6.155 ns | +0.296 ns | 0.000 |
| Fast 1200mV 0C | +12.493 ns | +0.108 ns | 0.000 |

All checks (setup, hold, recovery, removal, minimum pulse width) are
non-negative in every corner, on both `CLOCK_50` and the JTAG debug clock
(`altera_reserved_tck`). Fmax in the worst corner is **65.02 MHz** -- the
design has more timing headroom now than the first-generation build did
(+2.04 ns), despite doing twice the work per cycle, because narrowing the
adder trees and using dedicated multiplier hardware both shortened the
combinational paths that used to dominate.

The first `COUT_PAR=2` compile failed timing (-4.30 ns setup, Fmax
41.15 MHz): the new 2-taps-per-cycle input gather computed each tap's
padding/range check and destination index combinationally in the same
cycle it captured the pixel data. Registering that address arithmetic one
cycle earlier (adding one cycle to the one-time-per-tile gather latency,
fully hidden by the existing gather/issue overlap) fixed it.

## Per-layer cycle budget (RTL simulation, Verilator, bit-exact)

Every layer runs `COUT_PAR=2` (2 output channels issued per cycle) on top
of its own `CIN_PAR`/`NPASS`, so all 4 layers land close to the same
cycles/tile and can run concurrently on different tiles without one
becoming a bottleneck:

| Layer | CIN->COUT | CIN_PAR | NPASS | COUT_PAR | measured cycles/tile |
|---|---|---|---|---|---|
| L0 | 3->16  | 3  | 1 | 2 | 520 |
| L1 | 16->16 | 16 | 1 | 2 | 522 |
| L2 | 16->32 | 8  | 2 | 2 | 521 |
| L3 | 32->32 | 16 | 2 | 2 | 522 |

## End-to-end throughput

| Measurement | Where | Value |
|---|---|---|
| Steady-state gap between results | Gate C1 (sim, 1000 tiles) | 524 cycles, constant |
| Steady-state gap between results | Gate F1 (sim, 640x480 x2 frames) | 524 cycles, constant |
| Steady-state gap between results | **Gate P4 (real board, 640x480 x200 frames)** | **524 cycles, constant** |
| Frames per second | Gate F1 (sim) | ~78.7 fps |
| **Frames per second** | **Gate P4 (real board)** | **79.51 fps** |
| Tiles per second | Gate P4 (real board) | 95,410 tiles/s |
| Bit-exact correctness (cross-frame) | Gate P4 (real board) | 240,000/240,000 tiles, 0 mismatches |
| Bit-exact correctness (vs `ref/int_model.py`) | real board, full 640x480 frame | 1,200/1,200 tiles, 0 mismatches |

The real-hardware steady-state gap (524 cycles/tile) matches the RTL
simulation's number exactly, and the measured fps (79.51) is consistent
with 50e6 / 524 / (1200 tiles/frame at 640x480) -- i.e. the accelerator
behaves identically on real silicon as it does in simulation, with no
timing-related corruption (`result_sink`'s cross-frame mismatch check,
comparing frame 0's results against every later frame's, reported 0 of 0
across all 200 frames). A separate full-frame run compared against
`ref/int_model.py` (the same golden model used to generate the ROMs)
reported 0/1200 mismatches, confirming correctness independent of the
cross-frame self-check.

## Comparison across builds

| | `fpga_cnn_pipeline` (old, larger model) | Tiny-CNN gen 1 (`COUT_PAR=1`) | **Tiny-CNN gen 2 (`COUT_PAR=2`)** |
|---|---|---|---|
| Architecture | 1 shared, time-multiplexed engine | 4 concurrent, layer-pipelined engines | 4 concurrent engines, 2 output channels/cycle each |
| Cycles/tile | n/a (never closed timing) | 1037 | **524** |
| Measured fps | ~1 fps | 40.18 fps | **79.51 fps (real hardware)** |
| Timing closure @ 50 MHz | Never achieved (best: -16.7 ns slack) | Achieved (+2.04 ns slack) | **Achieved (+4.62 ns slack, more margin)** |
| LE usage | n/a | 88% | 50% |
| Embedded multipliers used | n/a | 8% (42/532) | 95% (504/532) |

~80x faster than the original shared-engine design, with more timing margin
than the first Tiny-CNN pass despite twice the throughput.

## Firmware / link

| | Value |
|---|---|
| Firmware image size | 35.11 KB (of 64 KB on-chip RAM) |
| Measured JTAG UART link throughput | ~623 B/s (one-time strip upload only, not per-frame) |
| Strip upload time (640x48 RGB, 92,160 B) | ~148 s, once per bench run |

## Superseded first-generation build (`COUT_PAR=1`)

Kept for reference; see `architecture.md`'s "COUT_PAR=2 optimization pass"
for what changed and why.

| Resource | Used | Available | % |
|---|---|---|---|
| Total logic elements | 100,309 | 114,480 | 88% |
| Total memory bits | 1,919,232 | 3,981,312 | 48% |
| Embedded 9-bit multipliers | 42 | 532 | 8% |

| Corner | Setup slack | Hold slack |
|---|---|---|
| Slow 1200mV 85C | +2.042 ns | +0.329 ns |

| Measurement | Value |
|---|---|
| Steady-state cycles/tile | 1037 |
| Frames per second (real board) | 40.18 |
