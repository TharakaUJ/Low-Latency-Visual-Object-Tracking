#!/usr/bin/env python3
"""
generate_tinycnn_sv.py
=======================
Reads the statically-quantized (int8 QDQ) ONNX export of the tiny CNN and
generates two SystemVerilog files:

    tinycnn_pkg.sv   - all weights/biases/requant multipliers/dimensions,
                        hardcoded as localparams (this is the "single
                        variable" artifact -- regenerate this whenever you
                        retrain/requantize the network).
    tinycnn_top.sv   - structural wiring: instantiates conv_engine per
                        conv layer, dp_ram activation buffers between
                        them, and gap_fc_argmax at the end, sequenced by
                        a small FSM. Regenerated alongside the package so
                        the two always agree on layer count/shape.

conv_engine.sv, gap_fc_argmax.sv and dp_ram.sv are generic, topology-
independent engines (hand-written, not regenerated) that tinycnn_top.sv
instantiates.

Requirements
------------
    pip install onnx numpy

Usage
-----
    python3 generate_tinycnn_sv.py <model_int8.onnx> [-o OUTDIR]

Assumptions this generator relies on (true for this export, and checked
at runtime -- it will raise a clear error if violated by a future export):
    * Per-channel int8 symmetric weight quantization (weight zero_point==0)
    * Per-tensor uint8 asymmetric activation quantization, but with
      zero_point == 0 everywhere (calibration produced this because all
      activations are post-ReLU / non-negative), so plain unsigned
      fixed-point math is enough -- no cross terms needed.
    * Topology: N x (Conv3x3 pad1 -> ReLU) blocks, feeding
      GlobalAveragePool -> Flatten -> Gemm (fully-connected) -> logits.
    * The graph is the standard onnxruntime static-quant QDQ output
      (QuantizeLinear/DequantizeLinear pairs bracketing float Conv/Gemm
      nodes) -- see NODE_MAP below if your export names things differently.
"""
import argparse
import sys
import numpy as np
import onnx
from onnx import numpy_helper

Q31 = 1 << 31


# --------------------------------------------------------------------------
# ONNX parsing
# --------------------------------------------------------------------------
def load_inits(model):
    return {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}


def find_conv_dequant_chain(model):
    """
    Walk the QDQ graph and pull out, in execution order, each
    Conv node together with the DequantizeLinear-fed weight/bias
    initializers and the DequantizeLinear/QuantizeLinear activation
    scales that surround it, plus stride. Also locates the final
    GlobalAveragePool scale pair and the Gemm (FC) layer.
    """
    g = model.graph
    inits = load_inits(model)

    # map: dequantized tensor name -> (quantized_initializer_name, scale_name, zp_name)
    dq_src = {}
    for n in g.node:
        if n.op_type == "DequantizeLinear" and n.input[0] in inits:
            dq_src[n.output[0]] = n.input  # (quantized, scale, zp)

    # map: activation tensor name -> scale initializer name (from QuantizeLinear nodes)
    act_scale = {}
    for n in g.node:
        if n.op_type == "QuantizeLinear":
            act_scale[n.input[0]] = n.input[1]  # produced-tensor -> its scale

    conv_nodes = [n for n in g.node if n.op_type == "Conv"]
    gemm_nodes = [n for n in g.node if n.op_type == "Gemm"]
    gap_nodes = [n for n in g.node if n.op_type == "GlobalAveragePool"]
    if len(gemm_nodes) != 1 or len(gap_nodes) != 1:
        raise RuntimeError("Expected exactly one Gemm and one GlobalAveragePool node")

    input_name = g.input[0].name
    input_scale_name = act_scale.get(input_name)
    if input_scale_name is None:
        raise RuntimeError(f"Could not find a QuantizeLinear scale for graph input '{input_name}'")

    layers = []
    cur_in_scale_name = input_scale_name
    for n in conv_nodes:
        w_dq_in = n.input[1]
        b_dq_in = n.input[2]
        if w_dq_in not in dq_src or b_dq_in not in dq_src:
            raise RuntimeError(f"Conv node {n.name} weight/bias not behind DequantizeLinear as expected")
        w_q_name, w_scale_name, w_zp_name = dq_src[w_dq_in]
        b_q_name, b_scale_name, b_zp_name = dq_src[b_dq_in]

        strides = [1, 1]
        pads = [1, 1, 1, 1]
        for a in n.attribute:
            if a.name == "strides":
                strides = list(a.ints)
            if a.name == "pads":
                pads = list(a.ints)
        if pads != [1, 1, 1, 1]:
            raise RuntimeError(f"Conv node {n.name} has non-(1,1,1,1) padding; generator assumes pad=1 everywhere")
        if strides[0] != strides[1]:
            raise RuntimeError(f"Conv node {n.name} has asymmetric stride; not supported")

        conv_out_tensor = n.output[0]
        out_scale_name = act_scale.get(conv_out_tensor)
        if out_scale_name is None:
            raise RuntimeError(f"No output QuantizeLinear scale found for {conv_out_tensor}")

        layers.append(dict(
            name=n.name,
            w=inits[w_q_name].astype(np.int8),
            w_scale=inits[w_scale_name].astype(np.float64),
            w_zp=inits[w_zp_name],
            b=inits[b_q_name].astype(np.int32),
            in_scale=float(inits[cur_in_scale_name]),
            out_scale=float(inits[out_scale_name]),
            stride=int(strides[0]),
        ))
        cur_in_scale_name = out_scale_name

        if np.any(layers[-1]["w_zp"] != 0):
            raise RuntimeError(f"Conv {n.name}: weight zero_point != 0 not supported by this generator")

    gap_in_scale_name = cur_in_scale_name
    gap_node = gap_nodes[0]
    gap_out_scale_name = act_scale.get(gap_node.output[0])
    if gap_out_scale_name is None:
        raise RuntimeError("No QuantizeLinear scale found after GlobalAveragePool")

    gemm = gemm_nodes[0]
    fc_w_dq_in = gemm.input[1]
    fc_b_dq_in = gemm.input[2]
    fc_w_q_name, fc_w_scale_name, fc_w_zp_name = dq_src[fc_w_dq_in]
    fc_b_q_name, fc_b_scale_name, fc_b_zp_name = dq_src[fc_b_dq_in]
    if np.any(inits[fc_w_zp_name] != 0):
        raise RuntimeError("FC weight zero_point != 0 not supported by this generator")

    fc = dict(
        w=inits[fc_w_q_name].astype(np.int8),          # (NCLS, CF)
        w_scale=inits[fc_w_scale_name].astype(np.float64),
        b=inits[fc_b_q_name].astype(np.int32),
        in_scale=float(inits[gap_in_scale_name]),
    )

    input_hw = None
    for vi in g.value_info:
        pass
    in_shape = [d.dim_value for d in g.input[0].type.tensor_type.shape.dim]

    return dict(
        input_shape=in_shape,               # [N,C,H,W]
        input_scale=float(inits[input_scale_name]),
        layers=layers,
        gap_in_scale=float(inits[gap_in_scale_name]),
        gap_out_scale=float(inits[gap_out_scale_name]),
        fc=fc,
    )


def q31_mult_shift(m):
    """
    Decompose a real multiplier m>0 (any magnitude) into an unsigned Q0.31
    mantissa 'mult' (in [2^30, 2^31)) and a right-shift amount 'shift', such
    that   m ~= mult * 2^(shift-31)   i.e.   round(acc*m) == (acc*mult) >>> shift.
    This is the same decomposition TFLite uses for per-channel requantization,
    generalized so it works whether m is <1 (typical conv/FC layers) or >1
    (can happen after GlobalAveragePool, whose calibrated output scale need
    not match the plain-averaging formula).
    Returns (mult: uint32 array, shift: int array), both same shape as m.
    """
    m = np.atleast_1d(np.asarray(m, dtype=np.float64))
    if np.any(m <= 0):
        raise RuntimeError("Non-positive requant multiplier encountered")
    significand, exponent = np.frexp(m)   # m == significand * 2**exponent, significand in [0.5,1)
    mult = np.round(significand * Q31).astype(np.int64)
    shift = (31 - exponent).astype(np.int64)
    # handle the round-to-2^31 edge case (significand rounds up to 1.0)
    overflow = mult >= Q31
    mult[overflow] //= 2
    shift[overflow] -= 1
    if np.any(shift < 0):
        raise RuntimeError(
            f"Requant multiplier too large (needs negative shift): max m={m.max()}. "
            "This generator assumes shift>=0; extend q31_mult_shift if this network needs it."
        )
    if np.any(mult >= Q31) or np.any(mult < (1 << 30)):
        raise RuntimeError("Q0.31 mantissa out of expected range")
    return mult.astype(np.uint32), shift.astype(np.int64)


# --------------------------------------------------------------------------
# SystemVerilog formatting helpers
# --------------------------------------------------------------------------
def sv_signed(width, v):
    """Format a signed integer as an SV sized literal, e.g. -59 -> -8'sd59."""
    v = int(v)
    return f"-{width}'sd{-v}" if v < 0 else f"{width}'sd{v}"


def fmt_w_array(w):
    # w: (COUT,CIN,3,3) int8 -> SV literal for
    #   logic signed [7:0] W [0:COUT-1][0:CIN-1][0:2][0:2]
    cout, cin, kh, kw = w.shape
    lines = ["'{"]
    for co in range(cout):
        lines.append("  '{ // co=%d" % co)
        for ci in range(cin):
            rows = ", ".join(
                "'{" + ", ".join(sv_signed(8, w[co,ci,r,c]) for c in range(kw)) + "}"
                for r in range(kh)
            )
            lines.append(f"    '{{ {rows} }}{',' if ci != cin-1 else ''}")
        lines.append("  }" + ("," if co != cout-1 else ""))
    lines.append("}")
    return "\n".join(lines)


def fmt_i32_array(arr):
    return "'{" + ", ".join(sv_signed(32, v) for v in arr) + "}"


def fmt_u32_array(arr):
    return "'{" + ", ".join(f"32'd{int(v)}" for v in arr) + "}"


def fmt_shift_array(arr):
    return "'{" + ", ".join(f"6'd{int(v)}" for v in arr) + "}"


def fmt_w2d_array(w):
    # w: (NCLS,CF) int8 -> logic signed [7:0] W [0:NCLS-1][0:CF-1]
    ncls, cf = w.shape
    lines = ["'{"]
    for k in range(ncls):
        row = ", ".join(sv_signed(8, w[k,c]) for c in range(cf))
        lines.append(f"  '{{ {row} }}{',' if k != ncls-1 else ''}")
    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------
def gen_pkg(model_info, module_name="tinycnn"):
    layers = model_info["layers"]
    in_c, in_h, in_w = model_info["input_shape"][1:4]

    dims = []
    h, w, c = in_h, in_w, in_c
    for i, L in enumerate(layers):
        cout, cin, kh, kw = L["w"].shape
        stride = L["stride"]
        hout = (h + 2 - 3) // stride + 1
        wout = (w + 2 - 3) // stride + 1
        dims.append(dict(idx=i, cin=cin, cout=cout, hin=h, win=w, hout=hout, wout=wout, stride=stride))
        h, w, c = hout, wout, cout
    final_cf, final_hf, final_wf = c, h, w

    fc = model_info["fc"]
    ncls, cf = fc["w"].shape
    assert cf == final_cf, f"FC input channels {cf} != final conv channels {final_cf}"

    lines = []
    lines.append(f"// tinycnn_pkg.sv -- AUTO-GENERATED by generate_tinycnn_sv.py. DO NOT EDIT BY HAND.")
    lines.append(f"// Regenerate from the quantized ONNX export instead.")
    lines.append(f"package {module_name}_pkg;")
    lines.append("")
    lines.append(f"  localparam int NUM_LAYERS = {len(layers)};")
    lines.append(f"  localparam int IN_C = {in_c}, IN_H = {in_h}, IN_W = {in_w};")
    lines.append(f"  localparam int NCLS = {ncls};")
    lines.append(f"  localparam int FINAL_CF = {final_cf}, FINAL_HF = {final_hf}, FINAL_WF = {final_wf};")
    lines.append("")

    lines.append("")

    for i, (L, D) in enumerate(zip(layers, dims)):
        mult, shift = q31_mult_shift((L["in_scale"] * L["w_scale"]) / L["out_scale"])
        lines.append(f"  // ---- layer {i}: Conv {D['cin']}->{D['cout']}, {D['hin']}x{D['win']} -> "
                      f"{D['hout']}x{D['wout']}, stride {D['stride']} ----")
        lines.append(f"  localparam int L{i}_CIN = {D['cin']};")
        lines.append(f"  localparam int L{i}_COUT = {D['cout']};")
        lines.append(f"  localparam int L{i}_HIN = {D['hin']};")
        lines.append(f"  localparam int L{i}_WIN = {D['win']};")
        lines.append(f"  localparam int L{i}_STRIDE = {D['stride']};")
        lines.append(f"  localparam logic signed [7:0] L{i}_WEIGHT [0:L{i}_COUT-1][0:L{i}_CIN-1][0:2][0:2] = "
                      f"{fmt_w_array(L['w'])};")
        lines.append(f"  localparam logic signed [31:0] L{i}_BIAS [0:L{i}_COUT-1] = {fmt_i32_array(L['b'])};")
        lines.append(f"  localparam logic [31:0] L{i}_MULT [0:L{i}_COUT-1] = {fmt_u32_array(mult)};")
        lines.append(f"  localparam logic [5:0] L{i}_SHIFT [0:L{i}_COUT-1] = {fmt_shift_array(shift)};")
        lines.append("")

    gap_mult, gap_shift = q31_mult_shift(np.array([model_info["gap_in_scale"] / model_info["gap_out_scale"]]))
    lines.append(f"  // ---- GlobalAveragePool requant ----")
    lines.append(f"  localparam logic [31:0] GAP_MULT = 32'd{int(gap_mult[0])};")
    lines.append(f"  localparam logic [5:0] GAP_SHIFT = 6'd{int(gap_shift[0])};")
    lines.append("")

    fc_in_scale = fc["in_scale"]
    fc_mult, fc_shift = q31_mult_shift(fc_in_scale * fc["w_scale"])
    lines.append(f"  // ---- FC (head) layer, {cf}->{ncls} ----")
    lines.append(f"  localparam logic signed [7:0] FC_WEIGHT [0:NCLS-1][0:{cf}-1] = {fmt_w2d_array(fc['w'])};")
    lines.append(f"  localparam logic signed [31:0] FC_BIAS [0:NCLS-1] = {fmt_i32_array(fc['b'])};")
    lines.append(f"  localparam logic [31:0] FC_MULT [0:NCLS-1] = {fmt_u32_array(fc_mult)};")
    lines.append(f"  localparam logic [5:0] FC_SHIFT [0:NCLS-1] = {fmt_shift_array(fc_shift)};")
    lines.append("")
    lines.append(f"  // input quantization: real_pixel_in_[0,1] -> round(pixel/INPUT_SCALE), clamp to [0,255]")
    lines.append(f"  localparam real INPUT_SCALE = {model_info['input_scale']:.10g};")
    lines.append("")
    lines.append("endpackage")
    return "\n".join(lines), dims, (final_cf, final_hf, final_wf), ncls


def gen_top(module_name, dims, final_shape, ncls):
    pkg = f"{module_name}_pkg"
    final_cf, final_hf, final_wf = final_shape
    n = len(dims)

    lines = []
    lines.append(f"// tinycnn_top.sv -- AUTO-GENERATED by generate_tinycnn_sv.py. DO NOT EDIT BY HAND.")
    lines.append(f"// Structural wiring for the {n}-conv-layer network defined in {pkg}.sv.")
    lines.append(f"// Generic engines used: conv_engine.sv, gap_fc_argmax.sv, dp_ram.sv (hand-written, reused as-is).")
    lines.append(f"import {pkg}::*;")
    lines.append("")
    lines.append(f"module {module_name}_top (")
    lines.append("    input  logic clk,")
    lines.append("    input  logic rst_n,")
    lines.append("")
    lines.append("    // preload the input image (already quantized to uint8, CHW flattened) before pulsing start")
    lines.append("    input  logic                             img_we,")
    lines.append(f"    input  logic [$clog2(IN_C*IN_H*IN_W)-1:0] img_waddr,")
    lines.append("    input  logic [7:0]                       img_wdata,")
    lines.append("")
    lines.append("    input  logic start,")
    lines.append("    output logic done,")
    lines.append(f"    output logic [$clog2(NCLS)-1:0] class_id,")
    lines.append(f"    output logic signed [31:0] class_scores [0:NCLS-1]")
    lines.append(");")
    lines.append("")

    lines.append("    // ---- activation buffers: buf[0] holds the input image, buf[i+1] holds layer i's output ----")
    for i in range(n + 1):
        if i == 0:
            depth = "IN_C*IN_H*IN_W"
        else:
            depth = f"L{i-1}_COUT*((L{i-1}_HIN+2-3)/L{i-1}_STRIDE+1)*((L{i-1}_WIN+2-3)/L{i-1}_STRIDE+1)"
        lines.append(f"    localparam int BUF{i}_DEPTH = {depth};")
    lines.append("")
    for i in range(n + 1):
        lines.append(f"    logic buf{i}_we; logic [$clog2(BUF{i}_DEPTH)-1:0] buf{i}_waddr; logic [7:0] buf{i}_wdata;")
        lines.append(f"    logic [$clog2(BUF{i}_DEPTH)-1:0] buf{i}_raddr; logic [7:0] buf{i}_rdata;")
        lines.append(f"    dp_ram #(.DEPTH(BUF{i}_DEPTH)) u_buf{i} ("
                      f".clk(clk), .we(buf{i}_we), .waddr(buf{i}_waddr), .wdata(buf{i}_wdata), "
                      f".raddr(buf{i}_raddr), .rdata(buf{i}_rdata));")
    lines.append("")
    lines.append("    // image preload feeds buf0's write port whenever the top-level img_we is asserted")
    lines.append("    assign buf0_we    = img_we;")
    lines.append("    assign buf0_waddr = img_waddr;")
    lines.append("    assign buf0_wdata = img_wdata;")
    lines.append("")

    lines.append("    // ---- per-layer conv_engine instances ----")
    for i in range(n):
        lines.append(f"    logic conv{i}_start, conv{i}_done;")
        lines.append(f"    conv_engine #(")
        lines.append(f"        .CIN(L{i}_CIN), .COUT(L{i}_COUT), .HIN(L{i}_HIN), .WIN(L{i}_WIN), "
                      f".STRIDE(L{i}_STRIDE), .CLAMP(1'b1)")
        lines.append(f"    ) u_conv{i} (")
        lines.append(f"        .clk(clk), .rst_n(rst_n), .start(conv{i}_start), .done(conv{i}_done),")
        lines.append(f"        .in_addr(buf{i}_raddr), .in_data(buf{i}_rdata),")
        lines.append(f"        .out_addr(buf{i+1}_waddr), .out_data(buf{i+1}_wdata), .out_we(buf{i+1}_we),")
        lines.append(f"        .weight(L{i}_WEIGHT), .bias(L{i}_BIAS), .mult(L{i}_MULT), .shift(L{i}_SHIFT)")
        lines.append(f"    );")
        lines.append("")

    lines.append("    // ---- GAP + FC + argmax ----")
    lines.append("    logic gap_start, gap_done;")
    lines.append("    gap_fc_argmax #(")
    lines.append(f"        .CF(FINAL_CF), .HF(FINAL_HF), .WF(FINAL_WF), .NCLS(NCLS)")
    lines.append("    ) u_gap_fc (")
    lines.append("        .clk(clk), .rst_n(rst_n), .start(gap_start), .done(gap_done),")
    lines.append(f"        .feat_addr(buf{n}_raddr), .feat_data(buf{n}_rdata),")
    lines.append("        .gap_mult(GAP_MULT), .gap_shift(GAP_SHIFT), .fc_weight(FC_WEIGHT), .fc_bias(FC_BIAS), .fc_mult(FC_MULT), .fc_shift(FC_SHIFT),")
    lines.append("        .class_id(class_id), .class_scores(class_scores)")
    lines.append("    );")
    lines.append("")

    # sequencing FSM: one-hot "current stage" counter driving conv{i}_start / gap_start
    lines.append(f"    // ---- sequencing FSM: run layer 0, wait done, run layer 1, ... , then GAP+FC ----")
    lines.append(f"    localparam int NSTAGE = {n + 1}; // N conv layers + 1 gap/fc stage")
    lines.append("    typedef enum logic [1:0] {ST_IDLE, ST_RUN, ST_DONE} seq_state_t;")
    lines.append("    seq_state_t seq_state;")
    lines.append("    int stage;")
    lines.append("")
    lines.append("    always_comb begin")
    for i in range(n):
        lines.append(f"        conv{i}_start = (seq_state == ST_RUN) && (stage == {i}) && !conv{i}_done_d;")
    lines.append(f"        gap_start = (seq_state == ST_RUN) && (stage == {n}) && !gap_done_d;")
    lines.append("    end")
    lines.append("")
    lines.append("    // rising-edge start pulses: only pulse start for one cycle when entering a stage")
    for i in range(n):
        lines.append(f"    logic conv{i}_done_d;")
    lines.append("    logic gap_done_d;")
    lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
    lines.append("        if (!rst_n) begin")
    for i in range(n):
        lines.append(f"            conv{i}_done_d <= 1'b0;")
    lines.append("            gap_done_d <= 1'b0;")
    lines.append("            seq_state <= ST_IDLE;")
    lines.append("            stage <= 0;")
    lines.append("            done <= 1'b0;")
    lines.append("        end else begin")
    lines.append("            unique case (seq_state)")
    lines.append("                ST_IDLE: begin")
    lines.append("                    done <= 1'b0;")
    lines.append("                    if (start) begin")
    lines.append("                        stage <= 0;")
    for i in range(n):
        lines.append(f"                        conv{i}_done_d <= 1'b0;")
    lines.append("                        gap_done_d <= 1'b0;")
    lines.append("                        seq_state <= ST_RUN;")
    lines.append("                    end")
    lines.append("                end")
    lines.append("                ST_RUN: begin")
    for i in range(n):
        lines.append(f"                    if (stage == {i} && conv{i}_done) conv{i}_done_d <= 1'b1;")
    lines.append(f"                    if (stage == {n} && gap_done) gap_done_d <= 1'b1;")
    lines.append("                    if (stage < NSTAGE-1) begin")
    for i in range(n):
        lines.append(f"                        if (stage == {i} && conv{i}_done) stage <= stage + 1;")
    lines.append("                    end else begin")
    lines.append("                        if (gap_done) seq_state <= ST_DONE;")
    lines.append("                    end")
    lines.append("                end")
    lines.append("                ST_DONE: begin")
    lines.append("                    done <= 1'b1;")
    lines.append("                    seq_state <= ST_IDLE;")
    lines.append("                end")
    lines.append("                default: seq_state <= ST_IDLE;")
    lines.append("            endcase")
    lines.append("        end")
    lines.append("    end")
    lines.append("")
    lines.append("endmodule")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx_path", help="path to the int8 QDQ ONNX model")
    ap.add_argument("-o", "--outdir", default="rtl_generated")
    ap.add_argument("--module-name", default="tinycnn")
    args = ap.parse_args()

    model = onnx.load(args.onnx_path)
    info = find_conv_dequant_chain(model)

    pkg_text, dims, final_shape, ncls = gen_pkg(info, args.module_name)
    top_text = gen_top(args.module_name, dims, final_shape, ncls)

    import os
    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, f"{args.module_name}_pkg.sv"), "w") as f:
        f.write(pkg_text + "\n")
    with open(os.path.join(args.outdir, f"{args.module_name}_top.sv"), "w") as f:
        f.write(top_text + "\n")

    print(f"Wrote {args.outdir}/{args.module_name}_pkg.sv")
    print(f"Wrote {args.outdir}/{args.module_name}_top.sv")
    print(f"Layers: {len(dims)}, final feature map: {final_shape}, classes: {ncls}")
    print("Copy conv_engine.sv, gap_fc_argmax.sv and dp_ram.sv from the rtl/ folder alongside these.")


if __name__ == "__main__":
    sys.exit(main())
