#!/usr/bin/env python3
"""Builds a diagram for one board run: the actual 640x480 frame the FPGA
processed (left) next to the same frame with each 16x16 tile's real-silicon
class-1-vs-class-0 argmax overlaid as a colored grid (right)."""
import json
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRATCH = "/tmp/claude-1000/-home-tharaka-Documents-Low-Latency-Visual-Object-Tracking/c21c709b-686c-4998-b01f-1b12bb05bac0/scratchpad"
OUT = "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn/results/stage2_summary/diagrams"

name = sys.argv[1]     # e.g. board_002675
label = sys.argv[2]    # e.g. 002675.jpg
out_name = sys.argv[3]

frame = np.load(f"{SCRATCH}/{name}/frame_640x480.npy")
info = json.load(open(f"{SCRATCH}/{name}/board_result.json"))
nw, nh = info["n_tiles_w"], info["n_tiles_h"]

grid = np.zeros((nh, nw), dtype=int)
logit_gap = np.zeros((nh, nw), dtype=int)
for t in info["tiles"]:
    grid[t["band"], t["tcol"]] = t["argmax"]
    logit_gap[t["band"], t["tcol"]] = t["logit1"] - t["logit0"]

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

axes[0].imshow(frame)
axes[0].set_title(f"Input frame ({label}, resized 640x480)\nas replayed to the FPGA")
axes[0].axis("off")

axes[1].imshow(frame)
overlay = np.zeros((*grid.shape, 4))
overlay[grid == 1] = [1, 0.2, 0.2, 0.35]
overlay[grid == 0] = [0.2, 0.4, 1, 0.12]
axes[1].imshow(overlay, extent=(0, 640, 480, 0), interpolation="nearest")
for x in range(0, 641, 16):
    axes[1].axvline(x, color="white", linewidth=0.15, alpha=0.4)
for y in range(0, 481, 16):
    axes[1].axhline(y, color="white", linewidth=0.15, alpha=0.4)
axes[1].set_title("Per-tile argmax(logit1, logit0), real silicon\n(red = class 1, blue = class 0 -- label mapping undefined)")
axes[1].axis("off")

im = axes[2].imshow(logit_gap, cmap="RdBu_r", vmin=-128, vmax=128, extent=(0, 640, 480, 0))
axes[2].set_title("logit1 - logit0 per tile (real silicon)\n(decision margin / confidence proxy)")
axes[2].axis("off")
fig.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04)

n_mismatch = info["mismatches"]
source = info.get("source_label", "FPGA (real DE2-115 hardware)")
fig.suptitle(f"{source} inference on {label} -- "
             f"{nw*nh} tiles, {n_mismatch} mismatches vs ref/int_model.py", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.92])
fig.savefig(f"{OUT}/{out_name}.png")
print("wrote", f"{OUT}/{out_name}.png")
