#!/usr/bin/env python3
"""
template_writer.py
-------------------
Drives the NIOS V firmware's command parser over the JTAG UART by
spawning `juart-terminal` (or `nios2-terminal` on older toolchains) as a
subprocess and talking to its stdin/stdout pipes.

IMPORTANT:
- Only one JTAG client can hold the debug connection at a time. Close
  Eclipse/Quartus debug sessions and any other juart-terminal/nios2-terminal
  instance before running this script.
- juart-terminal must be on PATH (it ships with the Quartus/Nios V toolchain).
- Your firmware must already be running on the board and printing "READY".

Usage:
  python template_writer.py --write 0 0 255
  python template_writer.py --read 0 0
  python template_writer.py --file template.csv     # bulk load a 16x16 grid
"""

import argparse
import subprocess
import sys
import time

TERMINAL_CMD = ["juart-terminal"]  # add ["--instance", "0"] etc. if you have >1 JTAG UART


class JtagUartSession:
    def __init__(self, cmd=TERMINAL_CMD, ready_timeout=10.0):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )
        self._wait_for_ready(ready_timeout)

    def _readline(self, timeout=5.0):
        # Simple blocking readline; swap for a select()-based version if you
        # need real timeout enforcement on your platform.
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("juart-terminal closed the connection")
        return line.strip()

    def _wait_for_ready(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._readline()
            if line == "READY":
                return
        raise TimeoutError("Never saw READY from target; is the firmware running?")

    def send(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def write_template(self, row, col, value):
        self.send(f"W {row} {col} {value}")
        resp = self._readline()
        if not resp.startswith("OK"):
            raise RuntimeError(f"write failed: {resp}")
        return resp

    def read_template(self, row, col):
        self.send(f"R {row} {col}")
        resp = self._readline()
        if not resp.startswith("VAL"):
            raise RuntimeError(f"read failed: {resp}")
        _, r, c, val = resp.split()
        return int(val)

    def close(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)


def load_csv_grid(session, path):
    """CSV of 16 rows x 16 cols, values 0-255."""
    with open(path, newline="") as f:
        for row, line in enumerate(f):
            values = [v.strip() for v in line.split(",") if v.strip() != ""]
            for col, v in enumerate(values):
                session.write_template(row, col, int(v))
                print(f"  wrote [{row}][{col}] = {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", nargs=3, type=int, metavar=("ROW", "COL", "VALUE"))
    ap.add_argument("--read", nargs=2, type=int, metavar=("ROW", "COL"))
    ap.add_argument("--file", type=str, help="CSV file with a 16x16 grid of values")
    args = ap.parse_args()

    session = JtagUartSession()
    try:
        if args.write:
            row, col, value = args.write
            resp = session.write_template(row, col, value)
            print(resp)
        elif args.read:
            row, col = args.read
            val = session.read_template(row, col)
            print(f"template[{row}][{col}] = {val}")
        elif args.file:
            load_csv_grid(session, args.file)
        else:
            print("Nothing to do. Use --write, --read, or --file.", file=sys.stderr)
            sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
