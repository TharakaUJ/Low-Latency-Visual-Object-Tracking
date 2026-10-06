#!/usr/bin/env python3
"""P3 demo: tracking on the DE2-115 over Ethernet (hardware in the loop), either tracker build.

The server scales each frame so the target is ~16 px. With --crop fpga it sends the whole scaled frame
(like a camera) and the FPGA crops the ROI around its own position; with --crop server it sends only
the ROI. The board runs the tracker core of the loaded bitstream (--tracker zsad | s3x8 must match)
and returns the new position. The bit-exact host model runs on the same ROI ("FPGA = model"). The
view is served as a live MJPEG page (http://<bind>:<port>/) and recorded as an MP4.

  python3 demo.py --tracker zsad --crop fpga --source otb --seq Walking
  python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking
  python3 demo.py --tracker zsad --source webcam --cam 0          # draw the box on the web page
  python3 demo.py --tracker zsad --source webcam --no-board       # no board: host model only (labelled)
"""
import argparse, csv, json, os, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from board_link3 import BoardLink3, FCLK, F_COMPLETE, F_GOOD, F_TRACKED
import dash as D
from trackers import make_model, pad_to, Track, WIN

PREVIEW_HINT = "Drag a box around the target on this page"
NOTE = ""

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>FPGA tracking demo</title>
<style>body{margin:0;background:#000;color:#ddd;font:14px sans-serif;overflow:hidden}#w{position:relative;display:inline-block}
img{display:block}#sel{position:absolute;border:2px dashed #0f0;display:none;pointer-events:none}
#h{position:absolute;left:10px;top:6px;margin:0;color:#ff0;font-size:18px}</style></head><body>
<div id="w"><img id="v" src="/stream"><div id="sel"></div><p id="h"></p></div><script>
const v=document.getElementById('v'),s=document.getElementById('sel'),h=document.getElementById('h');
let st=null;
// scale the dashboard to the window (keeps the aspect ratio; box drawing maps back via naturalWidth)
function fitImg(){if(!v.naturalWidth)return;const k=Math.min(innerWidth/v.naturalWidth,innerHeight/v.naturalHeight);
 v.style.width=Math.floor(v.naturalWidth*k)+'px';}
setInterval(fitImg,500);window.addEventListener('resize',fitImg);
setInterval(()=>fetch('/state').then(r=>r.json()).then(j=>{h.textContent=j.need_box?
 'Drag a box around the target to start tracking.':'Drag a new box on the camera view to re-select the target.';}),1000);
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
            self.cap = cv2.VideoCapture(a.cam, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                raise SystemExit(f"cannot open webcam {a.cam} (is the user in the video group?)")
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            w, h = (int(v) for v in a.cam_size.split("x"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)              # newest frame, no backlog
            # exposure: auto (aperture priority) can halve the frame rate in a dim room; a manual
            # exposure below 33 ms keeps 30 fps (darker image: raise the gain)
            if a.cam_exposure is not None:
                ctrls = f"auto_exposure=1,exposure_time_absolute={a.cam_exposure}"
            else:
                ctrls = "auto_exposure=3"
            if a.cam_gain is not None:
                ctrls += f",gain={a.cam_gain}"
            r = subprocess.run(["v4l2-ctl", "-d", f"/dev/video{a.cam}", "--set-ctrl", ctrls],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"warning: camera controls not set ({ctrls}): {r.stderr.strip()}", flush=True)
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


def place(frame):
    """Camera frame on an empty dashboard canvas, at the same place as the camera view of the dashboard.
    -> (canvas, (ox, oy, scale)) so a box drawn on the page maps back to camera pixels."""
    img = np.zeros((D.H, D.W, 3), np.uint8)
    v, s = D.fit(frame, D.MAIN_W, D.MAIN_H)
    ox, oy = (D.MAIN_W - v.shape[1]) // 2, (D.MAIN_H - v.shape[0]) // 2
    img[oy:oy + v.shape[0], ox:ox + v.shape[1]] = v
    return img, (ox, oy, s)


def view_map(frame):
    """(ox, oy, scale) of the camera view on the dashboard (as place() and dash.Dash.render)."""
    s = min(D.MAIN_W / frame.shape[1], D.MAIN_H / frame.shape[0])
    w, h = max(1, round(frame.shape[1] * s)), max(1, round(frame.shape[0] * s))
    return (D.MAIN_W - w) // 2, (D.MAIN_H - h) // 2, s


def view_to_cam(b, mapping):
    ox, oy, s = mapping
    return np.array([(b[0] - ox) / s, (b[1] - oy) / s, b[2] / s, b[3] / s])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["zsad", "s3x8"], default="zsad")
    ap.add_argument("--crop", choices=["fpga", "server"], default="fpga")
    ap.add_argument("--source", choices=["otb", "webcam"], default="otb")
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--init-box", default=None, help="webcam: x,y,w,h in camera pixels")
    ap.add_argument("--cam-size", default="640x480", help="webcam resolution (MJPG)")
    ap.add_argument("--cam-exposure", type=int, default=None,
                    help="webcam manual exposure in 100 us units (<= 330 keeps 30 fps); default: auto")
    ap.add_argument("--cam-gain", type=int, default=None, help="webcam gain (0..63 on the icSpring camera)")
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--loop", action="store_true", help="OTB: replay the sequence forever")
    ap.add_argument("--ip", default="10.8.100.230", help="board IP")
    ap.add_argument("--bind", default="100.76.229.14", help="web page address (Tailscale)")
    ap.add_argument("--http-port", type=int, default=8090)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-board", action="store_true",
                    help="no board: the host model tracks (to test sources and the page); labelled on screen")
    ap.add_argument("--workers", type=int, default=4, help="processes for the background FPGA = model check")
    a = ap.parse_args()

    global NOTE
    model = make_model(a.tracker)
    M = model.MARGIN
    tname = {"zsad": "ZSAD 16x16", "s3x8": "S-3x8 int8 CNN"}[a.tracker]
    NOTE = (f"Scaling on the server; {model.ROI}x{model.ROI} ROI crop in the FPGA; tracking on the DE2-115 ({tname})."
            if a.crop == "fpga" else
            f"Scaling + {model.ROI}x{model.ROI} ROI crop on the server; tracking on the DE2-115 ({tname}).")
    if a.no_board:
        NOTE = f"No board connected: scaling, {model.ROI}x{model.ROI} ROI crop and tracking ({tname}) in the host model."
    src = Source(a)
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results",
                                f"demo3_{a.tracker}_{'noboard' if a.no_board else a.crop}_{src.name}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    st = Stream()
    srv = ThreadingHTTPServer((a.bind, a.http_port), make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"view: http://{a.bind}:{a.http_port}/   output: {out}", flush=True)

    link = None if a.no_board else BoardLink3(a.ip)
    if link is not None:
        link.drain()
    checker = None if link is None else D.Checker(a.tracker, a.workers)
    dash = D.Dash(model, tname, NOTE)

    # ---- first frame and box (camera pixels)
    f0, k0 = src.next()
    if f0 is None:
        raise SystemExit("no frames")
    if a.source == "otb":
        box = src.gt_orig[0].copy()
    elif a.init_box:
        box = np.array([float(v) for v in a.init_box.split(",")])
    else:
        st.need_box = True
        while st.box_view is None:                 # live preview until a box is drawn on the page
            canvas, mapping = place(f0)
            D.text(canvas, PREVIEW_HINT, 20, 40, D.YELLOW, 0.9, 2)
            st.put(canvas)
            f, _ = src.next()
            if f is not None:
                f0 = f
            time.sleep(0.03)
        box = view_to_cam(st.box_view, mapping)
        st.box_view, st.need_box = None, False

    sc = {"s": 1.0}

    def scaled(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        s = sc["s"]
        return cv2.resize(g, (max(1, round(g.shape[1] * s)), max(1, round(g.shape[0] * s))),
                          interpolation=cv2.INTER_AREA)

    def init_track(frame, b):
        sc["s"] = a.target_px / np.sqrt(b[2] * b[3])
        fs = scaled(frame)
        t = Track(model, fs, ((b[0] + b[2] / 2) * sc["s"], (b[1] + b[3] / 2) * sc["s"]))
        if link is not None and not (link.send_template(t.tmpl) and link.set_position(t.tx, t.ty)):
            raise SystemExit(f"board did not acknowledge template/position (is the p3 {a.tracker} bitstream loaded?)")
        patch = pad_to(fs, model.ROI)[t.ty:t.ty + WIN, t.tx:t.tx + WIN].copy()
        tf = model.template_features()
        return t, patch, (None if tf is None else tf.copy())

    tr, patch, tfeat = init_track(f0, box)

    vw = None
    if not a.no_video:
        vw = cv2.VideoWriter(os.path.join(out, "demo.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (D.W, D.H))

    rows, preds = {}, []
    n = 0
    t_prev = time.perf_counter()
    fps_s = 0.0
    fid = 1
    period = 1.0 / a.fps
    t_next = time.perf_counter()
    last_map = None

    def take_checks(cs):
        for c in cs:
            dash.add_check(c)
            r = rows.get(c["n"])
            if r is not None:
                r.update(model_x=c["mx"], model_y=c["my"], model_score=c["mz"], model_good=int(c["mgood"]),
                         agree="" if c["ok"] is None else int(c["ok"]))
    try:
        while True:
            f, k = src.next()
            if f is None:
                break
            if a.source == "otb" and k == 0:       # sequence restart (loop): re-init from GT
                tr, patch, tfeat = init_track(f, src.gt_orig[0])
                continue
            if st.box_view is not None:            # a new box drawn on the page: re-select the target
                box = view_to_cam(st.box_view, last_map)
                st.box_view = None
                tr, patch, tfeat = init_track(f, box)
            fs = scaled(f)
            fp, (rx, ry), crop = tr.crop(fs)
            prev = (tr.tx, tr.ty)
            n += 1
            res = None
            f_us = rtt = rx_us = float("nan")
            if link is not None:
                res, t0, t1 = link.track(fid, fp if a.crop == "fpga" else crop)
                fid += 1
                tracked = res is not None and bool(res["flags"] & F_TRACKED) and bool(res["flags"] & F_COMPLETE)
                good = tracked and bool(res["flags"] & F_GOOD)
                score = res["score"] if tracked else None
                best = None
                if good:                           # follow the FPGA's own result
                    if a.crop == "fpga":
                        tr.tx, tr.ty = res["x"], res["y"]
                        best = (res["x"] - rx, res["y"] - ry)
                    else:
                        tr.update((rx, ry), res["x"] - M, res["y"] - M, True)
                        best = (res["x"], res["y"])
                if res is not None:
                    f_us = ((res["t_result"] - res["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6
                    rx_us = ((res["t_rx_end"] - res["t_rx_start"]) & 0xFFFFFFFF) / FCLK * 1e6
                    rtt = (res["t_recv_ns"] - t1) / 1e3
                checker.submit(dict(n=n, tmpl=tr.tmpl, roi=crop, origin=(rx, ry), prev_pos=prev, crop=a.crop,
                                    res=res, margin=M))
                take_checks(checker.poll())
            else:                                  # no board: the model tracks (labelled on screen)
                mx, my, mz, mgood, extra = model.inspect(crop)
                tr.update((rx, ry), mx, my, mgood)
                good, score, best = mgood, mz, (mx + M, my + M)
                c = dict(n=n, ok=None, mx=mx, my=my, mz=mz, mgood=mgood, map=extra["map"])
                if "feat" in extra:
                    c["feat"] = extra["feat"]
                dash.add_check(c)
            cx, cy = tr.center()
            s = sc["s"]
            now = time.perf_counter()
            fps_i = 1.0 / max(1e-6, now - t_prev)
            fps_s = 0.9 * fps_s + 0.1 * fps_i if fps_s else fps_i
            t_prev = now
            for key, val in (("score", score), ("fpga_us", f_us), ("rtt_us", rtt), ("fps", fps_s)):
                dash.h[key].append(val)
            d = dict(frame=f, n=n, k=k, name=src.name, mode=a.crop, board=link is not None, res=res,
                     gt=src.gt_orig[k] if (src.gt_orig is not None and k is not None) else None,
                     box=(cx / s - box[2] / 2, cy / s - box[3] / 2, box[2], box[3]),
                     roi_box=(rx / s, ry / s, model.ROI / s, model.ROI / s),
                     fp=fp if a.crop == "fpga" else pad_to(fs, model.ROI), roi=crop, origin=(rx, ry), best=best,
                     score=score, good=good, f_us=f_us, rtt_us=rtt, rx_us=rx_us, fps=fps_s,
                     tmpl_patch=patch, tmpl_feat=tfeat, lag=0 if checker is None else checker.lag())
            img = dash.render(d)
            last_map = view_map(f)
            st.put(img)
            if vw is not None:
                vw.write(img)
            rows[n] = dict(n=n, frame=k, roi_x=rx, roi_y=ry,
                           fpga_x=None if res is None else res["x"], fpga_y=None if res is None else res["y"],
                           fpga_score=score, fpga_good=int(good), model_x=None, model_y=None, model_score=None,
                           model_good=None, agree="", fpga_compute_us=round(f_us, 2), rtt_us=round(rtt, 1),
                           cx_orig=round(cx / s, 1), cy_orig=round(cy / s, 1))
            if link is None:
                rows[n].update(model_x=best[0] - M, model_y=best[1] - M, model_score=score, model_good=int(good))
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
        if checker is not None:
            take_checks(checker.poll(wait=True))
            checker.close()

    cols = ["n", "frame", "roi_x", "roi_y", "fpga_x", "fpga_y", "fpga_score", "fpga_good", "model_x", "model_y",
            "model_score", "model_good", "agree", "fpga_compute_us", "rtt_us", "cx_orig", "cy_orig"]
    with open(os.path.join(out, "frames.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader()
        for i in sorted(rows):
            w.writerow(rows[i])
    fu = np.array([r["fpga_compute_us"] for r in rows.values()] or [np.nan], float)
    rt = np.array([r["rtt_us"] for r in rows.values()] or [np.nan], float)
    fpsv = np.array([v for v in dash.h["fps"]] or [np.nan], float)
    agree_txt = ("n/a (no board: host model only)" if a.no_board else
                 f"{dash.checked - dash.mismatch}/{dash.checked} checked ({n} frames)"
                 + ("" if dash.mismatch == 0 else f", first mismatch at frame {dash.first_bad}"))
    lines = [f"# P3 demo run: {a.tracker}, {'no board' if a.no_board else 'crop ' + a.crop}, {src.name}", "",
             f"command: `python3 demo.py {' '.join(f'--{k_.replace(chr(95), chr(45))} {v}' for k_, v in vars(a).items() if v not in (None, False))}`", "",
             "| metric | value |", "|---|---|",
             f"| frames tracked | {n} |",
             f"| FPGA = model | {agree_txt} |",
             f"| rejected matches (hold) | {sum(1 for r in rows.values() if r['fpga_good'] == 0)} |",
             f"| display rate, last {len(dash.h['fps'])} frames (fps) | p50 {np.nanpercentile(fpsv, 50):.1f} |"]
    if not a.no_board:
        lines += [f"| FPGA compute after the last row (us) | p50 {np.nanpercentile(fu, 50):.1f}, max {np.nanmax(fu):.1f} |",
                  f"| network round trip, last row sent -> result (us) | p50 {np.nanpercentile(rt, 50):.0f}, p99 {np.nanpercentile(rt, 99):.0f}, max {np.nanmax(rt):.0f} |"]
    if a.source == "otb" and preds and not a.loop:
        k_all = len(src.d["frames"])
        pc = np.full((k_all, 2), np.nan)
        g0 = src.d["gt"][0]
        pc[0] = (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2)
        for k_, cx, cy in preds:
            pc[k_] = (cx, cy)
        gt_c = src.d["gt"][:, :2] + src.d["gt"][:, 2:] / 2
        m_ = src.otb.metrics.compute(pc, gt_c, sc["s"])
        lines.append(f"| P@20 (information only) | {m_['prec20']:.1f} |")
        lines.append(f"| success AUC, fixed box size (information only) | {src.otb.iou_auc(pc, src.gt_orig, sc['s']):.1f} |")
    lines += ["", NOTE]
    open(os.path.join(out, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    srv.shutdown()


if __name__ == "__main__":
    main()
