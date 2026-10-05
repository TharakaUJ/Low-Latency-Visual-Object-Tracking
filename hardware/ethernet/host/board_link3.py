"""Host side of the P3 board protocol (p3_track/rtl/row_stats.v): template chunks, set position,
frames as one UDP packet per row (whole frame for FPGA crop, the ROI for server crop), 44-byte
results matched by frame_id, kernel receive timestamps."""
import socket, struct, time
import numpy as np

PORT = 1234
HDR = struct.Struct("<HIHHH")
RES = struct.Struct("<HHIHHHHIIIIHHIHH")
FIELDS = ("magic", "flags", "frame_id", "rows_seen", "rows_bad", "height", "width", "checksum",
          "t_rx_start", "t_rx_end", "t_result", "x", "y", "score", "roi_x", "roi_y")
SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)
FCLK = 125e6
F_COMPLETE, F_CLOSED, F_GOOD, F_TRACKED, F_TIMEOUT, F_CROP = 1, 2, 4, 8, 16, 32
M_FRAME, M_TACK, M_PACK = 0x3CC3, 0x3CC4, 0x3CC5
CHUNK = 1024


class BoardLink3:
    def __init__(self, ip="10.8.100.230", port=PORT, timeout=0.2):
        self.dst = (ip, port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
        self.s.bind(("", 0))
        self.timeout = timeout

    def recv(self, timeout=None):
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
            return None             # e.g. a P1/P2 bitstream (40-byte results) is loaded
        r = dict(zip(FIELDS, RES.unpack(d)))
        r["t_recv_ns"] = t
        return r

    def drain(self, t=0.05):
        out, end = [], time.time() + t
        while time.time() < end:
            r = self.recv(0.01)
            if r:
                out.append(r)
        return out

    def _wait(self, magic, pred, timeout=1.0):
        end = time.time() + timeout
        while time.time() < end:
            r = self.recv()
            if r and r["magic"] == magic and pred(r):
                return r
        return None

    def send_template(self, tb):
        """Upload template bytes in chunks; True when every chunk ack carries the right byte sum."""
        tb = bytes(tb)
        for off in range(0, len(tb), CHUNK):
            c = tb[off:off + CHUNK]
            self.s.sendto(struct.pack("<HH", 0x5AA6, off) + c, self.dst)
            a = self._wait(M_TACK, lambda r: r["frame_id"] == off)
            if a is None or a["checksum"] != sum(c) or a["rows_seen"] != len(c):
                return False
        return True

    def set_position(self, tx, ty):
        self.s.sendto(struct.pack("<HHH", 0x5AA7, int(tx), int(ty)), self.dst)
        return self._wait(M_PACK, lambda r: (r["x"], r["y"]) == (int(tx), int(ty))) is not None

    def send_frame(self, fid, img):
        img = np.ascontiguousarray(img, dtype=np.uint8)
        h, w = img.shape
        assert w <= 1460
        t0 = time.time_ns()
        for r in range(h):
            self.s.sendto(HDR.pack(0x5AA5, fid & 0xFFFFFFFF, r, w, h) + img[r].tobytes(), self.dst)
        return t0, time.time_ns()

    def track(self, fid, img, timeout=1.0):
        """Send one frame and wait for its result. -> (result or None, t_send0, t_send1)."""
        t0, t1 = self.send_frame(fid, img)
        r = self._wait(M_FRAME, lambda r: r["frame_id"] == (fid & 0xFFFFFFFF), timeout)
        return r, t0, t1
