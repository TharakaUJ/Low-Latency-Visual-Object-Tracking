#!/usr/bin/env python3
"""
niosv_link.py - protocol layer for the NiosV tracker firmware (main.c).

Spawns juart-terminal / nios2-terminal ONCE and keeps it open (only one JTAG
client may hold the connection, so close Eclipse / other terminals first).
A background thread drains the pipe so every read can have a real timeout.

Also usable as a tiny CLI:
    python niosv_link.py grab out.png [--gray]
    python niosv_link.py boundary
    python niosv_link.py freeze | unfreeze
"""
import argparse
import queue
import shutil
import struct
import subprocess
import threading
import time

import numpy as np

W, H, WIN = 640, 576, 16
HALF = H // 2
MAGICS = (b"FRAM", b"TACK", b"TMPL", b"BNDS", b"FRZN")


# ----------------------------------------------------------------------------
# Image helpers
# ----------------------------------------------------------------------------
def weave(top_half_first: np.ndarray) -> np.ndarray:
    """(576, ...) buffer layout [field0 | field1] -> woven (576, ...) image."""
    out = np.empty_like(top_half_first)
    out[0::2], out[1::2] = top_half_first[:HALF], top_half_first[HALF:]
    return out


def raw_to_rgb(grid: np.ndarray) -> np.ndarray:
    """grid: (576,640) uint16, high byte = Y, low byte = alternating Cr/Cb."""
    Y = (grid >> 8).astype(np.float32)
    C = (grid & 0xFF).astype(np.float32)
    cr = np.repeat(C[:, 0::2], 2, axis=1) - 128
    cb = np.repeat(C[:, 1::2], 2, axis=1) - 128     # swap if colours look off
    rgb = np.stack([Y + 1.402 * cr,
                    Y - 0.344 * cb - 0.714 * cr,
                    Y + 1.772 * cb], -1)
    return weave(np.clip(rgb, 0, 255).astype(np.uint8))


def click_to_template(y_plane: np.ndarray, x: int, y: int):
    """
    y_plane : (576,640) uint8 luma in BUFFER layout (fields not woven).
    x, y    : click position in the WOVEN image.

    The hardware window is 16 consecutive lines of ONE field, so the template
    must be cut from a single field of the buffer, not from the woven picture
    (16 field lines = 32 woven rows).
    Returns (template 16x16 uint8, (col0, row0) top-left in field coords).
    """
    f, fy = y & 1, y >> 1
    r0 = int(np.clip(fy - WIN // 2, 0, HALF - WIN))
    c0 = int(np.clip(x - WIN // 2, 0, W - WIN))
    base = f * HALF
    return y_plane[base + r0: base + r0 + WIN, c0: c0 + WIN].copy(), (c0, r0)


# ----------------------------------------------------------------------------
class NiosLink:
    def __init__(self, tool=None, instance=None):
        tool = tool or next((t for t in ("juart-terminal", "nios2-terminal")
                             if shutil.which(t)), None)
        if not tool:
            raise SystemExit("juart-terminal / nios2-terminal not on PATH")
        cmd = [tool] + (["--instance", str(instance)] if instance is not None else [])
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0)
        self.q = queue.Queue()
        self.buf = bytearray()
        self.lock = threading.RLock()      # one transaction on the wire at a time
        threading.Thread(target=self._pump, daemon=True).start()

    # -- low level -----------------------------------------------------------
    def _pump(self):
        while True:
            chunk = self.proc.stdout.read(4096)
            if not chunk:
                self.q.put(None)
                return
            self.q.put(chunk)

    def _fill(self, deadline):
        try:
            chunk = self.q.get(timeout=max(0.0, deadline - time.time()))
        except queue.Empty:
            raise TimeoutError("no data from target")
        if chunk is None:
            raise EOFError("JTAG UART terminal closed")
        self.buf += chunk

    def _read(self, n, timeout=5.0, progress=None):
        deadline = time.time() + timeout
        while len(self.buf) < n:
            self._fill(deadline)
            deadline = time.time() + timeout      # inactivity timeout
            if progress:
                progress(min(len(self.buf), n), n)
        data, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return data

    def _sync(self, want, timeout=5.0):
        """Discard bytes (boot banner, junk) until one of `want` magics."""
        deadline = time.time() + timeout
        while True:
            for m in want:
                i = self.buf.find(m)
                if i >= 0:
                    del self.buf[:i + 4]
                    return m
            self.buf = self.buf[-3:]              # keep possible partial magic
            self._fill(deadline)

    def _send(self, data: bytes):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def _flush_input(self):
        time.sleep(0.05)
        while True:
            try:
                c = self.q.get_nowait()
            except queue.Empty:
                break
            if c: pass
        self.buf.clear()

    # -- commands ------------------------------------------------------------
    def boundary(self):
        with self.lock:
            self._send(b"B")
            self._sync([b"BNDS"])
            return struct.unpack("<HH", self._read(4))

    def freeze(self, on: bool):
        with self.lock:
            self._send(b"F" if on else b"U")
            self._sync([b"FRZN"], timeout=10)
            return self._read(1)[0]          # bit0 = requested, bit1 = frozen

    def load_template(self, tmpl: np.ndarray):
        """tmpl: (16,16) uint8. Returns number of readback mismatches."""
        assert tmpl.shape == (WIN, WIN)
        with self.lock:
            self._send(b"T" + tmpl.astype(np.uint8).tobytes())
            self._sync([b"TACK"], timeout=10)
            return self._read(1)[0]

    def read_template(self):
        with self.lock:
            self._send(b"R")
            self._sync([b"TMPL"], timeout=10)
            return np.frombuffer(self._read(WIN * WIN), np.uint8).reshape(WIN, WIN)

    def grab(self, luma_only=False, progress=None):
        """Returns (y_plane (576,640) uint8 in buffer layout, raw uint16 grid or None)."""
        with self.lock:
            self._send(b"Y" if luma_only else b"S")
            self._sync([b"FRAM"], timeout=30)
            w, h, fmt, n = struct.unpack("<HHBI", self._read(9))
            assert (w, h) == (W, H), f"unexpected geometry {w}x{h}"
            payload = self._read(n, timeout=15, progress=progress)
            (csum,) = struct.unpack("<I", self._read(4))
            ok = (int(np.frombuffer(payload, np.uint8).sum(dtype=np.uint64)) & 0xFFFFFFFF) == csum
            if fmt == 0x02:
                grid = np.frombuffer(payload, "<u2").reshape(H, W)
                return (grid >> 8).astype(np.uint8), grid, ok
            if fmt == 0x03:
                return np.frombuffer(payload, np.uint8).reshape(H, W).copy(), None, ok
            raise ValueError(f"unknown format 0x{fmt:02X}")

    def close(self):
        self.proc.terminate()


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["grab", "boundary", "freeze", "unfreeze"])
    ap.add_argument("out", nargs="?", default="frame.png")
    ap.add_argument("--gray", action="store_true")
    ap.add_argument("--tool")
    ap.add_argument("--instance", type=int)
    a = ap.parse_args()
    link = NiosLink(a.tool, a.instance)
    try:
        if a.cmd == "grab":
            yp, grid, ok = link.grab(a.gray, lambda d, t: print(f"\r{d}/{t}", end=""))
            print("\nchecksum", "OK" if ok else "MISMATCH")
            img = weave(yp) if grid is None else raw_to_rgb(grid)
            Image.fromarray(img).save(a.out)
        elif a.cmd == "boundary":
            print("boundary x,y =", link.boundary())
        else:
            print("ctrl status =", link.freeze(a.cmd == "freeze"))
    finally:
        link.close()
