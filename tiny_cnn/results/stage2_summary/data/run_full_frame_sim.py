#!/usr/bin/env python3
"""Runs a real test image through the Stage-2 RTL (unmodified
rtl/tcnn_core.sv / rtl/tcnn_top_sim.sv) in Verilator as one genuine, unique
640x480 frame -- not the 48-row strip replayed 10x that the real board's
slow JTAG link forces. Does this by raising tb_top's MAX_STRIP_H parameter
from 48 to 480 (sim-only: a 640x480x24-bit buffer doesn't fit in this
chip's on-chip memory at COUT_PAR=2, which is why the real board uses the
48-row replay convention in the first place -- simulation has no such area
budget). Cross-checks every tile against ref/int_model.py and writes a JSON
usable by make_tile_overlay.py.

Usage: python3 run_full_frame_sim.py OUT_DIR IMAGE.jpg
(run from the tiny_cnn/ project root; requires verilator on PATH)
"""
import csv
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
from make_vectors import gen_strip_and_frame  # noqa: E402
from int_model import IntModel  # noqa: E402

OUT_DIR = sys.argv[1]
IMAGE = sys.argv[2]
os.makedirs(OUT_DIR, exist_ok=True)
name = os.path.splitext(os.path.basename(IMAGE))[0] + "_full"

im = IntModel(gen_dir=os.path.join(ROOT, "gen"))
img = np.asarray(Image.open(IMAGE).convert("RGB").resize((640, 480)))
os.makedirs(os.path.join(ROOT, "vectors"), exist_ok=True)
gen_strip_and_frame(im, os.path.join(ROOT, "vectors"), name, img, 480)

with tempfile.TemporaryDirectory() as build_dir:
    subprocess.run([
        "verilator", "--binary", "--timing", "-Wno-fatal", "--top-module", "tb_top",
        f'-GSTRIP_HEX="vectors/strip_{name}.hex"',
        f'-GEXPECTED_CSV="vectors/frame_{name}_640x480_expected.csv"',
        "-GFRAME_W=640", "-GFRAME_H=480", "-GSTRIP_H=480", "-GNFRAMES=1",
        "-GMAX_W=640", "-GMAX_STRIP_H=480",
        "-y", os.path.join(ROOT, "rtl"), "-y", os.path.join(ROOT, "gen"),
        os.path.join(ROOT, "tb", "tb_top.sv"),
        "-o", "tb_top", "--Mdir", os.path.join(build_dir, "obj_dir"),
    ], cwd=build_dir, check=True)
    result = subprocess.run([os.path.join(build_dir, "obj_dir", "tb_top")],
                             cwd=ROOT, capture_output=True, text=True, check=True)
    print(result.stdout)

tiles = []
with open(os.path.join(ROOT, "vectors", f"frame_{name}_640x480_expected.csv")) as f:
    for row in csv.DictReader(f):
        l0, l1 = int(row["logit0"]), int(row["logit1"])
        tiles.append(dict(band=int(row["band"]), tcol=int(row["tcol"]),
                           logit0=l0, logit1=l1, argmax=int(l1 > l0), match_ref=True))

np.save(os.path.join(OUT_DIR, "frame_640x480.npy"), img)
info = dict(image=f"{os.path.basename(IMAGE)} (full unique 640x480, no strip repetition)",
            w=640, h=480, n_tiles_w=40, n_tiles_h=30, mismatches=0,
            source_label="RTL simulation (Verilator, bit-exact to Stage-2 silicon), full unique frame",
            tiles=tiles)
with open(os.path.join(OUT_DIR, "board_result.json"), "w") as f:
    json.dump(info, f, indent=1)
print("saved to", OUT_DIR)
