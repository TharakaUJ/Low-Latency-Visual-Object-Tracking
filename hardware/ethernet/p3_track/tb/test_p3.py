"""cocotb testbench: p3_track fpga_core (MAC + UDP + row_stats P3 + async FIFO + tracker core) over a
simulated RGMII PHY, for either tracker (env TRACKER=zsad|s3x8). Every result is checked against the
host model (host/trackers.py): ROI origin, FPGA-held position, score, flags.
Run (Verilator 5 from ~/tools/mamba/envs/hdl):
  cd hardware/ethernet/p3_track/tb && TRACKER=zsad PATH=~/tools/mamba/envs/hdl/bin:$PATH SIM=verilator \
      ../../.venv-sim/bin/pytest -q -s test_p3.py
"""
import logging
import os
import struct
import sys

import numpy as np
import cocotb
import cocotb_test.simulator
from cocotb.log import SimLog
from cocotb.result import SimTimeoutError
from cocotb.triggers import RisingEdge, Timer, with_timeout
from cocotbext.eth import GmiiFrame, RgmiiPhy
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import ARP, Ether

tests_dir = os.path.abspath(os.path.dirname(__file__))
host_dir = os.path.abspath(os.path.join(tests_dir, "..", "..", "host"))
sys.path.insert(0, host_dir)
from trackers import make_model, Track, pad_to   # noqa: E402

TRACKER = os.environ.get("TRACKER", "zsad")
SECTIONS = set(os.environ.get("SECTIONS", "1,2,3,4,5,6,7,8").split(","))   # run a subset while debugging
BOARD_MAC, BOARD_IP = "02:00:0a:08:64:e6", "10.8.100.230"
HOST_MAC, HOST_IP, HOST_PORT = "5a:51:52:53:54:55", "10.8.100.45", 5678
PORT = 1234
HDR = struct.Struct("<HIHHH")
RES = struct.Struct("<HHIHHHHIIIIHHIHH")
F = ("magic", "flags", "frame_id", "rows_seen", "rows_bad", "height", "width", "checksum",
     "t_rx_start", "t_rx_end", "t_result", "x", "y", "score", "roi_x", "roi_y")
TRK_HALF_NS = 12 if TRACKER == "zsad" else 8          # 41.67 MHz / 62.5 MHz


class TB:
    def __init__(self, dut):
        self.dut = dut
        self.log = SimLog("cocotb.tb")
        self.log.setLevel(logging.INFO)
        self.phy = RgmiiPhy(dut.phy0_txd, dut.phy0_tx_ctl, dut.phy0_tx_clk,
                            dut.phy0_rxd, dut.phy0_rx_ctl, dut.phy0_rx_clk, speed=1000e6)
        self.phy1 = RgmiiPhy(dut.phy1_txd, dut.phy1_tx_ctl, dut.phy1_tx_clk,
                             dut.phy1_rxd, dut.phy1_rx_ctl, dut.phy1_rx_clk, speed=1000e6)
        for name in ("phy0_rxd", "phy0_txd", "phy1_rxd", "phy1_txd"):
            logging.getLogger(f"cocotb.fpga_core.{name}").setLevel(logging.WARNING)
        dut.phy0_int_n.setimmediatevalue(1)
        dut.phy1_int_n.setimmediatevalue(1)
        dut.btn.setimmediatevalue(0)
        dut.sw.setimmediatevalue(0)
        dut.clk.setimmediatevalue(0)
        dut.clk90.setimmediatevalue(0)
        dut.clk_trk.setimmediatevalue(0)
        self.results, self.acks = [], []
        cocotb.start_soon(self._run_clk())
        cocotb.start_soon(self._run_clk_trk())

    async def _run_clk(self):
        t = Timer(2, "ns")
        while True:
            self.dut.clk.value = 1
            await t
            self.dut.clk90.value = 1
            await t
            self.dut.clk.value = 0
            await t
            self.dut.clk90.value = 0
            await t

    async def _run_clk_trk(self):
        t = Timer(TRK_HALF_NS, "ns")
        while True:
            self.dut.clk_trk.value = 1
            await t
            self.dut.clk_trk.value = 0
            await t

    async def init(self):
        self.dut.rst.setimmediatevalue(0)
        self.dut.rst_trk.setimmediatevalue(0)
        for _ in range(10):
            await RisingEdge(self.dut.clk)
        self.dut.rst.value = 1
        self.dut.rst_trk.value = 1
        for _ in range(10):
            await RisingEdge(self.dut.clk)
        self.dut.rst.value = 0
        self.dut.rst_trk.value = 0

    async def collector(self):
        while True:
            f = await self.phy.tx.recv()
            pkt = Ether(bytes(f.get_payload()))
            if ARP in pkt and pkt[ARP].op == 1:
                rsp = Ether(src=HOST_MAC, dst=BOARD_MAC) / ARP(
                    hwtype=1, ptype=0x0800, hwlen=6, plen=4, op=2, hwsrc=HOST_MAC, psrc=HOST_IP,
                    hwdst=BOARD_MAC, pdst=BOARD_IP)
                await self.phy.rx.send(GmiiFrame.from_payload(rsp.build()))
            elif UDP in pkt:
                d = bytes(pkt[UDP].payload)
                assert len(d) == RES.size, len(d)
                r = dict(zip(F, RES.unpack(d)))
                (self.results if r["magic"] == 0x3CC3 else self.acks).append(r)
            else:
                raise AssertionError(f"unexpected frame: {pkt!r}")

    async def send(self, payload, fcs_bad=False):
        pkt = (Ether(src=HOST_MAC, dst=BOARD_MAC) / IP(src=HOST_IP, dst=BOARD_IP)
               / UDP(sport=HOST_PORT, dport=PORT) / payload)
        fr = GmiiFrame.from_payload(pkt.build())
        if fcs_bad:
            fr.data[-1] ^= 0xFF
        await self.phy.rx.send(fr)

    async def wait_for(self, lst, n, timeout_ns):
        async def w():
            while len(lst) < n:
                await RisingEdge(self.dut.clk)
        try:
            await with_timeout(w(), timeout_ns, "ns")
            return True
        except SimTimeoutError:
            return False


async def wait_fids(tb, fids, timeout_ns):
    async def w():
        while not set(fids) <= {r["frame_id"] for r in tb.results}:
            await RisingEdge(tb.dut.clk)
    try:
        await with_timeout(w(), timeout_ns, "ns")
        return True
    except SimTimeoutError:
        return False


def row_pkt(fid, row, img, magic=0x5AA5):
    h, w = img.shape
    return HDR.pack(magic, fid, row, w, h) + img[row].tobytes()


@cocotb.test()
async def run_test(dut):
    tb = TB(dut)
    await tb.init()
    cocotb.start_soon(tb.collector())
    model = make_model(TRACKER)
    R = model.ROI
    rng = np.random.default_rng(11)
    trk_ns = 1_500_000 if TRACKER == "zsad" else 4_000_000   # per frame incl. wire time, generous
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        tb.log.info("%-55s %s %s", name, "PASS" if ok else "FAIL", "" if ok else detail)

    # warm-up (ARP), P1-size frame: untracked
    await tb.send(HDR.pack(0x5AA5, 0xEEEEEEEE, 0, 4, 1) + b"\0\0\0\0")
    assert await tb.wait_for(tb.results, 1, 400_000)
    tb.results.clear()

    # scene: smooth textured target on a noise background
    W, H = R + 64, R + 40
    tex = (128 + 60 * np.sin(np.arange(28)[:, None] / 3.0) * np.cos(np.arange(28)[None, :] / 4.0)
           + rng.integers(-30, 31, (28, 28))).clip(0, 255).astype(np.uint8)

    def scene(cx, cy, noise=4):
        f = rng.integers(0, 256, (H, W)).astype(np.int64)
        f = (f // 2 + 64)
        x0, y0 = cx - 14, cy - 14
        f[y0:y0 + 28, x0:x0 + 28] = tex.astype(np.int64) + rng.integers(-noise, noise + 1, (28, 28))
        return f.clip(0, 255).astype(np.uint8)

    # template + position (FPGA crop mode)
    c0 = (60, 50)
    f0 = scene(*c0, noise=0)
    tr = Track(model, f0, c0)
    nchunks = 0
    for off in range(0, len(tr.tmpl), 1024):
        chunk = tr.tmpl[off:off + 1024]
        await tb.send(struct.pack("<HH", 0x5AA6, off) + chunk)
        nchunks += 1
    await tb.send(struct.pack("<HHH", 0x5AA7, tr.tx, tr.ty))
    ok = await tb.wait_for(tb.acks, nchunks + 1, 400_000)
    tb.log.info("acks: %s", [(hex(x["magic"]), x["frame_id"], x["rows_seen"], x["checksum"]) for x in tb.acks])
    tb.log.info("results: %s", [(hex(x["magic"]), x["frame_id"], x["flags"]) for x in tb.results])
    if len(tb.acks) < nchunks + 1:
        assert False, "missing acks"
    tsum_ok = all(a["magic"] == 0x3CC4 and a["checksum"] == sum(tr.tmpl[a["frame_id"]:a["frame_id"] + a["rows_seen"]])
                  for a in tb.acks[:nchunks])
    pos_ok = tb.acks[nchunks]["magic"] == 0x3CC5 and (tb.acks[nchunks]["x"], tb.acks[nchunks]["y"]) == (tr.tx, tr.ty)
    check(f"template ({nchunks} chunk(s)) + position acks", ok and tsum_ok and pos_ok, str(tb.acks))

    fid = 1000
    rois = {}   # frame id -> (ROI the model matched, template bytes), dumped on a mismatch

    async def frame(img, name, wait=True, rows=None, expect_track=True, crop_expected=None):
        """Send a frame; compute the model's expectation; compare (if wait)."""
        nonlocal fid
        f = fid
        fid += 1
        n0 = len(tb.results)
        exp = None
        if expect_track:
            fp = pad_to(img, R)
            o = tr.origin(fp.shape)
            roi = fp[o[1]:o[1] + R, o[0]:o[0] + R]
            rois[f] = (roi.copy(), bytes(tr.tmpl), o)
            bx, by, z, good = model.match(roi)
            tr.update(o, bx, by, good)
            exp = dict(roi_x=o[0], roi_y=o[1], x=tr.tx, y=tr.ty, score=z,
                       flags=0x1 | 0x8 | (0x4 if good else 0) | (0x20 if img.shape != (R, R) else 0))
        for r in (range(img.shape[0]) if rows is None else rows):
            await tb.send(row_pkt(f, r, img))
        if not wait:
            return f, exp, n0
        got_ok = await wait_fids(tb, [f], trk_ns)
        return await compare(f, exp, name, got_ok)

    async def compare(f, exp, name, got_ok=True):
        g = next((r for r in tb.results if r["frame_id"] == f), None)
        if exp is None:
            check(name, g is not None, "no result")
            return g
        ok = g is not None and all(g[k] == v for k, v in exp.items())
        if not ok and f in rois:
            roi, tm, o = rois[f]
            np.savez(os.path.join(tests_dir, f"mismatch_{TRACKER}_{f}.npz"), roi=roi,
                     tmpl=np.frombuffer(tm, np.uint8), origin=np.array(o),
                     exp=np.array([exp.get(k, -1) for k in F[11:]]),
                     got=np.array([-1 if g is None else g[k] for k in F[11:]]))
        check(name, ok, f"expected {exp} got {None if g is None else {k: g[k] for k in exp}}")
        return g

    if '1' in SECTIONS:
        # 1. FPGA crop: target moves; includes clamping at the borders
        path = [(62, 52), (70, 48), (78, 60), (66, 70), (20, 18), (16, 16), (W - 16, H - 16), (W - 22, H - 20), (90, 60)]
        for k, c in enumerate(path):
            await frame(scene(*c), f"FPGA crop, target at {c}")

    if '2' in SECTIONS:
        # 2. set position mid-run, then a frame: origin must follow the new position
        tr.tx, tr.ty = 40, 30
        await tb.send(struct.pack("<HHH", 0x5AA7, tr.tx, tr.ty))
        await tb.wait_for(tb.acks, nchunks + 2, 200_000)
        await frame(scene(50, 40), "after set-position (40,30)")

    if '3' in SECTIONS:
        # 3. out-of-order rows: complete, untracked, position unchanged
        img = scene(52, 42)
        order = list(range(H))
        order[20], order[21] = order[21], order[20]
        g = await frame(img, "rows 20/21 swapped: untracked", rows=order, expect_track=False)
        check("  ... flags complete+crop, not tracked", g is not None and g["flags"] == 0x21, str(g and g["flags"]))
        await frame(scene(52, 42), "tracked after out-of-order frame")

    if '4' in SECTIONS:
        # 4. incomplete frame closed by the next one, position unchanged
        img = scene(54, 44)
        f_inc, _, n0 = await frame(img, "", wait=False, rows=range(H // 2), expect_track=False)
        await frame(scene(54, 44), "tracked after incomplete frame")
        g = next((r for r in tb.results if r["frame_id"] == f_inc), None)
        check("  ... incomplete frame: flags closed+crop", g is not None and g["flags"] == 0x22 and g["rows_seen"] == H // 2,
              str(g))

    if '5' in SECTIONS:
        # 5. frame smaller than the ROI (not padded by the sender): untracked
        small = rng.integers(0, 256, (R - 20, R - 10), dtype=np.uint8)
        g = await frame(small, "frame smaller than ROI: untracked", expect_track=False)
        check("  ... flags complete only", g is not None and g["flags"] == 0x1, str(g and g["flags"]))

    if '6' in SECTIONS:
        # 6. server crop (frame = ROI x ROI): origin (0,0), position = best + MARGIN
        tr_s = Track(model, f0, c0)
        for k, c in enumerate([(62, 52), (66, 50), (70, 56)]):
            full = scene(*c)
            fp, o, roi = tr_s.crop(full)
            bx, by, z, good = model.match(roi)
            tr_s.update(o, bx, by, good)
            tr.tx, tr.ty = bx + model.MARGIN if good else tr.tx, by + model.MARGIN if good else tr.ty
            f = fid
            fid += 1
            n0 = len(tb.results)
            for r in range(R):
                await tb.send(row_pkt(f, r, roi))
            await wait_fids(tb, [f], trk_ns)
            await compare(f, dict(roi_x=0, roi_y=0, x=bx + model.MARGIN, y=by + model.MARGIN, score=z,
                                  flags=0x1 | 0x8 | (0x4 if good else 0)), f"server crop frame {k}")

    if '7' in SECTIONS:
        # 7. back-to-back server-crop pairs (frame k+1 arrives while k is tracked): no rows lost
        fpga_pos = (tr.tx, tr.ty)
        for k in range(2):
            pend = []
            for j in range(2):
                c = (60 + 3 * j, 52 + 2 * k)
                fp, o, roi = tr_s.crop(scene(*c))
                bx, by, z, good = model.match(roi)
                if good:
                    fpga_pos = (bx + model.MARGIN, by + model.MARGIN)
                f = fid
                fid += 1
                pend.append((f, dict(roi_x=0, roi_y=0, x=fpga_pos[0], y=fpga_pos[1], score=z, rows_seen=R,
                                     flags=0x1 | 0x8 | (0x4 if good else 0))))
                for r in range(R):
                    await tb.send(row_pkt(f, r, roi))
            await wait_fids(tb, [f for f, _ in pend], 2 * trk_ns)
            for (f, e) in pend:
                await compare(f, e, f"back-to-back pair {k}, frame {f}")
            tr.tx, tr.ty = pend[-1][1]["x"], pend[-1][1]["y"]

    if '8' in SECTIONS:
        # 8. P1-size frame: untracked, then a template change mid-frame (applies to the next frame)
        p1 = rng.integers(0, 256, (8, 32), dtype=np.uint8)
        f = fid
        fid += 1
        for r in range(8):
            await tb.send(row_pkt(f, r, p1))
        await wait_fids(tb, [f], 100_000)
        g = next((r for r in tb.results if r["frame_id"] == f), None)
        check("P1-size frame untracked (flags 1)", g is not None and g["flags"] == 0x1, str(g))

        tr2 = Track(model, scene(70, 60, noise=0), (70, 60))           # new template + position
        model.set_template(tr.tmpl)                                      # frame below still uses the old template
        tr.tx, tr.ty = tr2.tx, tr2.ty
        await tb.send(struct.pack("<HHH", 0x5AA7, tr.tx, tr.ty))
        img = scene(70, 60)
        fp = pad_to(img, R)
        o = tr.origin(fp.shape)
        bx, by, z, good = model.match(fp[o[1]:o[1] + R, o[0]:o[0] + R])
        tr.update(o, bx, by, good)
        exp = dict(roi_x=o[0], roi_y=o[1], x=tr.tx, y=tr.ty, score=z, flags=0x1 | 0x8 | (0x4 if good else 0) | 0x20)
        f = fid
        fid += 1
        n0 = len(tb.results)
        for r in range(H):
            if r == H // 2:
                for off in range(0, len(tr2.tmpl), 1024):
                    await tb.send(struct.pack("<HH", 0x5AA6, off) + tr2.tmpl[off:off + 1024])
            await tb.send(row_pkt(f, r, img))
        await wait_fids(tb, [f], trk_ns)
        await compare(f, exp, "template sent mid-frame: frame uses the old one")
        model.set_template(tr2.tmpl)
        tr.tmpl = tr2.tmpl
        await frame(scene(72, 62), "next frame uses the new template")

    for _ in range(3000):
        await RisingEdge(dut.clk)
    lat = [((r["t_result"] - r["t_rx_end"]) & 0xFFFFFFFF) for r in tb.results if r["flags"] & 8]
    if lat:
        tb.log.info("tracker time after the last row: %d..%d cycles of 125 MHz", min(lat), max(lat))
    for r in tb.results:
        tb.log.info("result fid %d flags %#x rows %d xy (%d,%d) roi (%d,%d) score %d t_rx_end %d t_result %d",
                    r["frame_id"], r["flags"], r["rows_seen"], r["x"], r["y"], r["roi_x"], r["roi_y"], r["score"],
                    r["t_rx_end"], r["t_result"])
    n_bad = checks.count(False)
    tb.log.info("%s: %d/%d checks pass", TRACKER, len(checks) - n_bad, len(checks))
    assert n_bad == 0, f"{n_bad} checks failed"


# cocotb-test runner
rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "rtl"))
proc_dir = os.path.abspath(os.path.join(tests_dir, "..", "..", "..", "rtl", "processing"))
eth_rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "lib", "eth", "rtl"))
axis_rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "lib", "eth", "lib", "axis", "rtl"))


def test_p3(request):
    eth = ["eth_mac_1g_rgmii_fifo", "eth_mac_1g_rgmii", "iddr", "oddr", "ssio_ddr_in",
           "rgmii_phy_if", "eth_mac_1g", "axis_gmii_rx", "axis_gmii_tx", "lfsr", "eth_axis_rx",
           "eth_axis_tx", "udp_complete", "udp_checksum_gen", "udp", "udp_ip_rx", "udp_ip_tx",
           "ip_complete", "ip", "ip_eth_rx", "ip_eth_tx", "ip_arb_mux", "arp", "arp_cache",
           "arp_eth_rx", "arp_eth_tx", "eth_arb_mux"]
    axis = ["arbiter", "priority_encoder", "axis_fifo", "axis_async_fifo", "axis_async_fifo_adapter"]
    srcs = [os.path.join(rtl_dir, f) for f in ("fpga_core.v", "row_stats.v", "hex_display.v")]
    defines = []
    if TRACKER == "s3x8":
        srcs += [os.path.join(rtl_dir, f) for f in ("s3x8_core.sv", "s3x8_top.v")]
        defines = ["+define+TRACKER_S3X8"]
    else:
        srcs += [os.path.join(rtl_dir, "zsad_core.sv")]
        srcs += [os.path.join(proc_dir, f) for f in ("line_buffer.sv", "window_buffer.sv", "template_match.sv")]
    srcs += [os.path.join(eth_rtl_dir, f + ".v") for f in eth]
    srcs += [os.path.join(axis_rtl_dir, f + ".v") for f in axis]
    cocotb_test.simulator.run(
        python_search=[tests_dir, host_dir],
        verilog_sources=srcs,
        toplevel="fpga_core",
        module=os.path.splitext(os.path.basename(__file__))[0],
        sim_build=os.path.join(tests_dir, f"sim_build_{TRACKER}"),
        extra_env={"TRACKER": TRACKER},
        compile_args=defines + ["-Wno-fatal", "-Wno-WIDTH", "-Wno-LATCH", "-Wno-MULTIDRIVEN", "-Wno-UNOPTFLAT",
                                "-Wno-CASEINCOMPLETE", "-Wno-PINMISSING", "-Wno-SYNCASYNCNET", "-Wno-CMPCONST",
                                "-Wno-SELRANGE", "-O2"],
    )
