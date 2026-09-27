#!/usr/bin/env python3
"""Uploads a real test image's top-48-row strip to the real board (the
board's frame_player replays this strip cyclically to fill 480 rows, since
the JTAG link is too slow to stream a unique 640x480 frame every time --
documented in docs/architecture.md), runs one frame, and pulls back every
one of the 1200 tile results (logit0, logit1) via GRES. Also cross-checks
against ref/int_model.py. Saves a JSON with per-tile results plus the
resized 640x480 image array for diagram-building."""
import json
import os
import sys
import numpy as np

ROOT = "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn"
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "ref"))
from tcnn_link import TcnnLink, _load_image_strip, PITCH  # noqa: E402
from int_model import IntModel  # noqa: E402

OUT_DIR = sys.argv[1]
IMAGE = sys.argv[2]
os.makedirs(OUT_DIR, exist_ok=True)

W, H, SH = 640, 480, 48
strip = _load_image_strip(IMAGE, W, SH)

link = TcnnLink()
checksum = link.upload(strip)
result = link.run(W, H, SH, 1)
n_tiles_w, n_tiles_h = W // 16, H // 16
words = link.gres(n_tiles_h * PITCH)

model = IntModel(gen_dir=os.path.join(ROOT, "gen"))
replayed = strip[np.arange(H) % SH, :, :]

tiles = []
mismatches = 0
for band in range(n_tiles_h):
    for tcol in range(n_tiles_w):
        w16 = words[band * PITCH + tcol]
        got_l0, got_l1 = w16 & 0xFF, (w16 >> 8) & 0xFF
        tile_px = replayed[band*16:(band+1)*16, tcol*16:(tcol+1)*16, :]
        exp_l0, exp_l1 = model.run(tile_px)
        ok = bool((got_l0 == exp_l0) and (got_l1 == exp_l1))
        if not ok:
            mismatches += 1
        tiles.append(dict(band=band, tcol=tcol, logit0=got_l0, logit1=got_l1,
                           argmax=int(got_l1 > got_l0), match_ref=ok))

print(f"{IMAGE}: {len(tiles)} tiles, {mismatches} mismatches vs ref/int_model.py, "
      f"res_mismatch(cross-frame)={result['res_mismatch']}, checksum=0x{checksum:08x}")

np.save(os.path.join(OUT_DIR, "frame_640x480.npy"), replayed)
with open(os.path.join(OUT_DIR, "board_result.json"), "w") as f:
    json.dump(dict(image=IMAGE, w=W, h=H, sh=SH, n_tiles_w=n_tiles_w, n_tiles_h=n_tiles_h,
                    mismatches=mismatches, run_result=result, tiles=tiles), f, indent=1)
print("saved to", OUT_DIR)
