"""OSTrack-256 correction server for demo.py: the server-side heavy tracker of the locked system.
Runs in the research environment (GPU): `<research>/.venv-heavy/bin/python heavy_server.py`, started by
corrections.py. Same heavy as the research loop: E45 ost() (official OSTrack-256 weights; peak = max of the
score map) with the E49 gated query (ost-gated): search around the edge's reported position with the heavy's
own last box size; if that peak < tau, search again around the heavy's own previous box; keep the higher peak.

Protocol on stdin/stdout: one JSON line, then h*w*3 raw bytes (BGR uint8 frame, original resolution);
the answer is one JSON line. Boxes are (x, y, w, h) in original frame pixels.
  {"cmd": "init",  "h": .., "w": .., "box": [..]}                               -> {"cmd": "init", "ms": ..}
  {"cmd": "query", "id": .., "h": .., "w": .., "center": [cx, cy], "tau": ..}  -> {"cmd": "query", "id": .., "box": [..], "peaks": [..], "ms": ..}
First line written: {"ready": true, "device": ..}. Anything else OSTrack prints goes to stderr.
"""
import json, os, sys, time

RESEARCH = os.path.expanduser("~/Documents/Object_tracking_test/object_tracking")


def main():
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)                                   # library prints must not corrupt the protocol
    sys.path.insert(0, RESEARCH)
    os.chdir(RESEARCH)
    import numpy as np
    import cv2
    import torch
    from experiments.E45_edge_prior_heavy.src.run_loop import ost
    h = ost()
    dev = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    sync = torch.cuda.synchronize if torch.cuda.is_available() else (lambda: None)

    def track_at(rgb, b):
        h.t.state = [float(v) for v in b]
        return np.array(h.update(rgb), float), float(h.peak)

    proto.write(json.dumps({"ready": True, "device": dev}) + "\n")
    inp = sys.stdin.buffer
    box = None
    while True:
        line = inp.readline()
        if not line:
            break
        q = json.loads(line)
        buf = inp.read(q["h"] * q["w"] * 3)
        rgb = cv2.cvtColor(np.frombuffer(buf, np.uint8).reshape(q["h"], q["w"], 3), cv2.COLOR_BGR2RGB)
        t0 = time.perf_counter()
        if q["cmd"] == "init":
            h.init(rgb, q["box"])
            box = np.array(q["box"], float)
            track_at(rgb, box)                      # warm-up (first GPU call is slow); every query sets the state
            out = {"cmd": "init"}
        else:
            w, hh = box[2:]
            c = q["center"]
            res = [track_at(rgb, np.array([c[0] - w / 2, c[1] - hh / 2, w, hh]))]
            if res[0][1] < q["tau"]:
                res.append(track_at(rgb, box))
            box = max(res, key=lambda r: r[1])[0]
            out = {"cmd": "query", "id": q["id"], "box": box.tolist(), "peaks": [r[1] for r in res]}
        sync()
        out["ms"] = (time.perf_counter() - t0) * 1e3
        proto.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
