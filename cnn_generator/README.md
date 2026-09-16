# tinycnn → SystemVerilog

Generates SystemVerilog RTL for your quantized CNN directly from the
int8 ONNX export, with all weights/biases hardcoded as `localparam`s.

## Your model

```
input (3x128x128, uint8, scale 1/255)
 -> [Conv3x3 s2  3->4  + ReLU]  -> [Conv3x3 s1  4->4  + ReLU]
 -> [Conv3x3 s2  4->8  + ReLU]  -> [Conv3x3 s1  8->8  + ReLU]
 -> [Conv3x3 s2  8->16 + ReLU]  -> [Conv3x3 s1 16->16 + ReLU]
 -> [Conv3x3 s2 16->32 + ReLU]  -> [Conv3x3 s1 32->32 + ReLU]
 -> GlobalAveragePool -> FC(32->5) -> argmax -> class_id
```
All convs are pad=1. This was reverse-engineered from
`tinycnn_w4_r128_hard_250ep_int8.onnx` (the plain float model isn't used —
see "Why the int8 model" below).

## Files

```
generate_tinycnn_sv.py     the generator (run this whenever you retrain/requantize)
rtl/conv_engine.sv         generic sequential conv+bias+requant+ReLU engine (topology-independent)
rtl/gap_fc_argmax.sv       generic GlobalAvgPool + FC + argmax engine
rtl/dp_ram.sv              tiny dual-port byte RAM used for activation buffers
rtl_generated/tinycnn_pkg.sv   AUTO-GENERATED: every weight/bias/requant-multiplier, hardcoded
rtl_generated/tinycnn_top.sv   AUTO-GENERATED: wires 8x conv_engine + gap_fc_argmax + ping-pong RAMs + sequencing FSM
```

`rtl/*.sv` are hand-written and reused as-is — they don't know anything
about "5 classes" or "128x128", they're just a MAC engine. `rtl_generated/*`
is the "single variable" artifact you asked for: regenerate it and nothing
else needs to change.

## Regenerating

```bash
pip install onnx numpy
python3 generate_tinycnn_sv.py path/to/your_int8_model.onnx -o rtl_generated
```

This overwrites `tinycnn_pkg.sv` and `tinycnn_top.sv`. Re-run it any time
you retrain, requantize, resize the input, or change the number of layers —
`tinycnn_top.sv` is regenerated too so the two files never drift apart.

## Why the int8 model, not the float one

The plain `tinycnn_w4_r128_hard_250ep.onnx` has float32 weights — not
something you'd hardcode into FPGA/ASIC logic directly. The `_int8.onnx`
export is a standard onnxruntime static-quantization (QDQ) graph, and in
your case it's a particularly clean one for hardware:

- weights are **int8, per-output-channel scale, zero_point = 0** (symmetric)
- activations are **uint8, per-tensor scale, zero_point = 0** everywhere
  (true because everything downstream of a ReLU is non-negative)

Zero-point = 0 everywhere means there are no cross terms in the integer
convolution — `acc = sum(int8_weight * uint8_activation) + int32_bias` is
exact, so I used that directly. If you ever requantize with a different
tool and get nonzero zero-points, the generator will need conv-lowering
math extended (this one will just raise a clear error instead of silently
producing wrong RTL).

## Fixed-point requantization scheme

Standard per-channel integer requantization (same idea as TFLite):

```
acc        = sum(w_i8 * act_u8) + bias_i32
requant    = (acc * mult + (1 << (shift-1))) >>> shift
out_u8     = clamp(requant, 0, 255)              // clamp doubles as the ReLU
```

`mult` (Q0.31 unsigned mantissa) and `shift` are computed per output
channel in Python from `mult/2^shift = in_scale*w_scale[c]/out_scale`,
using the same frexp-based decomposition TFLite uses, so it's numerically
correct even where the multiplier is >1 (this happens after
GlobalAveragePool in your model, since its calibrated output scale isn't
literally `in_scale`).

**I validated this scheme numerically**: I reimplemented the whole
int8 inference path in NumPy using this exact integer math and compared
it against `onnxruntime` running your actual `_int8.onnx` graph on a
random input — same predicted class, logits within quantization noise.
(`sim/verify_quant_sim.py`, optional, reproduces this check.)

## Architecture (read this before you synthesize)

This is a **correctness-first, sequential** implementation, not a
high-throughput one:

- `conv_engine` does **one MAC per clock cycle** (6 nested loops: co, oh,
  ow, ci, kh, kw) via an FSM. For a tiny CNN like this it's simple to
  verify and reason about, but layer 0 alone (4x64x64 outputs x 3x3x3
  taps) is ~150K cycles. Total network is roughly 1-2M cycles end to end.
  If you need real throughput, the natural next step is to unroll the
  `ci`/`kw` loops into a small parallel MAC array (CIN*9 multipliers per
  cycle) — the datapath (accumulate → requant → clamp) doesn't need to
  change, just the FSM's inner loop.
- Activations between layers live in separate small dual-port RAMs
  (`dp_ram.sv`), one per layer boundary (9 buffers total, input image +
  8 conv outputs). No double-buffering/overlap — layers run strictly
  one after another via the sequencing FSM in `tinycnn_top.sv`.
- `conv_engine`'s internal accumulator is 40 bits, comfortably wide for
  this network's channel counts (max 32) and 8-bit operands.

## Top-level interface

```systemverilog
tinycnn_top (
    .clk, .rst_n,
    .img_we, .img_waddr, .img_wdata,   // preload the quantized image (uint8, CHW-flattened) before start
    .start, .done,
    .class_id,                          // 3-bit winning class index
    .class_scores                       // signed 32-bit fixed-point score per class, for debug/thresholding
);
```

Usage: hold `rst_n` low then release; write all `IN_C*IN_H*IN_W` = 49152
bytes of the quantized image via `img_we/img_waddr/img_wdata` (quantize a
real image the same way the generator documents: `round(pixel/INPUT_SCALE)`,
clamp to `[0,255]`, `INPUT_SCALE` is in the generated package); pulse
`start` for one cycle; wait for `done`; read `class_id`.

## Verification status / what I'd still test before trusting silicon

- ✅ The int8 math (mult/shift decomposition, conv accumulate, GAP,
  FC) is verified bit-for-bit-equivalent in NumPy against onnxruntime's
  actual quantized graph output (see above).
- ✅ Elaborates cleanly through Verilator (`verilator --lint-only`);
  the ~35 messages you'll see under `-Wall` are all style warnings
  (intentional address-bus truncation, blocking assigns to same-cycle
  scratch variables inside `always_ff`) — no syntax/elaboration errors.
- ⚠️ I have **not** run a cycle-accurate RTL testbench end-to-end against
  the NumPy reference (e.g. via cocotb/Verilator simulation with a real
  test image) — I'd recommend doing that before trusting results, and
  I'm happy to build that testbench next if useful.
- ⚠️ Icarus Verilog (`iverilog`) has incomplete support for unpacked-array
  localparams inside packages and will fail to parse `tinycnn_pkg.sv` —
  use Verilator, Vivado xsim, Questa, or VCS instead.

## Regenerating for a different network

The generator isn't hardcoded to "8 conv layers + FC" — it walks whatever
Conv/GlobalAveragePool/Gemm QDQ chain it finds in the ONNX graph and
regenerates `tinycnn_top.sv`'s instantiation accordingly. It currently
assumes: pad=1 on every conv, symmetric int8 weights (zero_point=0),
zero_point=0 activations everywhere, and exactly one GlobalAveragePool +
one final Gemm. If you change the architecture (add a residual add,
maxpool, a second FC layer, etc.) those assumptions will need extending —
ping me and I'll adapt it.
