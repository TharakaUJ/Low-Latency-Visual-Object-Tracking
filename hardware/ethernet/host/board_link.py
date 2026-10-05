"""Host side of the P2 board protocol (see p2_zsad/rtl/row_stats.v): template upload, ROI frames
as one UDP packet per row, result packets matched by frame_id, kernel receive timestamps."""
import socket, struct, time
import numpy as np

PORT = 1234
HDR = struct.Struct("<HIHHH")
RES = struct.Struct("<HHIHHHHIIIIHHI")
FIELDS = ("magic", "flags", "frame_id", "rows_seen", "rows_bad", "height", "width", "checksum",
          "t_rx_start", "t_rx_end", "t_result", "x", "y", "score")
SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)
FCLK = 125e6
F_COMPLETE, F_CLOSED, F_GOOD, F_TRACKED, F_TIMEOUT = 1, 2, 4, 8, 16


class BoardLink:
    def __init__(self, ip="10.8.100.230", port=PORT, timeout=0.2):
        self.dst = (ip, port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
        self.s.bind(("", 0))
        self.timeout = timeout
        self.s.settimeout(timeout)

    def _recv(self, timeout=None):
        self.s.settimeout(self.timeout if timeout is None else timeout)
        try:
            d, anc, _, _ = self.s.recvmsg(2048, 64)
        except socket.timeout:
            return None
        t = time.time_ns()
        for lvl, typ, data in anc:
            if lvl == socket.SOL_SOCKET and typ == SO_TIMESTAMPNS:
                sec, nsec = struct.unpack("qq", data[:16])
                t = sec * 1_000_000_000 + nsec
        if len(d) != RES.size:
            return None
        r = dict(zip(FIELDS, RES.unpack(d)))
        r["t_recv_ns"] = t
        return r

    def drain(self, t=0.05):
        out, end = [], time.time() + t
        while time.time() < end:
            r = self._recv(0.01)
            if r:
                out.append(r)
        return out

    def send_template(self, tmpl):
        """Upload a 16x16 uint8 template; returns True when the ack checksum matches."""
        t = np.ascontiguousarray(tmpl, dtype=np.uint8)
        assert t.shape == (16, 16)
        self.s.sendto(struct.pack("<H", 0x5AA6) + t.tobytes(), self.dst)
        end = time.time() + 1.0
        while time.time() < end:
            r = self._recv()
            if r and r["magic"] == 0x3CC4:
                return r["checksum"] == int(t.astype(np.int64).sum())
        return False

    def track(self, fid, roi):
        """Send one ROI frame (one packet per row), wait for its result. -> (result or None, t_send0, t_send1)."""
        roi = np.ascontiguousarray(roi, dtype=np.uint8)
        h, w = roi.shape
        t0 = time.time_ns()
        for r in range(h):
            self.s.sendto(HDR.pack(0x5AA5, fid & 0xFFFFFFFF, r, w, h) + roi[r].tobytes(), self.dst)
        t1 = time.time_ns()
        end = time.time() + 1.0
        while time.time() < end:
            res = self._recv()
            if res and res["magic"] == 0x3CC3 and res["frame_id"] == (fid & 0xFFFFFFFF):
                return res, t0, t1
        return None, t0, t1
