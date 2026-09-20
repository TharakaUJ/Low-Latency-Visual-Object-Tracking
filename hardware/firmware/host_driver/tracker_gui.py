#!/usr/bin/env python3
"""
tracker_gui.py - grab a frame, click a point, a 16x16 luma patch around it
becomes the hardware template. Optionally polls boundary_x/y live.

    pip install pillow numpy
    python tracker_gui.py [--gray] [--zoom 1] [--tool juart-terminal]

Workflow
  1. "Grab frame"  : SDRAM writes freeze, frame downloads, SDRAM resumes.
                     (Y stream keeps flowing into the matcher the whole time.)
  2. Click image   : template = 16x16 luma of ONE FIELD around the click
                     (drawn as a 16 x 32 box on the woven picture), sent to
                     the FPGA and read back for verification.
  3. "Calibrate"   : with the target held still, stores
                     delta = boundary - template top-left, so the live marker
                     lines up (absorbs anchor convention + pipeline latency).
  4. "Track" toggle: polls boundary ~5 Hz and draws a marker.
"""
import argparse
import threading
import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk

from niosv_link import NiosLink, W, H, WIN, weave, raw_to_rgb, click_to_template


class App:
    def __init__(self, root, link, gray, zoom):
        self.root, self.link, self.zoom = root, link, zoom
        self.gray = tk.BooleanVar(value=gray)
        self.track = tk.BooleanVar(value=False)
        self.y_plane = None
        self.tmpl_tl = None          # (col0,row0) in field coords
        self.tmpl_field = 0
        self.delta = (0, 0)
        self.busy = False
        self.last_bound = None

        bar = ttk.Frame(root); bar.pack(fill="x")
        ttk.Button(bar, text="Grab frame", command=self.grab).pack(side="left")
        ttk.Checkbutton(bar, text="Luma only (2x faster)", variable=self.gray).pack(side="left")
        ttk.Button(bar, text="Calibrate", command=self.calibrate).pack(side="left")
        ttk.Checkbutton(bar, text="Track", variable=self.track,
                        command=self.poll).pack(side="left")
        self.status = tk.StringVar(value="Grab a frame, then click the target.")
        ttk.Label(root, textvariable=self.status).pack(fill="x")

        self.canvas = tk.Canvas(root, width=W * zoom, height=H * zoom, bg="black")
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_click)
        self.img_id = self.rect_id = self.mark_id = None

    # -- helpers -------------------------------------------------------------
    def set_status(self, s):
        self.root.after(0, lambda: self.status.set(s))

    def bg(self, fn):
        if self.busy:
            return
        self.busy = True
        def run():
            try:
                fn()
            except Exception as e:
                self.set_status(f"ERROR: {e!r}")
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    # -- grab ----------------------------------------------------------------
    def grab(self):
        luma = self.gray.get()
        def work():
            self.set_status("Freezing SDRAM writes, downloading...")
            yp, grid, ok = self.link.grab(
                luma, lambda d, t: self.set_status(f"Downloading {100*d/t:5.1f}%"))
            self.y_plane = yp
            img = weave(yp) if grid is None else raw_to_rgb(grid)
            self.root.after(0, lambda: self.show(img))
            self.set_status("Frame OK. Click the target." if ok
                            else "WARNING: checksum mismatch - frame may be corrupt.")
        self.bg(work)

    def show(self, arr):
        im = Image.fromarray(arr)
        if self.zoom != 1:
            im = im.resize((W * self.zoom, H * self.zoom), Image.NEAREST)
        self.tk_img = ImageTk.PhotoImage(im)
        if self.img_id is None:
            self.img_id = self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        else:
            self.canvas.itemconfig(self.img_id, image=self.tk_img)

    # -- click -> template ---------------------------------------------------
    def on_click(self, ev):
        if self.y_plane is None or self.busy:
            return
        x, y = ev.x // self.zoom, ev.y // self.zoom
        tmpl, (c0, r0) = click_to_template(self.y_plane, x, y)
        self.tmpl_tl, self.tmpl_field = (c0, r0), y & 1

        z = self.zoom
        top_woven = 2 * r0 + self.tmpl_field
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            c0 * z, top_woven * z, (c0 + WIN) * z, (top_woven + 2 * WIN) * z,
            outline="lime", width=2)

        def work():
            self.set_status("Sending template...")
            bad = self.link.load_template(tmpl)
            self.set_status(
                f"Template set from field {self.tmpl_field}, top-left (col {c0}, row {r0})."
                + ("" if bad == 0 else f"  !! {bad} readback mismatches"))
        self.bg(work)

    # -- boundary / calibration ---------------------------------------------
    def calibrate(self):
        if self.tmpl_tl is None:
            return self.set_status("Set a template first.")
        def work():
            bx, by = self.link.boundary()
            self.delta = (bx - self.tmpl_tl[0], by - self.tmpl_tl[1])
            self.set_status(f"boundary=({bx},{by}) vs template top-left {self.tmpl_tl} "
                            f"-> delta={self.delta}")
        self.bg(work)

    def poll(self):
        if not self.track.get():
            return
        def work():
            self.last_bound = self.link.boundary()
            self.root.after(0, self.draw_marker)
        if not self.busy:
            self.bg(work)
        self.root.after(200, self.poll)

    def draw_marker(self):
        if self.last_bound is None: return
        bx, by = self.last_bound
        c = bx - self.delta[0]
        r = by - self.delta[1]
        z = self.zoom
        y_w = 2 * r + self.tmpl_field
        if self.mark_id: self.canvas.delete(self.mark_id)
        self.mark_id = self.canvas.create_rectangle(
            c * z, y_w * z, (c + WIN) * z, (y_w + 2 * WIN) * z, outline="red", width=2)
        self.status.set(f"boundary = ({bx},{by})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool"); ap.add_argument("--instance", type=int)
    ap.add_argument("--gray", action="store_true", help="default to luma-only grabs")
    ap.add_argument("--zoom", type=int, default=1)
    a = ap.parse_args()
    link = NiosLink(a.tool, a.instance)
    root = tk.Tk(); root.title("NiosV template tracker")
    App(root, link, a.gray, a.zoom)
    root.protocol("WM_DELETE_WINDOW", lambda: (link.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
