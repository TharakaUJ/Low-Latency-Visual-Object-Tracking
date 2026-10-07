#!/usr/bin/env python3
"""P2 demo: ZSAD tracking on the DE2-115 over Ethernet (hardware in the loop).

The server scales each frame so the target is ~16 px, crops an 80x80 ROI around the last position and
sends it to the board row by row; the board runs the existing ZSAD matcher and returns the best
position. The bit-exact Python model runs on the same crop ("FPGA = model"). The view is served as a
live MJPEG page (open http://<bind>:<port>/ in a browser) and recorded as an MP4.

  python3 demo_zsad.py --source otb --seq Walking                 # OTB replay, GT first box
  python3 demo_zsad.py --source webcam --cam 0                     # draw the box on the web page
  python3 demo_zsad.py --source webcam --init-box 300,200,60,80    # or give it (x,y,w,h)
"""
import argparse, csv, json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from board_link import BoardLink, FCLK, F_COMPLETE, F_GOOD, F_TRACKED
from zsad_model import ZsadTracker, match, SCORE_SAT

VIEW_W = 960
NOTE = "Scaling + 80x80 ROI crop run on the server; tracking runs on the DE2-115 FPGA (ZSAD 16x16)."

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>FPGA tracking demo</title>
<style>body{margin:0;background:#111;color:#ddd;font:14px sans-serif}#w{position:relative;display:inline-block}
img{display:block;max-width:100vw}#sel{position:absolute;border:2px dashed #0f0;display:none;pointer-events:none}
p{margin:6px 10px}</style></head><body><div id="w"><img id="v" src="/stream"><div id="sel"></div></div>
<p id="h"></p><script>
const v=document.getElementById('v'),s=document.getElementById('sel'),h=document.getElementById('h');
let st=null;
fetch('/state').then(r=>r.json()).then(j=>{if(j.need_box)h.textContent='Drag a box around the target to start tracking.';});
v.addEventListener('mousedown',e=>{const r=v.getBoundingClientRect();st=[e.clientX-r.left,e.clientY-r.top];e.preventDefault();});
v.addEventListener('mousemove',e=>{if(!st)return;const r=v.getBoundingClientRect();const x=e.clientX-r.left,y=e.clientY-r.top;
 s.style.display='block';s.style.left=Math.min(x,st[0])+'px';s.style.top=Math.min(y,st[1])+'px';
 s.style.width=Math.abs(x-st[0])+'px';s.style.height=Math.abs(y-st[1])+'px';});
v.addEventListener('mouseup',e=>{if(!st)return;const r=v.getBoundingClientRect();const x=e.clientX-r.left,y=e.clientY-r.top;
 const k=v.naturalWidth/r.width;const b=[Math.min(x,st[0])*k,Math.min(y,st[1])*k,Math.abs(x-st[0])*k,Math.abs(y-st[1])*k];
 st=null;s.style.display='none';if(b[2]>4&&b[3]>4)fetch('/init?box='+b.map(Math.round).join(','));});
</script></body></html>"""


class Stream:
    """Latest JPEG for the MJPEG clients, plus a box drawn on the web page (view coordinates)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpg, self.seq = None, 0
        self.box_view, self.need_box = None, False

    def put(self, img):
        ok, b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self.cond:
                self.jpg, self.seq = b.tobytes(), self.seq + 1
                self.cond.notify_all()


def make_handler(st):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                b = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/state":
                b = json.dumps(dict(need_box=st.need_box)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/init":
                try:
                    st.box_view = [float(v) for v in parse_qs(u.query)["box"][0].split(",")][:4]
                    self.send_response(204)
                except (KeyError, ValueError):
                    self.send_response(400)
                self.end_headers()
            elif u.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                last = -1
                try:
                    while True:
                        with st.cond:
                            st.cond.wait_for(lambda: st.seq != last, timeout=5)
                            jpg, last = st.jpg, st.seq
                        if jpg is None:
                            continue
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_response(404)
                self.end_headers()
    return H


class Source:
    def __init__(self, a):
        self.a = a
        if a.source == "otb":
            import otb_src
            self.otb = otb_src
            d = otb_src.load(a.seq, a.target_px, color=True)
            self.d, self.i = d, 0
            self.name = a.seq
            self.gt_orig = d["gt_orig"]
        else:
            self.cap = cv2.VideoCapture(a.cam)
            if not self.cap.isOpened():
                raise SystemExit(f"cannot open webcam {a.cam}")
            self.name = f"webcam{a.cam}"
            self.gt_orig = None

    def next(self):
        """-> (color frame in original resolution, frame index) or (None, None) at the end."""
        if self.a.source == "otb":
            if self.i >= len(self.d["frames_orig"]):
                if not self.a.loop:
                    return None, None
                self.i = 0
            f, k = self.d["frames_orig"][self.i], self.i
            self.i += 1
            return f, k
        ok, f = self.cap.read()
        return (f, None) if ok else (None, None)


def draw(view_img, k, info):
    """Boxes and status panel on the view image (already resized to VIEW_W)."""
    s = info["view_scale"]
    if info.get("gt") is not None and np.isfinite(info["gt"]).all():
        x, y, w, h = info["gt"] * s
        cv2.rectangle(view_img, (int(x), int(y)), (int(x + w), int(y + h)), (200, 200, 200), 1)
    rx, ry, rs = [v * s for v in info["roi"]]
    for t in range(0, int(rs), 8):                    # dashed ROI square
        for (p, q) in (((rx + t, ry), (rx + min(t + 4, rs), ry)), ((rx + t, ry + rs), (rx + min(t + 4, rs), ry + rs)),
                       ((rx, ry + t), (rx, ry + min(t + 4, rs))), ((rx + rs, ry + t), (rx + rs, ry + min(t + 4, rs)))):
            cv2.line(view_img, (int(p[0]), int(p[1])), (int(q[0]), int(q[1])), (255, 200, 0), 1)
    cx, cy = info["center"]
    bw, bh = info["box_wh"]
    col = (0, 220, 0) if info["good"] else (0, 160, 255)
    cv2.rectangle(view_img, (int((cx - bw / 2) * s), int((cy - bh / 2) * s)),
                  (int((cx + bw / 2) * s), int((cy + bh / 2) * s)), col, 2)
    H = view_img.shape[0]
    pad = np.zeros((126, view_img.shape[1], 3), np.uint8)
    agree = info["agree_n"] == info["n"]
    lines = [
        (f"{info['name']}  frame {k if k is not None else info['n']}   FPGA = model: "
         f"{'YES' if info['agree'] else 'NO'} ({info['agree_n']}/{info['n']})   "
         f"ZSAD {info['score']}{'' if info['good'] else ' (rejected: hold)'}",
         (0, 230, 0) if agree else (0, 0, 255)),
        (f"FPGA compute {info['fpga_us']:.1f} us   network round trip {info['rtt_us']:.0f} us "
         f"(transport, not part of the drone system)   {info['fps']:.1f} fps", (230, 230, 230)),
        (NOTE, (180, 180, 180)),
        ("Box: green = FPGA result (orange = rejected, hold)   grey = ground truth   dashed = ROI sent to FPGA",
         (180, 180, 180)),
    ]
    for j, (txt, c) in enumerate(lines):
        cv2.putText(pad, txt, (10, 26 + 30 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, 1, cv2.LINE_AA)
    return np.vstack([view_img, pad])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["otb", "webcam"], default="otb")
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--init-box", default=None, help="webcam: x,y,w,h in camera pixels")
    ap.add_argument("--roi", type=int, default=80)
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--loop", action="store_true", help="OTB: replay the sequence forever")
    ap.add_argument("--ip", default="10.8.100.230", help="board IP")
    ap.add_argument("--bind", default="100.76.229.14", help="web page address (Tailscale)")
    ap.add_argument("--http-port", type=int, default=8090)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    src = Source(a)
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results",
                                f"demo_{src.name}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    st = Stream()
    srv = ThreadingHTTPServer((a.bind, a.http_port), make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"view: http://{a.bind}:{a.http_port}/   output: {out}", flush=True)

    link = BoardLink(a.ip)
    link.drain()

    # ---- first frame and box ----
    f0, k0 = src.next()
    if f0 is None:
        raise SystemExit("no frames")
    vs = VIEW_W / f0.shape[1]
    if a.source == "otb":
        box = src.gt_orig[0].copy()
    elif a.init_box:
        box = np.array([float(v) for v in a.init_box.split(",")])
    else:
        st.need_box = True
        while st.box_view is None:                 # live preview until a box is drawn on the page
            v = cv2.resize(f0, (VIEW_W, int(f0.shape[0] * vs)))
            cv2.putText(v, "Drag a box around the target on this page", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
            st.put(v)
            f, _ = src.next()
            if f is not None:
                f0 = f
            time.sleep(0.03)
        box = np.array(st.box_view) / vs
        st.need_box = False
    s = a.target_px / np.sqrt(box[2] * box[3])

    def scaled(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, (max(1, round(g.shape[1] * s)), max(1, round(g.shape[0] * s))),
                          interpolation=cv2.INTER_AREA)

    tr = ZsadTracker(scaled(f0), ((box[0] + box[2] / 2) * s, (box[1] + box[3] / 2) * s), a.roi)
    if not link.send_template(tr.tmpl):
        raise SystemExit("board did not acknowledge the template (is the p2_zsad bitstream loaded?)")

    vw = None
    if not a.no_video:
        h0 = int(f0.shape[0] * vs) + 126
        vw = cv2.VideoWriter(os.path.join(out, "demo.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (VIEW_W, h0))

    rows, preds, ks = [], [], []
    n = agree_n = 0
    t_prev = time.perf_counter()
    fps_s = 0.0
    fid = 1
    period = 1.0 / a.fps
    t_next = time.perf_counter()
    try:
        while True:
            f, k = src.next()
            if f is None:
                break
            if a.source == "otb" and k == 0:       # sequence restart (loop): re-init from GT
                tr = ZsadTracker(scaled(f), ((box[0] + box[2] / 2) * s, (box[1] + box[3] / 2) * s), a.roi)
                link.send_template(tr.tmpl)
                continue
            g = scaled(f)
            rx, ry, crop = tr.crop(g)
            mx, my, mz, mgood = match(crop, tr.tmpl)
            res, t0, t1 = link.track(fid, crop)
            fid += 1
            n += 1
            if res is None:
                ok, good, score, f_us, rtt = False, False, -1, float("nan"), float("nan")
            else:
                tracked = bool(res["flags"] & F_TRACKED) and bool(res["flags"] & F_COMPLETE)
                good = bool(res["flags"] & F_GOOD)
                score = res["score"]
                ok = tracked and score == min(mz, SCORE_SAT) and good == mgood and \
                    (not good or (res["x"], res["y"]) == (mx, my))
                tr.update(rx, ry, res["x"], res["y"], good and tracked)
                f_us = ((res["t_result"] - res["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6
                rtt = (res["t_recv_ns"] - t1) / 1e3
            agree_n += ok
            cx, cy = tr.center()
            now = time.perf_counter()
            fps_s = 0.9 * fps_s + 0.1 * (1.0 / max(1e-6, now - t_prev)) if fps_s else 1.0 / max(1e-6, now - t_prev)
            t_prev = now
            info = dict(name=src.name, n=n, agree=ok, agree_n=agree_n, score=score, good=good,
                        fpga_us=f_us, rtt_us=rtt, fps=fps_s, view_scale=vs,
                        center=(cx / s, cy / s), box_wh=(box[2], box[3]),
                        roi=(rx / s, ry / s, a.roi / s),
                        gt=src.gt_orig[k] if (src.gt_orig is not None and k is not None) else None)
            view = draw(cv2.resize(f, (VIEW_W, int(f.shape[0] * vs))), k, info)
            st.put(view)
            if vw is not None:
                vw.write(view)
            rows.append([n, k, rx, ry, None if res is None else res["x"], None if res is None else res["y"],
                         score, int(good), mx, my, min(mz, SCORE_SAT), int(mgood), int(ok),
                         round(f_us, 2), round(rtt, 1), round(cx / s, 1), round(cy / s, 1)])
            if k is not None:
                preds.append((k, cx, cy))
            t_next += period
            dt = t_next - time.perf_counter()
            if dt > 0:
                time.sleep(dt)
            else:
                t_next = time.perf_counter()
    except KeyboardInterrupt:
        pass
    finally:
        if vw is not None:
            vw.release()

    with open(os.path.join(out, "frames.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["n", "frame", "roi_x", "roi_y", "fpga_x", "fpga_y", "fpga_score", "fpga_good", "model_x",
                    "model_y", "model_score", "model_good", "agree", "fpga_compute_us", "rtt_us", "cx_orig", "cy_orig"])
        w.writerows(rows)
    fu = np.array([r[13] for r in rows], float)
    rt = np.array([r[14] for r in rows], float)
    lines = [f"# P2 demo run: {src.name}", "",
             f"command: `python3 demo_zsad.py {' '.join(f'--{k.replace(chr(95), chr(45))} {v}' for k, v in vars(a).items() if v not in (None, False))}`", "",
             "| metric | value |", "|---|---|",
             f"| frames tracked | {n} |",
             f"| FPGA = model | {agree_n}/{n} |",
             f"| rejected matches (hold) | {sum(1 for r in rows if r[7] == 0)} |",
             f"| FPGA compute after the last row (us) | p50 {np.nanpercentile(fu, 50):.1f}, max {np.nanmax(fu):.1f} |",
             f"| network round trip, last row sent -> result (us) | p50 {np.nanpercentile(rt, 50):.0f}, p99 {np.nanpercentile(rt, 99):.0f}, max {np.nanmax(rt):.0f} |"]
    if a.source == "otb" and preds and not a.loop:
        k_all = len(src.d["frames"])
        pc = np.full((k_all, 2), np.nan)
        g0 = src.d["gt"][0]
        pc[0] = (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2)
        for k, cx, cy in preds:
            pc[k] = (cx, cy)
        gt_c = src.d["gt"][:, :2] + src.d["gt"][:, 2:] / 2
        m = src.otb.metrics.compute(pc, gt_c, s)
        lines.append(f"| P@20 (information only) | {m['prec20']:.1f} |")
        lines.append(f"| success AUC, fixed box size (information only) | {src.otb.iou_auc(pc, src.gt_orig, s):.1f} |")
    lines += ["", NOTE]
    open(os.path.join(out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    srv.shutdown()


if __name__ == "__main__":
    main()
