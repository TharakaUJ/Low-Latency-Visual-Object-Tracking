"""Python reference model of rtl/row_stats.v (same rules, no timing).

feed(dest_port, payload, err=False) takes one UDP packet as the FPGA sees it and returns the
list of result dicts the FPGA would send because of it (0, 1 or 2 results).
"""
import struct

MAGIC_DN, MAGIC_UP = 0x5AA5, 0x3CC3
PORT = 1234
HDR = struct.Struct("<HIHHH")
RES = struct.Struct("<HHIHHHHIIIIhhI")
FIELDS = ("magic", "flags", "frame_id", "rows_seen", "rows_bad", "height", "width",
          "checksum", "t_rx_start", "t_rx_end", "t_result", "x", "y", "score")
CHECKED = ("magic", "flags", "frame_id", "rows_seen", "rows_bad", "height", "width",
           "checksum", "x", "y", "score")


def row_packet(fid, row, width, height, pixels, magic=MAGIC_DN):
    return HDR.pack(magic, fid & 0xFFFFFFFF, row, width, height) + bytes(pixels)


def parse_result(data):
    return dict(zip(FIELDS, RES.unpack(data)))


class RowStatsModel:
    def __init__(self):
        self.active = False
        self.fid = self.rows = self.bad = self.height = self.width = self.sum = 0
        self.rows_bad_total = 0

    def _result(self, flags, fid, rows, bad, height, width, cks):
        return dict(magic=MAGIC_UP, flags=flags, frame_id=fid, rows_seen=rows, rows_bad=bad,
                    height=height, width=width, checksum=cks & 0xFFFFFFFF, x=0, y=0, score=0)

    def feed(self, dest_port, payload, err=False):
        if dest_port != PORT:
            return []
        n = len(payload)
        if n >= 12:
            magic, fid, row, width, height = HDR.unpack_from(payload)
        else:
            # the RTL keeps the previous packet's header bytes when the packet is short;
            # a short packet is always bad (p_idx < 11), so the values do not matter
            magic = fid = row = width = height = 0
        npix = max(0, n - 12)
        psum = sum(payload[12:]) & 0xFFFFFFFF
        udp_len = 8 + n
        good = (not err and n >= 12 and magic == MAGIC_DN and udp_len == 20 + width
                and npix == width and row < height and height != 0)
        out = []
        if not good:
            if self.active:
                self.bad = (self.bad + 1) & 0xFFFF
            self.rows_bad_total += 1
            return out
        if self.active and fid != self.fid:
            out.append(self._result(2, self.fid, self.rows, self.bad, self.height, self.width,
                                    self.sum))
            self.active = False
        if not self.active:
            self.active = True
            self.fid, self.bad, self.height, self.width = fid, 0, height, width
            self.rows, self.sum = 0, 0
        if self.rows + 1 == self.height:
            out.append(self._result(1, self.fid, self.rows + 1, self.bad, self.height,
                                    self.width, self.sum + psum))
            self.active = False
            self.rows, self.sum = 0, 0
        else:
            self.rows = (self.rows + 1) & 0xFFFF
            self.sum = (self.sum + psum) & 0xFFFFFFFF
        return out
