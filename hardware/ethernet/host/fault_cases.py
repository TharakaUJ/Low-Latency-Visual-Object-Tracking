"""Fault-injection cases for rtl/row_stats.v, shared by the cocotb testbench and the board test.

Each case is a list of packets (dest_port, payload, fcs_bad). fcs_bad packets are sent with a
corrupted Ethernet FCS (testbench only: the MAC drops them, so the model never sees them).
Every case ends with a one-row "flush" frame with a fresh frame_id, which closes any frame
the case left open, so cases are independent. expected() runs the model over the cases.
"""
import random
from row_model import RowStatsModel, row_packet, MAGIC_DN, PORT

W, H = 32, 8


def _pix(seed, n):
    r = random.Random(seed)
    return bytes(r.randrange(256) for _ in range(n))


def _rows(fid, w=W, h=H, rows=None, seed=0):
    rows = range(h) if rows is None else rows
    return [(PORT, row_packet(fid, r, w, h, _pix(seed * 1000 + r, w)), False) for r in rows]


def build_cases():
    c = []
    flush_id = [0xF0000000]

    def add(name, pkts, board=True):
        flush_id[0] += 1
        pkts = pkts + [(PORT, row_packet(flush_id[0], 0, 4, 1, b"\x01\x02\x03\x04"), False)]
        c.append(dict(name=name, packets=pkts, board=board))

    add("good frame", _rows(1, seed=1))
    add("skipped row 3", _rows(2, rows=[0, 1, 2, 4, 5, 6, 7], seed=2))
    p = _rows(3, seed=3)
    p[2] = (PORT, row_packet(3, 2, W, H, _pix(1, W), magic=0x1234), False)
    add("bad magic on row 2", p)
    p = _rows(4, seed=4)
    p[5] = (PORT, row_packet(4, 5, W, H, _pix(2, W - 2)), False)
    add("row 5 two pixels short", p)
    p = _rows(5, seed=5)
    p[5] = (PORT, row_packet(5, 5, W, H, _pix(3, W + 2)), False)
    add("row 5 two pixels long", p)
    p = _rows(6, seed=6)
    p.insert(3, (PORT, b"\x00\x01\x02\x03\x04", False))
    add("5-byte packet inside a frame", p)
    p = _rows(7, seed=7)
    p.insert(3, (PORT, b"", False))
    add("empty UDP payload inside a frame", p)
    add("width 0 single-row frame", [(PORT, row_packet(8, 0, 0, 1, b""), False)])
    p = _rows(9, seed=9)
    p[7] = (PORT, row_packet(9, 8, W, H, _pix(4, W)), False)
    add("row index = height", p)
    add("height 0", [(PORT, row_packet(10, 0, W, 0, _pix(5, W)), False)])
    add("frame ends early (rows 0-3 of 8)", _rows(11, rows=range(4), seed=11))
    add("bad row while no frame is open", [(PORT, row_packet(12, 0, W, H, _pix(6, W), magic=0), False)]
        + _rows(12, seed=12))
    p = _rows(13, seed=13)
    p.insert(4, p[3])
    add("duplicate row 3 (known limitation)", p)
    p = _rows(14, seed=14)
    p.insert(4, (PORT + 1, row_packet(14, 4, W, H, _pix(7, W)), False))
    add("other UDP port inside a frame", p)
    p = _rows(15, seed=15)
    p[4], p[5] = p[5], p[4]
    add("rows 4 and 5 swapped", p)
    add("max width 1460, 2 rows", _rows(16, w=1460, h=2, seed=16))
    add("frame_id wrap 0xFFFFFFFF -> 0", _rows(0xFFFFFFFF, seed=17) + _rows(0, seed=18))
    a, b = _rows(19, seed=19), _rows(20, seed=20)
    add("two frames interleaved", [x for pair in zip(a, b) for x in pair])
    p = _rows(21, seed=21)
    p[6] = (p[6][0], p[6][1], True)
    add("bad Ethernet FCS on row 6 (testbench only)", p, board=False)
    add("good frame after all faults", _rows(22, seed=22))
    return c


def expected(cases, board=False):
    """Results the FPGA should send, per case. board=True skips the testbench-only cases."""
    m = RowStatsModel()
    out = []
    for case in cases:
        if board and not case["board"]:
            continue
        res = []
        for dport, payload, fcs_bad in case["packets"]:
            if fcs_bad:
                continue                 # dropped by the MAC
            if dport == PORT and len(payload) == 0:
                continue                 # dropped by udp_ip_rx (no payload beat, header-only datagram)
            res += m.feed(dport, payload)
        out.append(res)
    return out
