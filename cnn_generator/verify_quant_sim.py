#!/usr/bin/env python3
"""
Standalone reference check: reimplements the int8 fixed-point inference
path (same math the SystemVerilog uses) in NumPy and compares it against
onnxruntime running the real quantized ONNX graph. Run this after
regenerating the RTL to sanity-check the requant scheme still matches.

    pip install onnx onnxruntime numpy
    python3 verify_quant_sim.py path/to/model_int8.onnx
"""
import sys
import numpy as np
import onnx
import onnxruntime as ort
from onnx import numpy_helper


def conv_layer(x_u8, w_i8, w_scale, bias_i32, in_scale, out_scale, stride, clamp01=True):
    Cin, H, W = x_u8.shape
    Cout = w_i8.shape[0]
    xp = np.pad(x_u8.astype(np.int64), ((0, 0), (1, 1), (1, 1)))
    Hout = (H + 2 - 3) // stride + 1
    Wout = (W + 2 - 3) // stride + 1
    acc = np.zeros((Cout, Hout, Wout), dtype=np.int64)
    for oh in range(Hout):
        for ow in range(Wout):
            ih0, iw0 = oh * stride, ow * stride
            patch = xp[:, ih0:ih0 + 3, iw0:iw0 + 3]
            acc[:, oh, ow] = np.tensordot(w_i8.astype(np.int64), patch, axes=([1, 2, 3], [0, 1, 2])) + bias_i32
    M = (in_scale * w_scale) / out_scale
    MULT = np.round(M * (2 ** 31)).astype(np.int64)
    out = (acc * MULT[:, None, None] + (1 << 30)) >> 31
    if clamp01:
        out = np.clip(out, 0, 255)
    return out.astype(np.int32)


def main(onnx_path):
    np.random.seed(0)
    model = onnx.load(onnx_path)
    inits = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}

    img = np.random.rand(1, 3, 128, 128).astype(np.float32)
    sess = ort.InferenceSession(onnx_path)
    ref = sess.run(["logits"], {"input": img})[0]

    input_scale = float(inits['input_scale'])
    x = np.clip(np.round(img[0] / input_scale), 0, 255).astype(np.int32)

    layer_names = [
        ('onnx::Conv_79_quantized', 'onnx::Conv_79_scale', 'onnx::Conv_80_quantized', input_scale, 0.02354955, 2),
        ('onnx::Conv_82_quantized', 'onnx::Conv_82_scale', 'onnx::Conv_83_quantized', 0.02354955, 0.040961053, 1),
        ('onnx::Conv_85_quantized', 'onnx::Conv_85_scale', 'onnx::Conv_86_quantized', 0.040961053, 0.055125307, 2),
        ('onnx::Conv_88_quantized', 'onnx::Conv_88_scale', 'onnx::Conv_89_quantized', 0.055125307, 0.05058564, 1),
        ('onnx::Conv_91_quantized', 'onnx::Conv_91_scale', 'onnx::Conv_92_quantized', 0.05058564, 0.038443405, 2),
        ('onnx::Conv_94_quantized', 'onnx::Conv_94_scale', 'onnx::Conv_95_quantized', 0.038443405, 0.03752272, 1),
        ('onnx::Conv_97_quantized', 'onnx::Conv_97_scale', 'onnx::Conv_98_quantized', 0.03752272, 0.030979699, 2),
        ('onnx::Conv_100_quantized', 'onnx::Conv_100_scale', 'onnx::Conv_101_quantized', 0.030979699, 0.06587609, 1),
    ]
    cur = x
    for wname, sname, bname, in_s, out_s, stride in layer_names:
        cur = conv_layer(cur, inits[wname], inits[sname], inits[bname], in_s, out_s, stride)

    gap_in_scale = 0.06587609
    gap_out_scale = float(inits['/GlobalAveragePool_output_0_scale'])
    Cf, Hf, Wf = cur.shape
    N = Hf * Wf
    gap_avg = (cur.astype(np.int64).sum(axis=(1, 2)) + N // 2) // N
    MULT_gap = round((gap_in_scale / gap_out_scale) * (2 ** 31))
    gap_req = np.clip((gap_avg * MULT_gap + (1 << 30)) >> 31, 0, 255).astype(np.int32)

    w_fc = inits['head.weight_quantized']
    w_scale_fc = inits['head.weight_scale']
    b_fc = inits['head.bias_quantized']
    acc_fc = (w_fc.astype(np.int64) @ gap_req.astype(np.int64)) + b_fc.astype(np.int64)
    logits_sim = acc_fc.astype(np.float64) * (gap_out_scale * w_scale_fc.astype(np.float64))

    print("onnxruntime logits:", ref)
    print("simulated  logits:", logits_sim)
    print("argmax sim:", int(np.argmax(logits_sim)), " argmax ref:", int(np.argmax(ref)))
    assert np.argmax(logits_sim) == np.argmax(ref), "argmax mismatch!"
    print("OK: integer fixed-point simulation matches onnxruntime's predicted class.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "model_int8.onnx")
