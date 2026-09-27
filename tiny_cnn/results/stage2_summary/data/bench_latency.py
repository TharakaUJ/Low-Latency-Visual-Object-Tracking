#!/usr/bin/env python3
"""Single-tile (batch=1) latency: models the real streaming case where one
16x16 tile becomes available at a time (as pixels stream off a camera),
rather than a whole frame buffered up-front for a big batched matmul."""
import time
import numpy as np
import os

ROOT = "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn"
model_path = os.path.join(ROOT, "tinycnn_qat_int4.onnx")
tile = np.random.rand(1, 3, 16, 16).astype(np.float32) * 255

N = 2000


def lat_onnxruntime_cpu():
    import onnxruntime as ort
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    for _ in range(20):
        sess.run(None, {name: tile})
    t0 = time.perf_counter()
    for _ in range(N):
        sess.run(None, {name: tile})
    return (time.perf_counter() - t0) / N


def lat_openvino(device):
    from openvino import Core
    core = Core()
    model = core.read_model(model_path)
    compiled = core.compile_model(model, device)
    infer = compiled.create_infer_request()
    inp = compiled.input(0)
    for _ in range(20):
        infer.infer({inp: tile})
    t0 = time.perf_counter()
    for _ in range(N):
        infer.infer({inp: tile})
    return (time.perf_counter() - t0) / N


results = {}
for name, fn in [("onnxruntime CPU", lat_onnxruntime_cpu),
                  ("OpenVINO CPU", lambda: lat_openvino("CPU")),
                  ("OpenVINO GPU", lambda: lat_openvino("GPU"))]:
    try:
        results[name] = fn()
    except Exception as e:
        print(f"{name} failed: {e}")

print()
print(f"{'Backend':<20}{'latency/tile (us)':>20}{'max tiles/s (1/lat)':>22}")
for name, lat in results.items():
    print(f"{name:<20}{lat*1e6:>20.1f}{1/lat:>22.0f}")
