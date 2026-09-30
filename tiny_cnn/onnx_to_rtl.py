#!/usr/bin/env python3
"""
onnx_to_rtl.py
==============
Parses the QAT-quantized tinycnn ONNX graph (Conv/QuantizeLinear/DequantizeLinear
sandwich pattern, int8 per-channel weights, uint8 per-tensor activations, int32
bias) and emits everything a Verilog build needs:

  gen/layers.json            - machine-readable layer list (shapes, strides, requant)
  gen/params_pkg.sv          - SystemVerilog package: layer shape/stride localparams
                                + per-layer TFLite-style requant multiplier/shift arrays
  gen/weights/wN_chOC.hex    - $readmemh files, one per (layer, output channel),
                                signed int8 weights, Cin*3*3 deep, MSB-first tap order
                                (oc, ic, kh, kw) flattened as ic*9+kh*3+kw
  gen/bias/bN.hex            - $readmemh, int32 bias per output channel (32-bit hex)
  gen/head_weight.hex        - int8 [2][128] head GEMM weights
  gen/head_bias.hex          - int32 [2] head GEMM bias

Requantization is computed exactly as TFLite/QNNPACK does it: a 32-bit fixed-point
multiplier M0 (Q31, i.e. treated as 0.31 fixed point, always in [0.5,1)) plus a
right-shift, per output channel, so hardware only needs a 32x8(or wider)->64 signed
multiply + arithmetic right shift + round + clamp. This avoids any floating point
in the FPGA.

Usage:
    pip install onnx numpy
    python3 onnx_to_rtl.py tinycnn_patch16_int8.onnx --outdir gen
"""
import argparse, json, math, os
import numpy as np
import onnx
from onnx import numpy_helper


def get_inits(model):
    return {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}


def weight_bits(w_q):
    """Returns 4 for an int4-quantized weight tensor (ml_dtypes.int4, values
    in [-8,7]), 8 for a plain int8 tensor. Auto-detected from the array's
    dtype name so both tinycnn_patch16_int8.onnx and a QAT int4 export
    (e.g. tinycnn_qat_int4.onnx) work with this same script."""
    name = np.dtype(w_q.dtype).name
    if "int4" in name:
        return 4
    return 8


def quantize_multiplier(real_multiplier):
    """TFLite QuantizeMultiplier: returns (M0 int32 in Q31, right_shift as positive int)
    such that  real_multiplier ~= M0 * 2^-31 * 2^-right_shift
    i.e. hardware does:  round( (acc * M0) >> (31 + right_shift) )  with acc,M0 signed."""
    if real_multiplier == 0.0:
        return 0, 0
    q, shift = math.frexp(real_multiplier)   # real_multiplier = q * 2^shift, 0.5<=|q|<1
    q_fixed = int(round(q * (1 << 31)))
    if q_fixed == (1 << 31):
        q_fixed //= 2
        shift += 1
    assert q_fixed <= 2**31 - 1
    right_shift = 31 - shift
    if right_shift < 0:
        # multiplier >= 2, extremely unlikely for a requant step; clamp defensively
        q_fixed >>= -right_shift
        right_shift = 0
    return q_fixed, right_shift


def find_conv_chain(model):
    """Walk the graph and pull out, in order, each Conv node together with the
    scale/zero_point of its (uint8) input activation and (uint8) output activation,
    plus the per-channel int8 weight tensor and int32 bias tensor already dequant-lined
    back to their *_quantized initializers."""
    inits = get_inits(model)
    nodes = {n.output[0]: n for n in model.graph.node}
    # map: dequant output name -> (scale, zero_point) of the uint8 tensor that feeds it
    # activation scale/zp for the graph input:
    act_scale = {"patches_DequantizeLinear_Output": (float(inits["patches_scale"]), int(inits["patches_zero_point"]))}

    convs = []
    for n in model.graph.node:
        if n.op_type != "Conv":
            continue
        in_act_name = n.input[0]
        w_dq_name = n.input[1]
        bias_name = n.input[2]
        out_name = n.output[0]  # e.g. 'relu', 'relu_1', ... (this IS the pre-quant fp name)

        in_scale, in_zp = act_scale[in_act_name]

        # find the weight_quantized / weight_scale feeding w_dq_name
        w_dq_node = nodes[w_dq_name]
        w_q = inits[w_dq_node.input[0]]           # int8 [OC,IC,KH,KW]
        w_scale = inits[w_dq_node.input[1]]        # float [OC]
        w_zp = inits[w_dq_node.input[2]]           # int8 [OC], expected all 0

        bias_dq_node = nodes[bias_name]
        bias_q = inits[bias_dq_node.input[0]].astype(np.int64)   # int32 [OC]

        # attrs
        attrs = {a.name: onnx.helper.get_attribute_value(a) for a in n.attribute}
        stride = list(attrs["strides"])
        pads = list(attrs["pads"])
        ksize = list(attrs["kernel_shape"])

        # find the QuantizeLinear that consumes this conv's fp output -> gives out_scale/zp
        # and register the *_DequantizeLinear_Output as the act_scale entry for the next conv
        q_node = None
        for nn in model.graph.node:
            if nn.op_type == "QuantizeLinear" and nn.input[0] == out_name:
                q_node = nn
                break
        out_scale = float(inits[q_node.input[1]])
        out_zp = int(inits[q_node.input[2]])
        dq_node = None
        for nn in model.graph.node:
            if nn.op_type == "DequantizeLinear" and nn.input[0] == q_node.output[0]:
                dq_node = nn
                break
        act_scale[dq_node.output[0]] = (out_scale, out_zp)

        convs.append(dict(
            name=n.name, out_name=out_name,
            in_scale=in_scale, in_zp=in_zp,
            out_scale=out_scale, out_zp=out_zp,
            w_q=w_q, w_scale=w_scale, w_zp=w_zp,
            bias_q=bias_q,
            stride=stride, pads=pads, ksize=ksize,
        ))

    # head Gemm
    head_w = inits["head.weight_quantized"]          # int8 [2,128]
    head_w_scale = inits["head.weight_scale"]         # float [2]
    head_bias = inits["head.bias_quantized"].astype(np.int64)  # int32 [2]
    # input to head is 'view' (== last conv's uint8 act, requantized identically -> view_scale==relu_7_scale)
    view_scale = float(inits["view_scale"]); view_zp = int(inits["view_zero_point"])
    logits_scale = float(inits["logits_scale"]); logits_zp = int(inits["logits_zero_point"])

    head = dict(w_q=head_w, w_scale=head_w_scale, bias_q=head_bias,
                in_scale=view_scale, in_zp=view_zp,
                out_scale=logits_scale, out_zp=logits_zp)

    return convs, head


def emit(convs, head, outdir):
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(os.path.join(outdir, "weights"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "bias"), exist_ok=True)

    wbits = weight_bits(convs[0]["w_q"])
    nhex = 1 if wbits == 4 else 2
    wmask = (1 << wbits) - 1

    layers_json = []
    sv_lines = []
    sv_lines.append("// AUTO-GENERATED by onnx_to_rtl.py -- do not edit by hand\n")
    sv_lines.append("package params_pkg;\n")
    sv_lines.append(f"  localparam int NUM_CONV_LAYERS = {len(convs)};\n")

    for li, c in enumerate(convs):
        OC, IC, KH, KW = c["w_q"].shape
        assert (KH, KW) == (3, 3)
        stride = c["stride"][0]
        pad = c["pads"][0]

        # per-channel requant multiplier: real_mult[oc] = in_scale*w_scale[oc]/out_scale
        mults = []
        shifts = []
        for oc in range(OC):
            real_mult = (c["in_scale"] * float(c["w_scale"][oc])) / c["out_scale"]
            m0, rs = quantize_multiplier(real_mult)
            mults.append(m0); shifts.append(rs)

        # weights: wbits-wide two's complement, laid out per output channel,
        # flattened (ic,kh,kw) = ic*9+kh*3+kw
        for oc in range(OC):
            fname = os.path.join(outdir, "weights", f"w{li}_oc{oc:03d}.hex")
            with open(fname, "w") as f:
                flat = c["w_q"][oc].reshape(-1)   # IC*9, row-major (ic,kh,kw)
                for v in flat:
                    iv = int(v) & wmask   # two's complement in hex
                    f.write(f"{iv:0{nhex}x}\n")

        bfname = os.path.join(outdir, "bias", f"b{li}.hex")
        with open(bfname, "w") as f:
            for v in c["bias_q"]:
                iv = int(v) & 0xFFFFFFFF
                f.write(f"{iv:08x}\n")

        layers_json.append(dict(
            idx=li, name=c["name"], in_ch=IC, out_ch=OC, stride=stride, pad=pad,
            in_zp=c["in_zp"], out_zp=c["out_zp"],
            mults=mults, shifts=shifts,
        ))

        sv_lines.append(f"  // layer {li}: {c['name']}  Cin={IC} Cout={OC} stride={stride}")
        sv_lines.append(f"  localparam int L{li}_CIN  = {IC};")
        sv_lines.append(f"  localparam int L{li}_COUT = {OC};")
        sv_lines.append(f"  localparam int L{li}_STRIDE = {stride};")
        sv_lines.append(f"  localparam int L{li}_PAD    = {pad};")
        sv_lines.append(f"  localparam int L{li}_IN_ZP  = {c['in_zp']};")
        sv_lines.append(f"  localparam int L{li}_OUT_ZP = {c['out_zp']};")
        mstr = ", ".join(str(m) for m in mults)
        sstr = ", ".join(str(s) for s in shifts)
        sv_lines.append(f"  localparam int L{li}_MULT [0:{OC-1}] = '{{{mstr}}};")
        sv_lines.append(f"  localparam int L{li}_SHIFT[0:{OC-1}] = '{{{sstr}}};\n")

    # head
    OC2, IC2 = head["w_q"].shape
    with open(os.path.join(outdir, "head_weight.hex"), "w") as f:
        for oc in range(OC2):
            for ic in range(IC2):
                iv = int(head["w_q"][oc, ic]) & wmask
                f.write(f"{iv:0{nhex}x}\n")
    with open(os.path.join(outdir, "head_bias.hex"), "w") as f:
        for v in head["bias_q"]:
            f.write(f"{int(v) & 0xFFFFFFFF:08x}\n")

    head_mults, head_shifts = [], []
    for oc in range(OC2):
        real_mult = (head["in_scale"] * float(head["w_scale"][oc])) / head["out_scale"]
        m0, rs = quantize_multiplier(real_mult)
        head_mults.append(m0); head_shifts.append(rs)

    sv_lines.append(f"  // head GEMM: Cin={IC2} Cout={OC2}")
    sv_lines.append(f"  localparam int HEAD_CIN  = {IC2};")
    sv_lines.append(f"  localparam int HEAD_COUT = {OC2};")
    sv_lines.append(f"  localparam int HEAD_IN_ZP  = {head['in_zp']};")
    sv_lines.append(f"  localparam int HEAD_OUT_ZP = {head['out_zp']};")
    sv_lines.append(f"  localparam int HEAD_MULT [0:{OC2-1}] = '{{{', '.join(map(str,head_mults))}}};")
    sv_lines.append(f"  localparam int HEAD_SHIFT[0:{OC2-1}] = '{{{', '.join(map(str,head_shifts))}}};")
    sv_lines.append("endpackage\n")

    with open(os.path.join(outdir, "params_pkg.sv"), "w") as f:
        f.write("\n".join(sv_lines))

    with open(os.path.join(outdir, "layers.json"), "w") as f:
        json.dump(dict(layers=layers_json, wbits=wbits,
                        head=dict(in_ch=IC2, out_ch=OC2,
                                  mults=head_mults, shifts=head_shifts,
                                  in_zp=head["in_zp"], out_zp=head["out_zp"])),
                   f, indent=2)

    print(f"weight bit-width: {wbits}-bit (auto-detected from ONNX tensor dtype)")
    print(f"Wrote {len(convs)} conv layers + head to {outdir}/")
    print("  params_pkg.sv, layers.json, weights/*.hex, bias/*.hex, head_weight.hex, head_bias.hex")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx_path")
    ap.add_argument("--outdir", default="gen")
    args = ap.parse_args()
    model = onnx.load(args.onnx_path)
    convs, head = find_conv_chain(model)
    emit(convs, head, args.outdir)
