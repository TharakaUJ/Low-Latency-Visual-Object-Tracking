#!/usr/bin/env python3
"""
make_vectors.py — generate test vectors for the Verilator testbenches (P1)
and the board bring-up (P4), from int_model.py (the bit-exact reference the
RTL must match). See docs/implementation_plan.md Phase 0/1/4.

Usage: python3 ref/make_vectors.py [--gen-dir gen] [--out vectors] [--n-tiles 1000]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from int_model import IntModel  # noqa: E402


def write_hex_bytes(path, arr_u8_flat):
    with open(path, "w") as f:
        for v in arr_u8_flat:
            f.write(f"{int(v):02x}\n")


def pixel_word(r, g, b):
    """24-bit input pixel word: [7:0]=R, [15:8]=G, [23:16]=B (see
    docs/implementation_plan.md's Data formats)."""
    return (int(b) << 16) | (int(g) << 8) | int(r)


def fmap_word(px_channels):
    """Feature-map word: channel c at bits [8c+7:8c]."""
    w = 0
    for c, v in enumerate(px_channels):
        w |= int(v) << (8 * c)
    return w


def gen_tiles(im, out_dir, n_tiles, images):
    rng = np.random.default_rng(42)
    n_rand = n_tiles // 2
    n_crop = n_tiles - n_rand
    tiles = [rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8) for _ in range(n_rand)]
    for i in range(n_crop):
        img = np.asarray(Image.open(images[i % len(images)]).convert("RGB"))
        h, w, _ = img.shape
        r = rng.integers(0, h - 16 + 1)
        c = rng.integers(0, w - 16 + 1)
        tiles.append(img[r:r + 16, c:c + 16, :].copy())

    # tiles.hex: 24-bit pixel words, raster order, 256 per tile
    with open(os.path.join(out_dir, "tiles.hex"), "w") as f:
        for t in tiles:
            for row in range(16):
                for col in range(16):
                    r, g, b = t[row, col, :]
                    f.write(f"{pixel_word(r, g, b):06x}\n")

    expected = []
    for t in tiles:
        logits = im.run(t)
        expected.append(logits)

    with open(os.path.join(out_dir, "tiles_expected.hex"), "w") as f:
        for logit0, logit1 in expected:
            # space-separated (not underscore-joined): SystemVerilog's
            # $fscanf "%h" treats '_' as a legal digit separator within a hex
            # literal, so "0026_00d2" would be swallowed as ONE number --
            # same lesson as fpga_cnn_pipeline/ref/make_vectors.py.
            f.write(f"{int(logit0):02x} {int(logit1):02x}\n")

    # per-layer dump of tile 0, for tb_conv_layer/tb_core debugging
    logits0, dumps0, view0 = im.run(tiles[0], dump=True)
    for k, d in enumerate(dumps0):
        with open(os.path.join(out_dir, f"tile0_layer{k}.hex"), "w") as f:
            oh, ow, cout = d.shape
            for row in range(oh):
                for col in range(ow):
                    f.write(f"{fmap_word(d[row, col, :]):0{(cout*8+3)//4}x}\n")
    write_hex_bytes(os.path.join(out_dir, "tile0_view.hex"), view0)

    print(f"tiles.hex: {len(tiles)} tiles ({n_rand} random + {n_crop} crops)")
    return tiles, expected


def windows_at_stride16(h, w):
    """Non-overlapping 16x16 tiles, raster order (band, tcol)."""
    positions = []
    r = 0
    while r + 16 <= h:
        c = 0
        while c + 16 <= w:
            positions.append((r, c))
            c += 16
        r += 16
    return positions


def gen_strip_and_frame(im, out_dir, name, img_rgb, strip_h):
    """img_rgb: [H,W,3] uint8, H>=strip_h. Writes:
      - strip_{name}.hex: strip_h x W, 24-bit pixel words, raster order
      - frame_{name}_expected.csv: band,tcol,logit0,logit1 for the frame
        replayed as (row % strip_h), tiled to img_rgb's full H,W."""
    h, w, _ = img_rgb.shape
    strip = img_rgb[:strip_h, :, :]
    with open(os.path.join(out_dir, f"strip_{name}.hex"), "w") as f:
        for row in range(strip_h):
            for col in range(w):
                r, g, b = strip[row, col, :]
                f.write(f"{pixel_word(r, g, b):06x}\n")

    # build the replayed frame: row r of the frame == strip row (r % strip_h)
    replayed = strip[np.arange(h) % strip_h, :, :]
    positions = windows_at_stride16(h, w)
    csv_path = os.path.join(out_dir, f"frame_{name}_{w}x{h}_expected.csv")
    with open(csv_path, "w") as f:
        f.write("band,tcol,logit0,logit1\n")
        for (r, c) in positions:
            band, tcol = r // 16, c // 16
            block = replayed[r:r + 16, c:c + 16, :]
            logits = im.run(block)
            f.write(f"{band},{tcol},{int(logits[0])},{int(logits[1])}\n")
    print(f"{csv_path}: {len(positions)} tiles (strip_h={strip_h}, replayed to {w}x{h})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-dir", default="gen")
    ap.add_argument("--out", default="vectors")
    ap.add_argument("--n-tiles", type=int, default=1000)
    ap.add_argument("--images", nargs="*",
                     default=["002675.jpg", "002683.jpg"])
    ap.add_argument("--strip-h", type=int, default=48)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    im = IntModel(gen_dir=args.gen_dir)

    gen_tiles(im, args.out, args.n_tiles, args.images)

    # requant vectors: 10k random (acc, mult, shift, zp) -> out, plus corners
    from int_model import requant
    rng = np.random.default_rng(7)
    n_req = 10000
    accs = rng.integers(-(1 << 20), 1 << 20, size=n_req, dtype=np.int64)
    mults = rng.integers(1 << 30, 1 << 31, size=n_req, dtype=np.int64)
    shifts = rng.integers(28, 40, size=n_req)
    zps = rng.integers(0, 128, size=n_req)
    # corner cases: exact .5 ties, extremes
    extra_accs = np.array([0, -1, 1, (1 << 20) - 1, -((1 << 20) - 1)], dtype=np.int64)
    extra_mults = np.full(5, 1 << 30, dtype=np.int64)
    extra_shifts = np.array([30, 33, 33, 35, 35])
    extra_zps = np.array([0, 0, 123, 123, 0])
    accs = np.concatenate([accs, extra_accs])
    mults = np.concatenate([mults, extra_mults])
    shifts = np.concatenate([shifts, extra_shifts])
    zps = np.concatenate([zps, extra_zps])

    with open(os.path.join(args.out, "requant_vectors.txt"), "w") as f:
        for a, m, s, z in zip(accs, mults, shifts, zps):
            out = requant(np.array([a]), int(m), int(s), int(z))[0]
            f.write(f"{a & 0xFFFFFFFF:08x} {m & 0xFFFFFFFF:08x} {s:02x} {z:02x} {out:02x}\n")
    print(f"requant_vectors.txt: {len(accs)} vectors")

    # strip + full-frame expected vectors (real image, resized to 640x480)
    img = np.asarray(Image.open(args.images[0]).convert("RGB").resize((640, 480)))
    name = os.path.splitext(os.path.basename(args.images[0]))[0]
    gen_strip_and_frame(im, args.out, name, img, args.strip_h)

    # small synthetic frame for quick sim (64x48, exactly matches strip_h)
    rng2 = np.random.default_rng(11)
    small = rng2.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
    gen_strip_and_frame(im, args.out, "rand64x48", small, 48)

    print(f"vectors written to {args.out}/")


if __name__ == "__main__":
    main()
