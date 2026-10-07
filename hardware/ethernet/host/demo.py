#!/usr/bin/env python3
"""P3 demo: tracking on the DE2-115 over Ethernet (hardware in the loop), either tracker build, with server
corrections from OSTrack and a control panel on the web page.

The server scales each frame so the target is ~16 px. With crop "fpga" it sends the whole scaled frame
(like a camera) and the FPGA crops the ROI around its own position; with crop "server" it sends only the
ROI. The board runs the tracker core of the loaded bitstream and returns the new position. The bit-exact
host model re-computes every frame in the background ("FPGA = model").

Server corrections (corrections.py, the K3 rule of the locked system): every N frames the FPGA position
and the frame go to OSTrack-256 on the GPU (ost-gated tau 0.6); the answer is applied L frames later as a
position offset plus (mode pos+tmpl) a new template cut from the request frame.

The page (http://<bind>:<port>/) shows the 1920x1080 dashboard and a control panel: source (OTB sequence
or webcam), restart / pause / loop / reset to GT, fps, tracker and crop mode (switching the tracker
reprograms the board over JTAG, ~10 s), and the corrections (on/off, N, L, mode). Changes are logged in
controls.csv. Each run of a source is a session with its own folder (frames.csv, corrections.csv,
summary.md, demo.mp4).

  python3 demo.py --tracker s3x8 --crop fpga --source otb --seq Walking
  python3 demo.py --tracker s3x8 --source webcam --cam 0           # draw the box on the web page
  python3 demo.py --tracker zsad --no-board                         # no board: host model only (labelled)
  python3 demo.py ... --once                                        # exit after the first session (scripts)
"""
import argparse, csv, json, os, signal, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from board_link3 import BoardLink3, FCLK, F_COMPLETE, F_GOOD, F_TRACKED
import dash as D
from corrections import Heavy, Corrections, TAU
from trackers import make_model, pad_to, Track, WIN

HERE = os.path.dirname(os.path.abspath(__file__))
ETH_DIR = os.path.dirname(HERE)
DEMO_SEQS = ["Walking", "Jumping", "BlurOwl", "Bolt"]
TNAME = {"zsad": "ZSAD 16x16", "s3x8": "S-3x8 int8 CNN"}
RESTART_KEYS = ("source", "seq", "tracker", "crop", "cam")
LIVE_KEYS = ("fps", "loop", "paused", "corr_on", "corr_N", "corr_L", "corr_mode")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>FPGA tracking demo</title>
<style>body{margin:0;background:#000;color:#ddd;font:14px sans-serif;overflow:hidden}#w{position:relative;display:inline-block}
img{display:block}#sel{position:absolute;border:2px dashed #0f0;display:none;pointer-events:none}
#h{position:absolute;left:10px;bottom:4px;margin:0;color:#ff0;font-size:16px;text-shadow:0 0 3px #000}
#cp{position:fixed;left:8px;top:8px;background:rgba(20,20,28,.88);border:1px solid #556;border-radius:6px;padding:8px 10px;
 font-size:13px;line-height:1.9;max-width:470px;z-index:5}#cp b{color:#ff0}#cp .row{white-space:nowrap}
#cp input[type=number]{width:52px}#cp select,#cp input,#cp button{font-size:13px}#cp .hint{color:#9ab;font-size:12px;line-height:1.3;white-space:normal}
#tg{position:fixed;left:8px;top:8px;z-index:6;display:none}#st{color:#8f8;white-space:normal;line-height:1.3}</style></head><body>
<button id="tg">controls</button>
<div id="cp"><div class="row"><b>Controls</b> &nbsp;<button id="hide">hide</button> <span class="hint">(key: c)</span></div>
<div class="row">source <select id="source"><option value="otb">OTB-100</option><option value="webcam">webcam</option></select>
 <input id="seq" list="seqs" size="12"><datalist id="seqs"></datalist>
 tracker <select id="tracker"><option value="s3x8">S-3x8</option><option value="zsad">ZSAD</option></select>
 crop <select id="crop"><option value="fpga">FPGA</option><option value="server">server</option></select></div>
<div class="row"><button id="apply">start / switch</button> <button data-act="restart">restart</button>
 <button data-act="pause" id="pause">pause</button> <button data-act="reset_gt">reset to GT</button>
 <label><input type="checkbox" id="loop"> loop</label></div>
<div class="row">fps <input type="range" id="fps" min="1" max="60" style="width:140px;vertical-align:middle"> <span id="fpsv"></span></div>
<div class="row"><b>Server corrections</b> (OSTrack-256, K3) <label><input type="checkbox" id="corr_on"> on</label></div>
<div class="row">every N <input type="number" id="corr_N" min="1" max="1000"> frames, delay L <input type="number" id="corr_L" min="0" max="300"> frames
 <span id="lms"></span></div>
<div class="row">correction <select id="corr_mode"><option value="pos+tmpl">position + template</option><option value="pos">position only</option></select></div>
<div id="st"></div>
<div class="hint">Draw a box on the camera view to (re)select the target. Switching the tracker reprograms the FPGA (~10 s).</div></div>
<div id="w"><img id="v" src="/stream"><div id="sel"></div><p id="h"></p></div><script>
const v=document.getElementById('v'),s=document.getElementById('sel'),h=document.getElementById('h'),cp=document.getElementById('cp'),tg=document.getElementById('tg');
const $=id=>document.getElementById(id);let st=null,S={},edit=0;
function fitImg(){if(!v.naturalWidth)return;const k=Math.min(innerWidth/v.naturalWidth,innerHeight/v.naturalHeight);
 v.style.width=Math.floor(v.naturalWidth*k)+'px';}
setInterval(fitImg,500);window.addEventListener('resize',fitImg);
function show(on){cp.style.display=on?'block':'none';tg.style.display=on?'none':'block';}
$('hide').onclick=()=>show(false);tg.onclick=()=>show(true);
document.addEventListener('keydown',e=>{if(e.key==='c'&&!['INPUT','SELECT'].includes(document.activeElement.tagName))show(cp.style.display==='none');});
function ctl(q){edit=Date.now();return fetch('/control?'+new URLSearchParams(q)).then(r=>r.json()).then(fill);}
for(const id of ['fps','corr_N','corr_L','corr_mode','corr_on','loop'])
 $(id).addEventListener('change',e=>{const el=e.target;ctl({[id]:el.type==='checkbox'?(el.checked?1:0):el.value});});
$('fps').addEventListener('input',e=>{$('fpsv').textContent=e.target.value;});
document.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>ctl({action:b.dataset.act}));
$('apply').onclick=()=>ctl({source:$('source').value,seq:$('seq').value,tracker:$('tracker').value,crop:$('crop').value,action:'restart'});
let boot=null;v.onerror=()=>setTimeout(()=>{v.src='/stream?'+Date.now();},1000);
function fill(j){if(boot!==null&&j.boot!==boot)v.src='/stream?'+Date.now();boot=j.boot;S=j;if(Date.now()-edit>1500){for(const k of ['source','tracker','crop','corr_mode'])if(document.activeElement!==$(k))$(k).value=j[k];
 if(document.activeElement!==$('seq'))$('seq').value=j.seq;
 for(const k of ['fps','corr_N','corr_L'])if(document.activeElement!==$(k))$(k).value=j[k];
 $('corr_on').checked=!!j.corr_on;$('loop').checked=!!j.loop;}
 $('fpsv').textContent=$('fps').value;$('pause').textContent=j.paused?'resume':'pause';
 $('lms').textContent='(= '+Math.round(1000*j.corr_L/j.fps)+' ms at '+j.fps+' fps)';
 $('st').textContent=j.status;h.textContent=j.need_box?'Drag a box around the target to start tracking.':
 (j.source==='webcam'?'Drag a new box on the camera view to re-select the target.':'');
 const dl=$('seqs');if(!dl.childElementCount&&j.seqs)j.seqs.forEach(q=>{const o=document.createElement('option');o.value=q;dl.appendChild(o);});}
setInterval(()=>fetch('/state').then(r=>r.json()).then(fill),700);
v.addEventListener('mousedown',e=>{const r=v.getBoundingClientRect();st=[e.clientX-r.left,e.clientY-r.top];e.preventDefault();});
v.addEventListener('mousemove',e=>{if(!st)return;const r=v.getBoundingClientRect();const x=e.clientX-r.left,y=e.clientY-r.top;
 s.style.display='block';s.style.left=Math.min(x,st[0])+'px';s.style.top=Math.min(y,st[1])+'px';
 s.style.width=Math.abs(x-st[0])+'px';s.style.height=Math.abs(y-st[1])+'px';});
v.addEventListener('mouseup',e=>{if(!st)return;const r=v.getBoundingClientRect();const x=e.clientX-r.left,y=e.clientY-r.top;
 const k=v.naturalWidth/r.width;const b=[Math.min(x,st[0])*k,Math.min(y,st[1])*k,Math.abs(x-st[0])*k,Math.abs(y-st[1])*k];
 st=null;s.style.display='none';if(b[2]>4&&b[3]>4)fetch('/init?box='+b.map(Math.round).join(','));});
</script></body></html>"""


class Control:
    """Settings shared by the web page and the demo loop (+ the latest JPEG for the MJPEG clients)."""

    def __init__(self, a, log_path, seqs):
        self.lock = threading.Lock()
        self.cond = threading.Condition()
        self.jpg, self.seq_no = None, 0
        self.box_view, self.need_box = None, False
        self.set = dict(source=a.source, seq=a.seq, cam=a.cam, tracker=a.tracker, crop=a.crop, fps=a.fps, loop=int(a.loop),
                        paused=0, corr_on=int(not a.no_corrections), corr_N=a.corr_n, corr_L=a.corr_l, corr_mode=a.corr_mode)
        self.restart = False
        self.actions = []
        self.status = "starting"
        self.boot = time.strftime("%H%M%S") + str(os.getpid())     # the page reconnects the stream when it changes
        self.seqs = seqs
        self.log = open(log_path, "a", newline="")
        self.logw = csv.writer(self.log)
        if self.log.tell() == 0:
            self.logw.writerow(["time", "session", "frame", "key", "value"])
        self.where = (0, 0)

    def put(self, img):
        ok, b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self.cond:
                self.jpg, self.seq_no = b.tobytes(), self.seq_no + 1
                self.cond.notify_all()

    def state(self):
        with self.lock:
            return dict(self.set, need_box=self.need_box, status=self.status, seqs=self.seqs, boot=self.boot)

    def apply(self, q):
        """q: dict from the page. Restart keys take effect at the next session start (action restart)."""
        with self.lock:
            for k, v in q.items():
                if k == "action":
                    if v == "restart":
                        self.restart = True
                    elif v == "pause":
                        self.set["paused"] = 1 - self.set["paused"]
                    else:
                        self.actions.append(v)
                elif k in self.set:
                    try:
                        if k in ("fps",):
                            v = float(min(120.0, max(0.5, float(v))))
                        elif k in ("corr_N",):
                            v = int(min(10000, max(1, int(float(v)))))
                        elif k in ("corr_L", "cam"):
                            v = int(min(10000, max(0, int(float(v)))))
                        elif k in ("loop", "paused", "corr_on"):
                            v = int(bool(int(float(v))))
                        elif k == "source" and v not in ("otb", "webcam"):
                            continue
                        elif k == "tracker" and v not in TNAME:
                            continue
                        elif k == "crop" and v not in ("fpga", "server"):
                            continue
                        elif k == "corr_mode" and v not in ("pos+tmpl", "pos"):
                            continue
                        elif k == "seq" and v not in self.seqs:
                            continue
                    except ValueError:
                        continue
                    self.set[k] = v
                else:
                    continue
                self.logw.writerow([time.strftime("%H:%M:%S"), self.where[0], self.where[1], k, v])
            self.log.flush()

    def take_actions(self):
        with self.lock:
            a, self.actions = self.actions, []
            return a


def make_handler(ctl):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, d):
            b = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

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
                self._json(ctl.state())
            elif u.path == "/control":
                ctl.apply({k: v[0] for k, v in parse_qs(u.query).items()})
                self._json(ctl.state())
            elif u.path == "/init":
                try:
                    ctl.box_view = [float(v) for v in parse_qs(u.query)["box"][0].split(",")][:4]
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
                        with ctl.cond:
                            ctl.cond.wait_for(lambda: ctl.seq_no != last, timeout=5)
                            jpg, last = ctl.jpg, ctl.seq_no
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
    """OTB-100 sequence (frames read on demand) or a V4L2 webcam."""

    def __init__(self, a, kind, seq, cam):
        self.kind = kind
        if kind == "otb":
            import otb_src
            self.otb = otb_src
            self.d = otb_src.meta(seq, a.target_px)
            self.i, self.name, self.gt_orig = 0, seq, self.d["gt_orig"]
            self.n_frames = len(self.d["paths"])
        else:
            self.cap = cv2.VideoCapture(cam, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                raise RuntimeError(f"cannot open webcam {cam} (is the user in the video group?)")
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            w, h = (int(v) for v in a.cam_size.split("x"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)              # newest frame, no backlog
            # exposure: auto (aperture priority) can halve the frame rate in a dim room; a manual
            # exposure below 33 ms keeps 30 fps (darker image: raise the gain)
            ctrls = (f"auto_exposure=1,exposure_time_absolute={a.cam_exposure}" if a.cam_exposure is not None
                     else "auto_exposure=3")
            if a.cam_gain is not None:
                ctrls += f",gain={a.cam_gain}"
            r = subprocess.run(["v4l2-ctl", "-d", f"/dev/video{cam}", "--set-ctrl", ctrls], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"warning: camera controls not set ({ctrls}): {r.stderr.strip()}", flush=True)
            self.name, self.gt_orig = f"webcam{cam}", None

    def next(self, loop):
        """-> (color frame in original resolution, frame index) or (None, None) at the end."""
        if self.kind == "otb":
            if self.i >= self.n_frames:
                if not loop:
                    return None, None
                self.i = 0
            k = self.i
            self.i += 1
            return cv2.imread(self.d["paths"][k], cv2.IMREAD_COLOR), k
        ok, f = self.cap.read()
        return (f, None) if ok else (None, None)

    def close(self):
        if self.kind == "webcam":
            self.cap.release()


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


def message(ctl, lines, col=D.YELLOW):
    img = np.zeros((D.H, D.W, 3), np.uint8)
    for i, t in enumerate(lines):
        D.text(img, t, 520, 300 + 44 * i, col if i == 0 else D.WHITE, 0.9 if i == 0 else 0.7, 2 if i == 0 else 1)
    ctl.put(img)
    return img


class Demo:
    def __init__(self, a):
        self.a = a
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.out = a.out or os.path.join(ETH_DIR, "results", f"demo3_{stamp}")
        os.makedirs(self.out, exist_ok=True)
        import otb_src
        seqs = DEMO_SEQS + [t for t in otb_src.targets() if t not in DEMO_SEQS]
        self.ctl = Control(a, os.path.join(self.out, "controls.csv"), seqs)
        self.srv = ThreadingHTTPServer((a.bind, a.http_port), make_handler(self.ctl))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        print(f"view: http://{a.bind}:{a.http_port}/   output: {self.out}", flush=True)
        self.link = None if a.no_board else BoardLink3(a.ip)
        self.loaded = a.tracker                 # bitstream assumed on the board (--program to load it)
        if self.link is not None and a.program:
            self.program(a.tracker)
        self.heavy = None if a.no_corrections_server else Heavy(os.path.join(self.out, "ostrack_server.log"))
        self.session_no = 0

    # ---------------------------------------------------------------- helpers
    def program(self, tracker):
        message(self.ctl, [f"Programming the FPGA with the {TNAME[tracker]} bitstream ...", "(JTAG, about 10 s)"])
        self.ctl.status = f"programming the FPGA ({tracker}) ..."
        r = subprocess.run(["make", "--no-print-directory", f"program-{tracker}"], cwd=ETH_DIR, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"make program-{tracker} failed: {(r.stderr or r.stdout).strip()[-300:]}")
        self.loaded = tracker
        time.sleep(3)                           # link up again after configuration
        self.link.drain(0.2)

    def wait_for_change(self, lines):
        """Show a message until the page asks for a (re)start."""
        self.ctl.status = " ".join(lines)
        while not self.ctl.restart:
            message(self.ctl, lines)
            time.sleep(0.3)

    # ---------------------------------------------------------------- main loop
    def run(self):
        try:
            while True:
                self.ctl.restart = False
                reason = "error"
                try:
                    reason = self.session()
                except RuntimeError as e:
                    print(f"session error: {e}", flush=True)
                    if self.a.once:
                        break
                    self.wait_for_change(["Error: " + str(e)[:110], "Change the settings and press 'start / switch'."])
                    continue
                if self.a.once or reason == "quit":
                    break
                if reason == "end":
                    self.wait_for_change(["End of the sequence.", "Press 'restart', tick 'loop' or choose another source."])
        except KeyboardInterrupt:
            pass
        finally:
            if self.heavy is not None:
                self.heavy.close()
            self.srv.shutdown()

    def session(self):
        a, ctl, link = self.a, self.ctl, self.link
        S = ctl.state()
        self.session_no += 1
        sid = self.session_no
        tracker, crop = S["tracker"], S["crop"]
        if link is not None and tracker != self.loaded:
            self.program(tracker)
        model = make_model(tracker)
        M = model.MARGIN
        tname = TNAME[tracker]
        note = (f"Scaling on the server; {model.ROI}x{model.ROI} ROI crop in the FPGA; tracking on the DE2-115 ({tname})."
                if crop == "fpga" else
                f"Scaling + {model.ROI}x{model.ROI} ROI crop on the server; tracking on the DE2-115 ({tname}).")
        if link is None:
            note = f"No board connected: scaling, {model.ROI}x{model.ROI} ROI crop and tracking ({tname}) in the host model."
        src = Source(a, S["source"], S["seq"], S["cam"])
        sdir = os.path.join(self.out, f"{sid:02d}_{tracker}_{'noboard' if link is None else crop}_{src.name}")
        os.makedirs(sdir, exist_ok=True)
        if link is not None:
            link.drain()
        checker = None if link is None else D.Checker(tracker, a.workers)
        dash = D.Dash(model, tname, note)
        corr = Corrections(self.heavy)
        ctl.status = f"session {sid}: {tracker}, crop {crop}, {src.name}"
        ctl.where = (sid, 0)

        # ---- first frame and box (camera pixels)
        f0, k0 = src.next(False)
        if f0 is None:
            raise RuntimeError(f"no frames from {src.name}")
        mapping = view_map(f0)
        if src.kind == "otb":
            box = src.gt_orig[0].copy()
        elif a.init_box and sid == 1:
            box = np.array([float(v) for v in a.init_box.split(",")])
        else:
            ctl.need_box = True
            while ctl.box_view is None:            # live preview until a box is drawn on the page
                if ctl.restart:
                    ctl.need_box = False
                    src.close()
                    return "restart"
                canvas, mapping = place(f0)
                D.text(canvas, "Drag a box around the target on this page", 20, 40, D.YELLOW, 0.9, 2)
                ctl.put(canvas)
                f, _ = src.next(False)
                if f is not None:
                    f0 = f
                time.sleep(0.03)
            box = view_to_cam(ctl.box_view, mapping)
            ctl.box_view, ctl.need_box = None, False

        sc = {"s": 1.0}

        def scaled(img):
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            s = sc["s"]
            return cv2.resize(g, (max(1, round(g.shape[1] * s)), max(1, round(g.shape[0] * s))),
                              interpolation=cv2.INTER_AREA)

        st = dict(prev=None, note="")             # previous template patch (display)

        def init_track(frame, b):
            sc["s"] = a.target_px / np.sqrt(b[2] * b[3])
            fs = scaled(frame)
            t = Track(model, fs, ((b[0] + b[2] / 2) * sc["s"], (b[1] + b[3] / 2) * sc["s"]))
            if link is not None and not (link.send_template(t.tmpl) and link.set_position(t.tx, t.ty)):
                raise RuntimeError(f"board did not acknowledge template/position (is the p3 {tracker} bitstream loaded?)")
            patch = pad_to(fs, model.ROI)[t.ty:t.ty + WIN, t.tx:t.tx + WIN].copy()
            tf = model.template_features()
            corr.reset(frame, b)
            st.update(prev=None, note="")
            return t, patch, (None if tf is None else tf.copy())

        tr, patch, tfeat = init_track(f0, box)

        vw = None
        if not a.no_video:
            vw = cv2.VideoWriter(os.path.join(sdir, "demo.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30, (D.W, D.H))

        rows, preds = {}, []
        n = 0
        t_prev = time.perf_counter()
        fps_s = 0.0
        fid = 1
        t_next = time.perf_counter()
        last_map = mapping
        banners = {}                               # kind -> (text, colour, until frame n)
        heavy_show = None                          # (box original px, until n)
        reason = "end"

        def take_checks(cs):
            for c in cs:
                dash.add_check(c)
                r = rows.get(c["n"])
                if r is not None:
                    r.update(model_x=c["mx"], model_y=c["my"], model_score=c["mz"], model_good=int(c["mgood"]),
                             agree="" if c["ok"] is None else int(c["ok"]))
        try:
            while True:
                S = ctl.state()
                corr.on, corr.N, corr.L, corr.mode = bool(S["corr_on"]), S["corr_N"], S["corr_L"], S["corr_mode"]
                if ctl.restart:
                    reason = "restart"
                    break
                if S["paused"]:
                    time.sleep(0.05)
                    t_next = time.perf_counter()
                    continue
                f, k = src.next(bool(S["loop"]))
                if f is None:
                    break
                acts = ctl.take_actions()
                if src.kind == "otb" and k == 0:       # sequence restart (loop): re-init from GT
                    tr, patch, tfeat = init_track(f, src.gt_orig[0])
                    continue
                if "reset_gt" in acts and src.kind == "otb" and np.isfinite(src.gt_orig[k]).all():
                    tr, patch, tfeat = init_track(f, src.gt_orig[k])
                    banners["init"] = (f"reset to ground truth at frame {k}", D.YELLOW, n + 30)
                if ctl.box_view is not None:            # a new box drawn on the page: re-select the target
                    box = view_to_cam(ctl.box_view, last_map)
                    ctl.box_view = None
                    tr, patch, tfeat = init_track(f, box)
                    banners["init"] = ("new target selected", D.YELLOW, n + 30)
                fs = scaled(f)
                fp, (rx, ry), crop_img = tr.crop(fs)
                prev = (tr.tx, tr.ty)
                n += 1
                ctl.where = (sid, n)
                res = None
                f_us = rtt = rx_us = float("nan")
                if link is not None:
                    res, t0, t1 = link.track(fid, fp if crop == "fpga" else crop_img)
                    fid += 1
                    tracked = res is not None and bool(res["flags"] & F_TRACKED) and bool(res["flags"] & F_COMPLETE)
                    good = tracked and bool(res["flags"] & F_GOOD)
                    score = res["score"] if tracked else None
                    best = None
                    if good:                           # follow the FPGA's own result
                        if crop == "fpga":
                            tr.tx, tr.ty = res["x"], res["y"]
                            best = (res["x"] - rx, res["y"] - ry)
                        else:
                            tr.update((rx, ry), res["x"] - M, res["y"] - M, True)
                            best = (res["x"], res["y"])
                    if res is not None:
                        f_us = ((res["t_result"] - res["t_rx_end"]) & 0xFFFFFFFF) / FCLK * 1e6
                        rx_us = ((res["t_rx_end"] - res["t_rx_start"]) & 0xFFFFFFFF) / FCLK * 1e6
                        rtt = (res["t_recv_ns"] - t1) / 1e3
                    checker.submit(dict(n=n, tmpl=tr.tmpl, roi=crop_img, origin=(rx, ry), prev_pos=prev, crop=crop,
                                        res=res, margin=M))
                    take_checks(checker.poll())
                else:                                  # no board: the model tracks (labelled on screen)
                    mx, my, mz, mgood, extra = model.inspect(crop_img)
                    tr.update((rx, ry), mx, my, mgood)
                    good, score, best = mgood, mz, (mx + M, my + M)
                    c = dict(n=n, ok=None, mx=mx, my=my, mz=mz, mgood=mgood, map=extra["map"])
                    if "feat" in extra:
                        c["feat"] = extra["feat"]
                    dash.add_check(c)

                # ---- server corrections (K3): apply the answers that are due, then maybe send a request
                app_now, drift_now = False, None
                for r in corr.due(n):
                    hs = corr.heavy_pos(r)
                    before = np.array([tr.tx, tr.ty])
                    Hf, Wf = fp.shape
                    p = np.clip(before + hs - np.array(r["edge"]), [0, 0], [Wf - WIN, Hf - WIN]).astype(int)
                    use_t = r["mode"] == "pos+tmpl"
                    newt = model.template(r["fp"], int(hs[0]), int(hs[1])) if use_t else None
                    pos_ok = t_ok = True
                    if link is not None:            # host state changes only with what the board acknowledged
                        pos_ok = any(link.set_position(int(p[0]), int(p[1])) for _ in range(3))
                        t_ok = (not use_t) or any(link.send_template(newt) for _ in range(3))
                        if not (pos_ok and t_ok):
                            msg = (f"correction #{r['rid']}: board did not acknowledge the "
                                   f"{'position' if not pos_ok else 'template'} (3 tries)")
                            print("warning: " + msg, flush=True)
                            banners["err"] = (msg, D.RED, n + 90)
                            corr.failed += 1
                    if not pos_ok:
                        p = before
                    use_t = use_t and t_ok
                    tr.tx, tr.ty = int(p[0]), int(p[1])
                    if use_t:
                        tr.tmpl = newt
                        model.set_template(newt)
                        st["prev"] = patch
                        patch = r["fp"][hs[1]:hs[1] + WIN, hs[0]:hs[0] + WIN].copy()
                        tf = model.template_features()
                        tfeat = None if tf is None else tf.copy()
                        st["note"] = f"(new, from frame {r['s']})"
                    rec = corr.record(r, n, hs, before, p, use_t)
                    app_now, drift_now = True, rec["drift_px"]
                    late = f", {rec['late']} late" if rec["late"] > 0 else ""
                    banners["app"] = (f"correction #{rec['rid']} from frame {rec['s']} applied at {n}: "
                                      f"moved ({int(p[0] - before[0]):+d},{int(p[1] - before[1]):+d}) px"
                                      f"{' + new template' if use_t else ''}{late}", D.MAGENTA, n + 30)
                    heavy_show = (rec["box_orig"], n + 30)
                rid = corr.request(n, f, fp, (tr.tx, tr.ty), sc["s"])
                if rid is not None:
                    banners["req"] = (f"OSTrack request #{rid}: frame {n} + FPGA position sent", D.SKY, n + 20)

                cx, cy = tr.center()
                s = sc["s"]
                now = time.perf_counter()
                fps_i = 1.0 / max(1e-6, now - t_prev)
                fps_s = 0.9 * fps_s + 0.1 * fps_i if fps_s else fps_i
                t_prev = now
                for key, val in (("score", score), ("fpga_us", f_us), ("rtt_us", rtt), ("fps", fps_s),
                                 ("req", rid is not None), ("app", app_now), ("drift", drift_now)):
                    dash.h[key].append(val)
                if not corr.available():
                    cline = (["server corrections: OSTrack server not available" + (f" ({self.heavy.error})" if self.heavy and self.heavy.error else
                              " (loading ...)" if self.heavy else " (--no-corrections-server)")], D.GREY)
                elif not corr.on:
                    cline = (["server corrections: off"], D.GREY)
                else:
                    last = corr.done[-1] if corr.done else None
                    cline = ([f"server corrections: OSTrack-256 (GPU), ost-gated {TAU}, K3;  every {corr.N} frames, "
                              f"delay {corr.L} frames = {1000 * corr.L / S['fps']:.0f} ms;  "
                              f"{'position + template' if corr.mode == 'pos+tmpl' else 'position only'}",
                              f"requests {corr.rid}, applied {len(corr.done)}, in flight {len(corr.pending)}"
                              + (f", not acknowledged {corr.failed}" if corr.failed else "")
                              + (f";  last: FPGA vs OSTrack {last['drift_px']:.1f} px ({last['drift_orig_px']:.0f} px in the image), "
                                 f"OSTrack {last['ostrack_ms']:.0f} ms ({last['calls']} GPU call{'s' if last['calls'] > 1 else ''}, peak {last['peaks'].split()[-1]})"
                                 if last else "")], D.MAGENTA)
                d = dict(frame=f, n=n, k=k, name=src.name, mode=crop, board=link is not None, res=res,
                         gt=src.gt_orig[k] if (src.gt_orig is not None and k is not None) else None,
                         box=(cx / s - box[2] / 2, cy / s - box[3] / 2, box[2], box[3]),
                         roi_box=(rx / s, ry / s, model.ROI / s, model.ROI / s),
                         fp=fp if crop == "fpga" else pad_to(fs, model.ROI), roi=crop_img, origin=(rx, ry), best=best,
                         score=score, good=good, f_us=f_us, rtt_us=rtt, rx_us=rx_us, fps=fps_s,
                         tmpl_patch=patch, tmpl_feat=tfeat, lag=0 if checker is None else checker.lag(),
                         corr=dict(lines=cline[0], col=cline[1]),
                         banners=[(t_, c_) for t_, c_, u_ in banners.values() if n < u_],
                         heavy_box=heavy_show[0] if heavy_show and n < heavy_show[1] else None,
                         tmpl_prev=st["prev"], tmpl_note=st["note"])
                img = dash.render(d)
                last_map = view_map(f)
                ctl.put(img)
                if vw is not None:
                    vw.write(img)
                rows[n] = dict(n=n, frame=k, roi_x=rx, roi_y=ry,
                               fpga_x=None if res is None else res["x"], fpga_y=None if res is None else res["y"],
                               fpga_score=score, fpga_good=int(good), model_x=None, model_y=None, model_score=None,
                               model_good=None, agree="", fpga_compute_us=round(f_us, 2), rtt_us=round(rtt, 1),
                               cx_orig=round(cx / s, 1), cy_orig=round(cy / s, 1),
                               request=rid or "", applied=" ".join(str(e[2]) for e in corr.events if e[0] == n and e[1] == "app"))
                if link is None:
                    rows[n].update(model_x=best[0] - M, model_y=best[1] - M, model_score=score, model_good=int(good))
                if k is not None:
                    preds.append((k, cx, cy))
                t_next += 1.0 / S["fps"]
                dt = t_next - time.perf_counter()
                if dt > 0:
                    time.sleep(dt)
                else:
                    t_next = time.perf_counter()
        except KeyboardInterrupt:
            reason = "quit"
        finally:
            if vw is not None:
                vw.release()
            if checker is not None:
                take_checks(checker.poll(wait=True))
                checker.close()
            src.close()
        self.write_session(sdir, S, tracker, crop, src, dash, rows, preds, corr, n, sc["s"], note)
        return reason

    def write_session(self, sdir, S, tracker, crop, src, dash, rows, preds, corr, n, scale, note):
        a = self.a
        cols = ["n", "frame", "roi_x", "roi_y", "fpga_x", "fpga_y", "fpga_score", "fpga_good", "model_x", "model_y",
                "model_score", "model_good", "agree", "fpga_compute_us", "rtt_us", "cx_orig", "cy_orig", "request", "applied"]
        with open(os.path.join(sdir, "frames.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, cols)
            w.writeheader()
            for i in sorted(rows):
                w.writerow(rows[i])
        if corr.done:
            with open(os.path.join(sdir, "corrections.csv"), "w", newline="") as fh:
                w = csv.DictWriter(fh, list(corr.done[0]))
                w.writeheader()
                w.writerows(corr.done)
        fu = np.array([r["fpga_compute_us"] for r in rows.values()] or [np.nan], float)
        rt = np.array([r["rtt_us"] for r in rows.values()] or [np.nan], float)
        fpsv = np.array([v for v in dash.h["fps"]] or [np.nan], float)
        board = self.link is not None
        agree_txt = ("n/a (no board: host model only)" if not board else
                     f"{dash.checked - dash.mismatch}/{dash.checked} checked ({n} frames)"
                     + ("" if dash.mismatch == 0 else f", first mismatch at frame {dash.first_bad}"))
        lines = [f"# P3 demo session: {tracker}, {'no board' if not board else 'crop ' + crop}, {src.name}", "",
                 f"command: `python3 demo.py {' '.join(f'--{k_.replace(chr(95), chr(45))} {v}' for k_, v in vars(a).items() if v not in (None, False))}`"
                 f" (settings at the end of the session: {json.dumps({k: S[k] for k in RESTART_KEYS + LIVE_KEYS})}; changes in controls.csv)", "",
                 "| metric | value |", "|---|---|",
                 f"| frames tracked | {n} |",
                 f"| FPGA = model | {agree_txt} |",
                 f"| rejected matches (hold) | {sum(1 for r in rows.values() if r['fpga_good'] == 0)} |",
                 f"| display rate, last {len(dash.h['fps'])} frames (fps) | p50 {np.nanpercentile(fpsv, 50):.1f} |"]
        if board:
            lines += [f"| FPGA compute after the last row (us) | p50 {np.nanpercentile(fu, 50):.1f}, max {np.nanmax(fu):.1f} |",
                      f"| network round trip, last row sent -> result (us) | p50 {np.nanpercentile(rt, 50):.0f}, p99 {np.nanpercentile(rt, 99):.0f}, max {np.nanmax(rt):.0f} |"]
        if corr.rid:
            dr = np.array([c["drift_px"] for c in corr.done] or [np.nan])
            om = np.array([c["ostrack_ms"] for c in corr.done] or [np.nan])
            lines += [f"| OSTrack requests / applied | {corr.rid} / {len(corr.done)} (late: {sum(1 for c in corr.done if c['late'] > 0)}; "
                      f"not acknowledged by the board: {corr.failed}) |",
                      f"| FPGA vs OSTrack at the request frame (scaled px) | mean {np.nanmean(dr):.1f}, max {np.nanmax(dr):.1f} |",
                      f"| OSTrack time per request (ms), GPU calls per request | p50 {np.nanmedian(om):.1f}, "
                      f"{np.mean([c['calls'] for c in corr.done]) if corr.done else float('nan'):.2f} |"]
        if src.kind == "otb" and preds and not S["loop"]:
            k_all = src.n_frames
            pc = np.full((k_all, 2), np.nan)
            g0 = src.d["gt"][0]
            pc[0] = (g0[0] + g0[2] / 2, g0[1] + g0[3] / 2)
            for k_, cx, cy in preds:
                pc[k_] = (cx, cy)
            gt_c = src.d["gt"][:, :2] + src.d["gt"][:, 2:] / 2
            if n == k_all - 1:
                m_ = src.otb.metrics.compute(pc, gt_c, scale)
                lines.append(f"| P@20 (information only) | {m_['prec20']:.1f} |")
                lines.append(f"| success AUC, fixed box size (information only) | {src.otb.iou_auc(pc, src.gt_orig, scale):.1f} |")
        lines += ["", note]
        open(os.path.join(sdir, "summary.md"), "w").write("\n".join(lines) + "\n")
        print("\n".join(lines), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["zsad", "s3x8"], default="s3x8")
    ap.add_argument("--crop", choices=["fpga", "server"], default="fpga")
    ap.add_argument("--source", choices=["otb", "webcam"], default="otb")
    ap.add_argument("--seq", default="Walking")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--init-box", default=None, help="webcam: x,y,w,h in camera pixels (first session)")
    ap.add_argument("--cam-size", default="640x480", help="webcam resolution (MJPG)")
    ap.add_argument("--cam-exposure", type=int, default=None,
                    help="webcam manual exposure in 100 us units (<= 330 keeps 30 fps); default: auto")
    ap.add_argument("--cam-gain", type=int, default=None, help="webcam gain (0..63 on the icSpring camera)")
    ap.add_argument("--target-px", type=float, default=16.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--loop", action="store_true", help="OTB: replay the sequence forever")
    ap.add_argument("--corr-n", type=int, default=30, help="correction request every N frames")
    ap.add_argument("--corr-l", type=int, default=6, help="correction applied L frames after its request frame")
    ap.add_argument("--corr-mode", choices=["pos+tmpl", "pos"], default="pos+tmpl")
    ap.add_argument("--no-corrections", action="store_true", help="start with the corrections off (page can turn them on)")
    ap.add_argument("--no-corrections-server", action="store_true", help="do not start the OSTrack server")
    ap.add_argument("--program", action="store_true", help="program the board with --tracker at start")
    ap.add_argument("--once", action="store_true", help="exit after the first session")
    ap.add_argument("--ip", default="10.8.100.230", help="board IP")
    ap.add_argument("--bind", default="100.76.229.14", help="web page address (Tailscale)")
    ap.add_argument("--http-port", type=int, default=8090)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-board", action="store_true",
                    help="no board: the host model tracks (to test sources and the page); labelled on screen")
    ap.add_argument("--workers", type=int, default=4, help="processes for the background FPGA = model check")
    a = ap.parse_args()

    def stop(*_):
        raise KeyboardInterrupt

    # stop cleanly (session summaries written) on Ctrl-C and on kill / pkill (SIGTERM); a process started in
    # the background inherits SIGINT ignored, so both handlers are installed explicitly
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    Demo(a).run()


if __name__ == "__main__":
    main()
