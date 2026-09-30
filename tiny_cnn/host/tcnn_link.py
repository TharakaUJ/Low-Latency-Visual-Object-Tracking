#!/usr/bin/env python3
"""
tcnn_link.py -- host-side protocol layer + CLI for the standalone tiny-cnn
test system (quartus/tcnn_test/), talking to firmware/src/main.c over the
JTAG UART. See rtl/tcnn_avalon_slave.sv for the register map the firmware
fronts, and docs/progress_log.md's Gate S1 entry for the exact semantics.

Reuses the same `juart-terminal`-subprocess-plus-background-pump pattern as
fpga_cnn_pipeline/host/cnn_link.py's CnnLink (a single persistent JTAG UART
client, a background thread draining stdout into a queue so every read can
have a real timeout, and a lock serializing one transaction at a time on the
wire) -- including its `--no-quit-on-ctrl-d` workaround for juart-terminal's
default behavior of exiting the moment it sees a raw 0x04 byte from the
target, which would otherwise silently kill the connection mid-transaction
on this binary protocol.

CLI:
    tcnn_link.py ping | id | echo --bytes 65536
    tcnn_link.py upload IMG --w 640 --sh 48
    tcnn_link.py bench --w 640 --h 480 --sh 48 --frames 200 [--image IMG]
    tcnn_link.py check --w 640 --h 480 --sh 48 [--image IMG]
    tcnn_link.py tiles [--n 1000]
    tcnn_link.py abort

Every command that produces a result writes a log to `--out` (when given)
and exits non-zero on any mismatch.
"""
import argparse
import os
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ref"))
from int_model import IntModel  # noqa: E402

MAGICS = (b"PONG", b"TCID", b"SCRA", b"ECHO", b"UACK", b"RDON", b"GRES", b"XACK")

MAX_W = 640
PITCH = MAX_W // 16


class TcnnLink:
    def __init__(self, tool=None, instance=None):
        if isinstance(tool, (list, tuple)):
            cmd = list(tool)
        else:
            tool = tool or next((t for t in ("juart-terminal", "nios2-terminal")
                                 if shutil.which(t)), None)
            if not tool:
                raise SystemExit("juart-terminal / nios2-terminal not on PATH")
            cmd = [tool, "--no-quit-on-ctrl-d"] + (["--instance", str(instance)] if instance is not None else [])
        self.rx_total = 0
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0)
        self.q = queue.Queue()
        self.buf = bytearray()
        self.lock = threading.RLock()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            chunk = self.proc.stdout.read(4096)
            if not chunk:
                self.q.put(None)
                return
            self.q.put(chunk)

    def _fill(self, deadline, stage="read"):
        try:
            chunk = self.q.get(timeout=max(0.0, deadline - time.time()))
        except queue.Empty:
            raise TimeoutError(f"{stage}: no data for {deadline - time.time():.0f}s")
        if chunk is None:
            raise EOFError("JTAG UART terminal closed (juart-terminal exited)")
        self.rx_total += len(chunk)
        self.buf += chunk

    def _read(self, n, timeout=5.0, stage="read"):
        deadline = time.time() + timeout
        while len(self.buf) < n:
            self._fill(deadline, stage)
            deadline = time.time() + timeout
        data, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return data

    def _sync(self, want, timeout=5.0, stage="sync"):
        deadline = time.time() + timeout
        while True:
            for m in want:
                i = self.buf.find(m)
                if i >= 0:
                    del self.buf[:i + 4]
                    return m
            self.buf = self.buf[-3:]
            before = self.rx_total
            self._fill(deadline, stage)
            if self.rx_total != before:
                deadline = time.time() + timeout

    def _send(self, data: bytes):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def close(self):
        self.proc.terminate()

    @staticmethod
    def _u16(v): return struct.pack("<H", v)

    @staticmethod
    def _u32(v): return struct.pack("<I", v)

    # -- commands -------------------------------------------------------------
    def ping(self):
        with self.lock:
            self._send(b"P")
            self._sync([b"PONG"], stage="ping")
            return True

    def id(self):
        with self.lock:
            self._send(b"I")
            self._sync([b"TCID"], stage="id")
            tcid, version, status = struct.unpack("<III", self._read(12))
            return tcid, version, status

    def scratch(self, value: int):
        with self.lock:
            self._send(b"W" + self._u32(value))
            self._sync([b"SCRA"], stage="scratch")
            (rb,) = struct.unpack("<I", self._read(4))
            return rb

    MAX_ECHO_CHUNK = 0xFFFF

    def echo(self, data: bytes):
        with self.lock:
            out = bytearray()
            for i in range(0, len(data), self.MAX_ECHO_CHUNK):
                chunk = data[i:i + self.MAX_ECHO_CHUNK]
                self._send(b"E" + self._u16(len(chunk)) + chunk)
                self._sync([b"ECHO"], timeout=10, stage="echo")
                out += self._read(len(chunk), timeout=10, stage="echo payload")
            return bytes(out)

    def upload(self, strip_rgb: np.ndarray, timeout=300.0):
        """strip_rgb: (SH, W, 3) uint8, tightly packed. Returns checksum.

        Sends one row (w*3 bytes) per write, matching firmware's per-row
        recv_all(row_buf, w*3) boundary in cmd_upload() -- a single huge
        write() of the whole strip (up to 92160 B for 640x48) blocked the
        underlying juart-terminal pipe long enough that the firmware's
        recv_all() for a later row never got fed before the host's timeout
        elapsed, and worse, once that happens the firmware is left stuck
        mid-read forever (recv_all loops until it has every byte), so even
        an unrelated later `ping` never gets answered until the board is
        redownloaded. Row-sized writes with a flush between them keep the
        pipe draining steadily instead of building up one huge backlog.
        """
        sh, w, _ = strip_rgb.shape
        data = strip_rgb.astype(np.uint8).tobytes()
        row_bytes = w * 3
        with self.lock:
            self._send(b"U" + self._u16(w) + self._u16(sh))
            for row in range(sh):
                self._send(data[row * row_bytes:(row + 1) * row_bytes])
            self._sync([b"UACK"], timeout=timeout, stage="upload")
            (checksum,) = struct.unpack("<I", self._read(4))
            return checksum

    def run(self, w, h, sh, nframes, timeout=120.0):
        """Returns dict: cycles, tiles_done, res_mismatch, min_gap, max_gap, feed_stall, status."""
        with self.lock:
            hdr = self._u16(w) + self._u16(h) + self._u16(sh) + self._u16(nframes)
            self._send(b"R" + hdr)
            self._sync([b"RDON"], timeout=timeout, stage="run")
            vals = struct.unpack("<IIIIIII", self._read(28, timeout=timeout, stage="run reply"))
            keys = ("cycles", "tiles_done", "res_mismatch", "min_gap", "max_gap",
                    "feed_stall", "status")
            return dict(zip(keys, vals))

    def gres(self, n, timeout=60.0):
        """Returns n uint16 words, {logit1, logit0} packed as sent by the RTL."""
        with self.lock:
            self._send(b"G" + self._u16(n))
            self._sync([b"GRES"], timeout=timeout, stage="gres")
            data = self._read(n * 2, timeout=timeout, stage="gres payload")
            return struct.unpack(f"<{n}H", data)

    def abort(self):
        with self.lock:
            self._send(b"X")
            self._sync([b"XACK"], stage="abort")


# --------------------------------------------------------------------------
def _load_image_strip(path, w, sh):
    """Loads an image, resizes to (w, 480) (the board's target frame height),
    and takes the top `sh` rows as the strip -- matching
    ref/make_vectors.py's gen_strip_and_frame() convention."""
    from PIL import Image
    im_full = Image.open(path).convert("RGB").resize((w, 480))
    return np.asarray(im_full)[:sh, :, :]


def cmd_ping(link, args):
    link.ping()
    print("PONG")
    return 0


def cmd_id(link, args):
    tcid, version, status = link.id()
    print(f"TCID=0x{tcid:08x} VERSION=0x{version:08x} STATUS=0x{status:08x}")
    if tcid != 0x5443_4E31:
        print("MISMATCH: expected ID 0x5443_4E31 (\"TCN1\")", file=sys.stderr)
        return 1
    return 0


def cmd_echo(link, args):
    rng = np.random.default_rng(1)
    data = rng.integers(0, 256, size=args.bytes, dtype=np.uint8).tobytes()
    t0 = time.time()
    got = link.echo(data)
    dt = time.time() - t0
    ok = got == data
    kbps = (len(data) / 1024) / dt if dt > 0 else float("inf")
    print(f"echo: {args.bytes} bytes, {'OK' if ok else 'MISMATCH'}, {kbps:.1f} KB/s")
    return 0 if ok else 1


def cmd_upload(link, args):
    strip = _load_image_strip(args.image, args.w, args.sh)
    want_checksum = int(strip.astype(np.uint64).sum()) & 0xFFFFFFFF
    checksum = link.upload(strip)
    ok = checksum == want_checksum
    print(f"upload: {args.w}x{args.sh}, checksum {'OK' if ok else 'MISMATCH'} "
          f"(got 0x{checksum:08x} want 0x{want_checksum:08x})")
    return 0 if ok else 1


def _strip_for(args):
    if args.image:
        return _load_image_strip(args.image, args.w, args.sh)
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(args.sh, args.w, 3), dtype=np.uint8)


def cmd_bench(link, args):
    strip = _strip_for(args)
    link.upload(strip)
    t0 = time.time()
    result = link.run(args.w, args.h, args.sh, args.frames)
    dt = time.time() - t0

    cycles = result["cycles"]
    fps = (args.frames * 50e6) / cycles if cycles else 0.0
    tiles_per_frame = (args.w // 16) * (args.h // 16)
    tps = result["tiles_done"] / (cycles / 50e6) if cycles else 0.0

    print(f"bench: {args.w}x{args.h}, {args.frames} frames, "
          f"cycles={cycles} fps={fps:.2f} tiles/s={tps:.0f} "
          f"tiles_done={result['tiles_done']} (expect {tiles_per_frame * args.frames}) "
          f"res_mismatch={result['res_mismatch']} "
          f"min_gap={result['min_gap']} max_gap={result['max_gap']} "
          f"feed_stall={result['feed_stall']} status=0x{result['status']:08x} "
          f"wall={dt:.2f}s")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "bench.txt"), "w") as f:
            f.write(f"{result}\nfps={fps:.2f}\n")

    return 0 if result["res_mismatch"] == 0 else 1


def cmd_check(link, args):
    """Uploads a strip, runs 1 frame, reads results back, and compares against
    ref/int_model.py run on the same replayed frame (same strip-repeat logic
    make_vectors.py's gen_strip_and_frame() used for the expected CSVs)."""
    strip = _strip_for(args)
    link.upload(strip)
    result = link.run(args.w, args.h, args.sh, 1)

    model = IntModel(gen_dir=os.path.join(os.path.dirname(__file__), "..", "gen"))
    h, w = args.h, args.w
    replayed = strip[np.arange(h) % args.sh, :, :]

    n_tiles_w, n_tiles_h = w // 16, h // 16
    exp = {}
    for band in range(n_tiles_h):
        for tcol in range(n_tiles_w):
            tile = replayed[band * 16:(band + 1) * 16, tcol * 16:(tcol + 1) * 16, :]
            l0, l1 = model.run(tile)
            exp[(band, tcol)] = (int(l0), int(l1))

    words = link.gres(n_tiles_h * PITCH)
    mismatches = 0
    for band in range(n_tiles_h):
        for tcol in range(n_tiles_w):
            w16 = words[band * PITCH + tcol]
            got = (w16 & 0xFF, (w16 >> 8) & 0xFF)
            if got != exp[(band, tcol)]:
                mismatches += 1
                print(f"MISMATCH band={band} tcol={tcol} got={got} exp={exp[(band, tcol)]}",
                      file=sys.stderr)

    print(f"check: {n_tiles_h * n_tiles_w} tiles, {mismatches} mismatches, "
          f"res_mismatch={result['res_mismatch']}")
    return 0 if (mismatches == 0 and result["res_mismatch"] == 0) else 1


def cmd_tiles(link, args):
    """Bit-exact test using vectors/tiles.hex (1000 tiles), repacked on the fly
    into 640x48 strips of 120 tiles each (9 strips), matching the plan's
    board-side bit-exact test."""
    vec_dir = os.path.join(os.path.dirname(__file__), "..", "vectors")
    with open(os.path.join(vec_dir, "tiles.hex")) as f:
        words = [int(x.strip(), 16) for x in f if x.strip()]
    n_total = len(words) // 256
    n = min(args.n, n_total)

    with open(os.path.join(vec_dir, "tiles_expected.hex")) as f:
        exp_lines = [line.split() for line in f if line.strip()]
    exp = [(int(a, 16), int(b, 16)) for a, b in exp_lines[:n]]

    bands_per_strip = 48 // 16  # 3
    tiles_per_strip = bands_per_strip * PITCH  # 120, matches the plan (9 strips for 1000 tiles)

    mismatches = 0
    checked = 0
    strip_idx = 0
    while checked < n:
        strip = np.zeros((48, MAX_W, 3), dtype=np.uint8)
        tile_map = {}
        n_here = min(tiles_per_strip, n - checked)
        for i in range(n_here):
            band, tcol = divmod(i, PITCH)
            tile_idx = checked + i
            tile_map[(band, tcol)] = tile_idx
            base = tile_idx * 256
            for py in range(16):
                for px in range(16):
                    word = words[base + py * 16 + px]
                    r, g, b = word & 0xFF, (word >> 8) & 0xFF, (word >> 16) & 0xFF
                    strip[band * 16 + py, tcol * 16 + px] = (r, g, b)

        link.upload(strip)
        result = link.run(MAX_W, 48, 48, 1)
        words_out = link.gres(bands_per_strip * PITCH)

        for (band, tcol), tile_idx in tile_map.items():
            w16 = words_out[band * PITCH + tcol]
            got = (w16 & 0xFF, (w16 >> 8) & 0xFF)
            if got != exp[tile_idx]:
                mismatches += 1
                print(f"MISMATCH tile {tile_idx}: got {got} expected {exp[tile_idx]}",
                      file=sys.stderr)
        if result["res_mismatch"] != 0:
            print(f"WARNING: strip {strip_idx} res_mismatch={result['res_mismatch']}",
                  file=sys.stderr)

        checked += n_here
        strip_idx += 1

    print(f"tiles: {checked} tiles, {mismatches} mismatches")
    return 0 if mismatches == 0 else 1


def cmd_abort(link, args):
    link.abort()
    print("XACK")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool")
    ap.add_argument("--instance", type=int)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("ping")
    sub.add_parser("id")

    p = sub.add_parser("echo")
    p.add_argument("--bytes", type=int, default=65536)

    p = sub.add_parser("upload")
    p.add_argument("image")
    p.add_argument("--w", type=int, default=640)
    p.add_argument("--sh", type=int, default=48)

    p = sub.add_parser("bench")
    p.add_argument("--w", type=int, default=640)
    p.add_argument("--h", type=int, default=480)
    p.add_argument("--sh", type=int, default=48)
    p.add_argument("--frames", type=int, default=200)
    p.add_argument("--image")
    p.add_argument("--out")

    p = sub.add_parser("check")
    p.add_argument("--w", type=int, default=640)
    p.add_argument("--h", type=int, default=480)
    p.add_argument("--sh", type=int, default=48)
    p.add_argument("--image")

    p = sub.add_parser("tiles")
    p.add_argument("--n", type=int, default=1000)

    sub.add_parser("abort")

    args = ap.parse_args()
    link = TcnnLink(tool=args.tool, instance=args.instance)
    try:
        fn = {
            "ping": cmd_ping, "id": cmd_id, "echo": cmd_echo, "upload": cmd_upload,
            "bench": cmd_bench, "check": cmd_check, "tiles": cmd_tiles, "abort": cmd_abort,
        }[args.command]
        rc = fn(link, args)
    finally:
        link.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
