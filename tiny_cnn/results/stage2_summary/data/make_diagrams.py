#!/usr/bin/env python3
import json
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT = "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn/results/stage2_summary/diagrams"
SCRATCH = "/tmp/claude-1000/-home-tharaka-Documents-Low-Latency-Visual-Object-Tracking/c21c709b-686c-4998-b01f-1b12bb05bac0/scratchpad"
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "font.size": 10})

# ---------------------------------------------------------------- 1. resource
fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
labels = ["Gen 1\n(COUT_PAR=1)", "Gen 2\n(COUT_PAR=2)"]
data = {
    "Logic elements\n(of 114,480)": [100309, 57288],
    "Memory bits\n(of 3,981,312)": [1919232, 1973920],
    "Embedded 9x9\nmultipliers (of 532)": [42, 504],
}
colors = ["#c0392b", "#2471a3"]
for ax, (title, vals) in zip(axes, data.items()):
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    ax.set_title(title, fontsize=10)
    total = int(title.split("of ")[1].replace(",", "").rstrip(")"))
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v, f"{v:,}\n({100*v/total:.0f}%)",
                ha="center", va="bottom", fontsize=8.5)
    ax.set_ylim(0, total * 1.18)
    ax.spines[["top", "right"]].set_visible(False)
fig.suptitle("FPGA resource utilization: Gen 1 (40.18 fps) vs Gen 2 (79.51 fps)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.93])
fig.savefig(os.path.join(OUT, "01_resource_utilization.png"))
plt.close(fig)

# ---------------------------------------------------------------- 2. timing
fig, ax = plt.subplots(figsize=(7, 4))
corners = ["Slow 85C\n(worst case)", "Slow 0C", "Fast 0C"]
gen1_setup = [2.042, 3.846, 10.924]
gen2_setup = [4.621, 6.155, 12.493]
x = np.arange(len(corners))
w = 0.35
ax.bar(x - w/2, gen1_setup, w, label="Gen 1 (COUT_PAR=1)", color="#c0392b")
ax.bar(x + w/2, gen2_setup, w, label="Gen 2 (COUT_PAR=2)", color="#2471a3")
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xticks(x, corners)
ax.set_ylabel("Setup slack (ns), higher = more margin")
ax.set_title("Timing closure at 50 MHz across STA corners")
ax.legend()
for i, (a, b) in enumerate(zip(gen1_setup, gen2_setup)):
    ax.text(i - w/2, a + 0.15, f"+{a:.2f}", ha="center", fontsize=8)
    ax.text(i + w/2, b + 0.15, f"+{b:.2f}", ha="center", fontsize=8)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "02_timing_slack.png"))
plt.close(fig)

# ---------------------------------------------------------------- 3. fps: fpga generations + calc vs observed
fig, ax = plt.subplots(figsize=(7, 4.2))
names = ["Gen 1\ncalculated\n(1024 cyc)", "Gen 1\nobserved\n(board)",
         "Gen 2\ncalculated\n(512 cyc)", "Gen 2\nobserved\n(board)"]
vals = [50e6/1024/1200, 40.18, 50e6/512/1200, 79.51]
cs = ["#e8a598", "#c0392b", "#9ac6e8", "#2471a3"]
bars = ax.bar(names, vals, color=cs)
for b, v in zip(bars, vals):
    ax.text(b.get_x()+b.get_width()/2, v+0.8, f"{v:.2f}", ha="center", fontsize=9)
ax.set_ylabel("fps @ 640x480, 50 MHz")
ax.set_title("Calculated vs. observed (real board) frame rate")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "03_fpga_calc_vs_observed.png"))
plt.close(fig)

# ---------------------------------------------------------------- 4. fps: fpga vs cpu/gpu (batched throughput)
fig, ax = plt.subplots(figsize=(7.5, 4.2))
names = ["onnxruntime\nCPU", "OpenVINO\nCPU (i7-1185G7)", "OpenVINO\nIris Xe iGPU", "FPGA\n(Gen 2, this project)"]
vals = [14.7, 50.0, 250.0, 79.51]
cs = ["#7f8c8d", "#7f8c8d", "#27ae60", "#2471a3"]
bars = ax.barh(names, vals, color=cs)
for b, v in zip(bars, vals):
    ax.text(v + 4, b.get_y()+b.get_height()/2, f"{v:.1f} fps", va="center", fontsize=9)
ax.set_xlabel("fps, 640x480 frame batched as 1200 tiles/call")
ax.set_title("Batched-throughput comparison (best case for CPU/GPU)")
ax.set_xlim(0, 320)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "04_fps_batched_comparison.png"))
plt.close(fig)

# ---------------------------------------------------------------- 5. streaming latency comparison
fig, ax = plt.subplots(figsize=(7.5, 4.2))
names = ["OpenVINO\nIris Xe iGPU", "OpenVINO\nCPU", "onnxruntime\nCPU", "FPGA\n(Gen 2, this project)"]
fps_vals = [0.6, 3.85, 9.5, 79.51]
cs = ["#c0392b", "#7f8c8d", "#7f8c8d", "#2471a3"]
bars = ax.barh(names, fps_vals, color=cs)
ax.set_xscale("log")
for b, v in zip(bars, fps_vals):
    ax.text(v * 1.15, b.get_y()+b.get_height()/2, f"{v:.2f} fps", va="center", fontsize=9)
ax.set_xlabel("equivalent fps @ 1200 tiles/frame (log scale), one tile at a time")
ax.set_title("Single-tile streaming latency comparison (real camera-feed scenario)")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "05_fps_streaming_latency.png"))
plt.close(fig)

# ---------------------------------------------------------------- 6. pipeline schedule diagram
fig, ax = plt.subplots(figsize=(9, 3.6))
stage_names = ["L0 (3->16, s2)", "L1 (16->16, s1)", "L2 (16->32, s2)", "L3 (32->32, s1)", "GAP+FC head"]
stage_cycles = [520, 522, 521, 522, 110]
colors5 = ["#2471a3", "#2e86c1", "#5dade2", "#85c1e9", "#aeb6bf"]
tile_labels = ["tile N+3", "tile N+2", "tile N+1", "tile N", ""]
y0 = 0
for i, (name, cyc, c, tl) in enumerate(zip(stage_names, stage_cycles, colors5, tile_labels)):
    y = len(stage_names) - i - 1
    ax.barh(y, cyc, left=0, height=0.6, color=c, edgecolor="black", linewidth=0.6)
    ax.text(cyc/2, y, f"{name}\n{cyc} cycles" + (f"  [{tl}]" if tl else ""),
            ha="center", va="center", fontsize=8.5, color="white" if i < 4 else "black")
ax.set_xlim(0, 560)
ax.set_yticks([])
ax.set_xlabel("cycles within one steady-state tile period (524 cycles @ 50 MHz = 10.48 us)")
ax.set_title("Layer-pipelined schedule: 4 concurrent engines, one tile out every 524 cycles")
ax.spines[["top", "right", "left"]].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "06_pipeline_schedule.png"))
plt.close(fig)

print("6 charts written to", OUT)
