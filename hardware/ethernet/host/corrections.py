"""Server corrections for demo.py: the OSTrack heavy tracker (heavy_server.py, research GPU environment) and
the K3 correction rule of the locked hardware system (research common/linksim.py, E45 simulate_lazy,
decision 2026-10-06_E53_k3_for_hardware):

  every N frames (frame s) the edge (FPGA) position edge(s) and frame s go to the server; OSTrack answers
  heavy(s) (ost-gated tau 0.6). The answer is applied at frame s + L (or as soon as it is ready, if later):
    position  p <- p_fpga(s+L) + heavy(s) - edge(s)     (an offset: the motion since s is kept)
    template  re-cut from frame s at heavy(s)            (mode "pos+tmpl"; "pos" keeps the template)
Positions are top-left corners of the 16x16 window in scaled frame pixels (as trackers.Track).
"""
import json, os, queue, subprocess, sys, threading, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.expanduser("~/Documents/Object_tracking_test/object_tracking")
HEAVY_PY = os.path.join(RESEARCH, ".venv-heavy", "bin", "python")
WIN = 16
TAU = 0.6


class Heavy:
    """Client of heavy_server.py: requests go out through a sender thread, answers come back on a reader
    thread, so the display loop never waits for the GPU."""

    def __init__(self, log_path):
        self.ready, self.error, self.device = False, None, None
        self.last_id = 0                 # request ids are unique over the whole run (late answers of an old
        self.answers = queue.Queue()     # session can never match a new request)
        self.outq = queue.Queue()
        try:
            self.p = subprocess.Popen([HEAVY_PY, os.path.join(HERE, "heavy_server.py")], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=open(log_path, "ab"))
        except OSError as e:
            self.p, self.error = None, f"cannot start OSTrack server: {e}"
            return
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._sender, daemon=True).start()

    def _reader(self):
        for line in self.p.stdout:
            d = json.loads(line)
            if d.get("ready"):
                self.ready, self.device = True, d["device"]
            else:
                self.answers.put(d)
        self.ready, self.error = False, f"OSTrack server exited (code {self.p.wait()}, see its log)"

    def _sender(self):
        while True:
            hdr, payload = self.outq.get()
            try:
                self.p.stdin.write(hdr + payload)
                self.p.stdin.flush()
            except (BrokenPipeError, ValueError):
                return

    def _send(self, d, frame):
        f = np.ascontiguousarray(frame, np.uint8)
        d.update(h=f.shape[0], w=f.shape[1])
        self.outq.put(((json.dumps(d) + "\n").encode(), f.tobytes()))

    def init(self, frame, box):
        self._send({"cmd": "init", "box": [float(v) for v in box]}, frame)

    def query(self, rid, frame, center, tau=TAU):
        self._send({"cmd": "query", "id": rid, "center": [float(center[0]), float(center[1])], "tau": tau}, frame)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.answers.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        if self.p is not None:
            self.p.kill()


class Corrections:
    """K3 correction loop state for one tracking session. Settings (on, N, L, mode) may change at any
    time; a request keeps the L it was sent with."""

    def __init__(self, heavy):
        self.heavy = heavy
        self.on, self.N, self.L, self.mode = True, 30, 6, "pos+tmpl"
        self.reset_stats()

    def reset_stats(self):
        self.rid = 0                 # requests in this session (ids: heavy.last_id)
        self.failed = 0              # corrections the board did not acknowledge
        self.inited = False
        self.init_args = None
        self.pending = {}            # rid -> request (answer added when it arrives)
        self.done = []               # applied corrections (records for the dashboard and corrections.csv)
        self.events = []             # (n, "req" | "app", rid) for the plots / banners
        self.init_ms = None

    def reset(self, frame, box):
        """New target (start, loop restart, box drawn): OSTrack init on this frame, pending requests dropped.
        The counts and the applied list run over the whole session."""
        self.pending = {}
        self.inited = False
        self.init_args = (frame.copy(), np.asarray(box, float).copy())
        self._ensure_init()

    def _ensure_init(self):
        """OSTrack init once the server is up (it may still be loading when the session starts)."""
        if not self.inited and self.init_args is not None and self.available():
            self.heavy.init(*self.init_args)
            self.inited = True

    def available(self):
        return self.heavy is not None and self.heavy.ready

    def request(self, n, frame, fp, pos, scale):
        """Call after frame n is tracked (and due corrections applied): send a request if n is a multiple of N."""
        self._ensure_init()
        if not (self.on and self.inited and self.N > 0 and n % self.N == 0):
            return None
        self.rid += 1
        self.heavy.last_id += 1
        rid = self.heavy.last_id
        c = ((pos[0] + WIN / 2) / scale, (pos[1] + WIN / 2) / scale)        # edge position, original pixels
        self.pending[rid] = dict(rid=rid, s=n, edge=(int(pos[0]), int(pos[1])), fp=fp.copy(), scale=scale,
                                      L=self.L, due=n + self.L, mode=self.mode, t_sent=time.perf_counter(), ans=None)
        self.heavy.query(rid, frame, c)
        self.events.append((n, "req", rid))
        return rid

    def due(self, n):
        """Requests whose answer has arrived and whose time has come (s + L <= n), oldest first."""
        if self.heavy is not None:
            for a in self.heavy.poll():
                if a.get("cmd") == "init":
                    self.init_ms = a["ms"]
                elif a.get("id") in self.pending:
                    r = self.pending[a["id"]]
                    r["ans"], r["t_ans"] = a, time.perf_counter()
        out = [r for r in self.pending.values() if r["ans"] is not None and n >= r["due"]]
        for r in sorted(out, key=lambda r: r["s"]):
            del self.pending[r["rid"]]
        return sorted(out, key=lambda r: r["s"])

    def heavy_pos(self, r):
        """OSTrack box at frame s -> top-left in scaled pixels (research real_positions: centre * s - 8, round, clip)."""
        b = np.array(r["ans"]["box"], float)
        H, W = r["fp"].shape
        c = (b[:2] + b[2:] / 2) * r["scale"] - WIN / 2
        return np.clip(np.round(c), [0, 0], [W - WIN, H - WIN]).astype(int)

    def record(self, r, n, hs, before, after, tmpl_changed):
        rec = dict(rid=r["rid"], s=r["s"], applied=n, L=r["L"], late=n - r["due"], mode=r["mode"],
                   edge_x=r["edge"][0], edge_y=r["edge"][1], heavy_x=int(hs[0]), heavy_y=int(hs[1]),
                   drift_px=round(float(np.hypot(hs[0] - r["edge"][0], hs[1] - r["edge"][1])), 2),
                   drift_orig_px=round(float(np.hypot(hs[0] - r["edge"][0], hs[1] - r["edge"][1]) / r["scale"]), 1),
                   before_x=int(before[0]), before_y=int(before[1]), after_x=int(after[0]), after_y=int(after[1]),
                   template=int(tmpl_changed), ostrack_ms=round(r["ans"]["ms"], 1), calls=len(r["ans"]["peaks"]),
                   peaks=" ".join(f"{p:.3f}" for p in r["ans"]["peaks"]),
                   answer_ms=round((r["t_ans"] - r["t_sent"]) * 1e3, 1),
                   box_orig=[round(v, 1) for v in r["ans"]["box"]])
        self.done.append(rec)
        self.events.append((n, "app", r["rid"]))
        return rec
