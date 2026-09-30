#!/usr/bin/env python3
"""Benchmark tinycnn_qat_int4.onnx on CPU and Intel Iris Xe iGPU (OpenVINO),
processing the same workload as the FPGA: 1200 non-overlapping 16x16x3 tiles
per 640x480 frame, replayed for many frames, reporting frames/sec."""
import time
import numpy as np
import onnx
from PIL import Image
import os

ROOT = "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn"
IMG = os.path.join(ROOT, "002675.jpg")  # same image used for the FPGA's strip

im = Image.open(IMG).convert("RGB").resize((640, 480))
arr = np.asarray(im, dtype=np.float32)  # HWC, 0..255
tiles = []
for ty in range(480 // 16):
    for tx in range(640 // 16):
        t = arr[ty*16:ty*16+16, tx*16:tx*16+16, :].transpose(2, 0, 1)  # CHW
        tiles.append(t)
batch = np.stack(tiles, axis=0)  # (1200, 3, 16, 16)
assert batch.shape == (1200, 3, 16, 16)
print(f"tiles/frame: {batch.shape[0]}")

N_FRAMES = 200
model_path = os.path.join(ROOT, "tinycnn_qat_int4.onnx")


def bench_onnxruntime_cpu():
    import onnxruntime as ort
    so = ort.SessionOptions()
    sess = ort.InferenceSession(model_path, sess_options=so, providers=["CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name
    # warmup
    for _ in range(5):
        sess.run(None, {inp_name: batch})
    t0 = time.perf_counter()
    for _ in range(N_FRAMES):
        sess.run(None, {inp_name: batch})
    dt = time.perf_counter() - t0
    return dt


def bench_openvino(device):
    from openvino import Core, compile_model
    core = Core()
    model = core.read_model(model_path)
    compiled = core.compile_model(model, device)
    infer = compiled.create_infer_request()
    inp = compiled.input(0)
    # warmup
    for _ in range(5):
        infer.infer({inp: batch})
    t0 = time.perf_counter()
    for _ in range(N_FRAMES):
        infer.infer({inp: batch})
    dt = time.perf_counter() - t0
    return dt


results = {}
try:
    dt = bench_onnxruntime_cpu()
    results["onnxruntime CPU"] = dt
except Exception as e:
    print("onnxruntime CPU failed:", e)

for dev in ["CPU", "GPU"]:
    try:
        dt = bench_openvino(dev)
        results[f"OpenVINO {dev}"] = dt
    except Exception as e:
        print(f"OpenVINO {dev} failed:", e)

print()
print(f"{'Backend':<20}{'total (s)':>12}{'fps':>12}{'tiles/s':>14}")
for name, dt in results.items():
    fps = N_FRAMES / dt
    tps = fps * 1200
    print(f"{name:<20}{dt:>12.3f}{fps:>12.2f}{tps:>14.0f}")
