#!/usr/bin/env python3
"""
frame_grab.py - Host-PC driver for the NiosV frame-grab firmware.

Talks to the board over its JTAG UART by spawning Altera/Intel's
`nios2-terminal` (older Quartus) or `juart-terminal` (current Quartus)
as a subprocess and using its stdin/stdout pipes as a raw byte pipe -
this avoids needing to write against the low-level JTAG Atlantic C API
directly.

Requirements:
    pip install pillow numpy
    Quartus's bin (or bin64) directory must be on PATH, so that
    `nios2-terminal` / `juart-terminal` can be found. Alternatively pass
    --tool with a full path.

Usage:
    python frame_grab.py                       # auto-detect terminal tool
    python frame_grab.py --tool juart-terminal
    python frame_grab.py --instance 0 --out frame.png
"""

import argparse
import shutil
import subprocess
import struct
import sys
import time

import numpy as np
from PIL import Image

MAGIC = b"FRAM"
HEADER_LEN_AFTER_MAGIC = 9   # width(2) + height(2) + format(1) + payload_len(4)


def find_terminal_tool(explicit):
    if explicit:
        return explicit
    for candidate in ("juart-terminal", "nios2-terminal"):
        path = shutil.which(candidate)
        if path:
            return candidate
    raise SystemExit(
        "Could not find 'juart-terminal' or 'nios2-terminal' on PATH.\n"
        "Pass --tool <name-or-full-path>, or add Quartus's bin directory to PATH."
    )

def decode_raw(grid):                       # grid: (576, 640) uint16
    Y = (grid >> 8).astype(np.float32)
    C = (grid & 0xFF).astype(np.float32)
    cr = np.repeat(C[:, 0::2], 2, axis=1) - 128   # even cols -> Cr
    cb = np.repeat(C[:, 1::2], 2, axis=1) - 128   # odd  cols -> Cb  (swap if colours look off)
    rgb = np.stack([Y + 1.402*cr,
                    Y - 0.344*cb - 0.714*cr,
                    Y + 1.772*cb], -1)
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    half = grid.shape[0] // 2
    out = np.empty_like(rgb)
    out[0::2], out[1::2] = rgb[:half], rgb[half:]  # weave the two fields
    return out

def open_jtag_pipe(tool, instance):
    cmd = [tool]
    if instance is not None:
        cmd += ["--instance", str(instance)]
    # Both tools default to relaying raw bytes between the JTAG UART and
    # their own stdin/stdout when not run in a real interactive TTY.
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    return proc


def read_exact(stream, n):
    buf = bytearray()
    last_print = time.time()
    while len(buf) < n:
        chunk = stream.read(min(n - len(buf), 4096)) # Read in chunks
        if not chunk:
            raise EOFError("JTAG UART pipe closed unexpectedly")
        buf += chunk
        
        # Print progress every 0.5 seconds so you know it's alive
        if time.time() - last_print > 0.5:
            print(f"  Downloading: {len(buf)} / {n} bytes ({len(buf)/n*100:.1f}%)", end="\r")
            last_print = time.time()
            
    print(f"  Downloading: {n} / {n} bytes (100.0%)") # Clear line when done
    return bytes(buf)



def find_magic(stream, timeout_s=15.0):
    """Scan incoming bytes (discarding any startup-banner noise) until the
    4-byte magic 'FRAM' is seen, byte by byte."""
    window = bytearray()
    start = time.time()
    while True:
        if time.time() - start > timeout_s:
            raise TimeoutError("Timed out waiting for frame header ('FRAM' magic)")
        b = stream.read(1)
        if not b:
            continue
        window += b
        if len(window) > 4:
            window = window[-4:]
        if bytes(window) == MAGIC:
            return


def ycbcr422_to_rgb(payload: bytes, width: int, height: int) -> np.ndarray:
    """payload is packed Y0 Cb Y1 Cr Y2 Cb' Y3 Cr' ... (2 pixels per 4 bytes)."""
    arr = np.frombuffer(payload, dtype=np.uint8)
    arr = arr.reshape(-1, 4).astype(np.int16)  # [N/2, 4] = Y0,Cb,Y1,Cr

    y0 = arr[:, 0]
    cb = arr[:, 1] - 128
    y1 = arr[:, 2]
    cr = arr[:, 3] - 128

    def to_rgb(y, cb, cr):
        r = y + 1.402 * cr
        g = y - 0.344136 * cb - 0.714136 * cr
        b = y + 1.772 * cb
        rgb = np.stack([r, g, b], axis=-1)
        return np.clip(rgb, 0, 255).astype(np.uint8)

    rgb0 = to_rgb(y0, cb, cr)
    rgb1 = to_rgb(y1, cb, cr)

    # interleave pixel0, pixel1, pixel0, pixel1, ... back into full-width rows
    out = np.empty((rgb0.shape[0] * 2, 3), dtype=np.uint8)
    out[0::2] = rgb0
    out[1::2] = rgb1

    return out.reshape(height, width, 3)


def raw_samples_to_grayscale(payload: bytes, width: int, height: int) -> np.ndarray:
    """format 0x02: payload is width*height raw 16-bit YCbCr422 samples,
    LE, one sample per SDRAM word (only the low 16 bits were meaningful on
    the FPGA side). Still interlaced, still includes blanking - this is a
    first-look decode only: high byte of each 16-bit sample as grayscale,
    reshaped straight into the raw (height, width) grid with no
    deinterlacing/blanking-crop/chroma handling yet."""
    arr = np.frombuffer(payload, dtype="<u2")  # little-endian uint16
    expected = width * height
    if arr.size != expected:
        raise ValueError(
            f"Payload has {arr.size} samples, expected {expected} "
            f"({width}x{height}) - geometry mismatch?"
        )
    grid = arr.reshape(height, width)
    # crude grayscale preview: low byte of each raw sample
    gray = (grid & 0xFF).astype(np.uint8)
    return grid, gray


def grab_frame(tool, instance, out_path):
    proc = open_jtag_pipe(tool, instance)
    try:
        stdin, stdout = proc.stdin, proc.stdout

        print("Requesting frame ('S')...")
        stdin.write(b"S")
        stdin.flush()

        find_magic(stdout)
        rest = read_exact(stdout, HEADER_LEN_AFTER_MAGIC)
        width, height, fmt, payload_len = struct.unpack("<HHBI", rest)

        if fmt not in (0x01, 0x02):
            raise ValueError(f"Unsupported pixel format code 0x{fmt:02X}")

        print(f"Header OK: {width}x{height}, format=0x{fmt:02X}, payload={payload_len} bytes")

        payload = read_exact(stdout, payload_len)
        csum_bytes = read_exact(stdout, 4)
        (csum_recv,) = struct.unpack("<I", csum_bytes)

        csum_calc = int(np.frombuffer(payload, dtype=np.uint8).astype(np.uint32).sum() % (2**32))
        if csum_calc != csum_recv:
            print(f"WARNING: checksum mismatch! got 0x{csum_recv:08X}, "
                  f"expected 0x{csum_calc:08X} - frame may be corrupted.")
        else:
            print("Checksum OK.")

        if fmt == 0x01:
            rgb = ycbcr422_to_rgb(payload, width, height)
            img = Image.fromarray(rgb, mode="RGB")
            img.save(out_path)
            print(f"Saved frame to {out_path}")
            img.show()
        else:  # fmt == 0x02: raw, still-interlaced, still-blanked samples
            grid, gray = raw_samples_to_grayscale(payload, width, height)
            npy_path = out_path.rsplit(".", 1)[0] + "_raw.npy"
            np.save(npy_path, grid)
            print(f"Saved raw {width}x{height} uint16 sample grid to {npy_path}")
            img = Image.fromarray(decode_raw(grid))
            img.save(out_path)
            print(f"Saved grayscale preview to {out_path} "
                  f"(raw/interlaced/blanked - not a clean decoded picture yet)")
            img.show()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tool", default=None,
                     help="terminal executable name or path (default: auto-detect)")
    ap.add_argument("--instance", type=int, default=None,
                     help="JTAG UART instance index, if you have more than one")
    ap.add_argument("--out", default="frame.png", help="output image path")
    args = ap.parse_args()

    tool = find_terminal_tool(args.tool)
    grab_frame(tool, args.instance, args.out)


if __name__ == "__main__":
    main()
