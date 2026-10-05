"""cocotb testbench: p2_zsad fpga_core (MAC + UDP + row_stats P2 + async FIFO + zsad_core with the
user's window_buffer/template_match) over a simulated RGMII PHY. Checks every result packet against
host/zsad_model.py (bit-exact ZSAD) and the frame rules.
Run (Verilator 5 from ~/tools/mamba/envs/hdl):
  cd hardware/ethernet/p2_zsad/tb && PATH=~/tools/mamba/envs/hdl/bin:$PATH SIM=verilator \
      ../../.venv-sim/bin/pytest -q test_p2_zsad.py
"""
import logging
import os
import random
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
from zsad_model import match, SCORE_SAT, REJECT_SAD   # noqa: E402

BOARD_MAC, BOARD_IP = "02:00:0a:08:64:e6", "10.8.100.230"
HOST_MAC, HOST_IP, HOST_PORT = "5a:51:52:53:54:55", "10.8.100.45", 5678
PORT, ROI = 1234, 80
HDR = struct.Struct("<HIHHH")
RES = struct.Struct("<HHIHHHHIIIIHHI")
F = ("magic", "flags", "frame_id", "rows_seen", "rows_bad", "height", "width", "checksum",
     "t_rx_start", "t_rx_end", "t_result", "x", "y", "score")


def row_pkt(fid, row, w, h, pix, magic=0x5AA5):
    return HDR.pack(magic, fid, row, w, h) + bytes(pix)


def tmpl_pkt(t, extra=b""):
    return struct.pack("<H", 0x5AA6) + bytes(t.astype(np.uint8).ravel()) + extra


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
        self.results = []
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
        t = Timer(12, "ns")                   # 41.67 MHz
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
                self.results.append(dict(zip(F, RES.unpack(d))))
            else:
                raise AssertionError(f"unexpected frame: {pkt!r}")

    async def send(self, payload, dport=PORT, fcs_bad=False):
        pkt = (Ether(src=HOST_MAC, dst=BOARD_MAC) / IP(src=HOST_IP, dst=BOARD_IP)
               / UDP(sport=HOST_PORT, dport=dport) / payload)
        fr = GmiiFrame.from_payload(pkt.build())
        if fcs_bad:
            fr.data[-1] ^= 0xFF
        await self.phy.rx.send(fr)

    async def wait_results(self, n, timeout_ns=4_000_000):
        async def w():
            while len(self.results) < n:
                await RisingEdge(self.dut.clk)
        try:
            await with_timeout(w(), timeout_ns, "ns")
        except SimTimeoutError:
            self.log.error("timeout: %d of %d results", len(self.results), n)


def frame_exp(fid, roi_rows, tmpl, flags_base=1, rows_bad=0, tracked=True):
    """Expected result of a complete frame (rows = list of row arrays in order)."""
    roi = np.array(roi_rows, dtype=np.uint8)
    e = dict(magic=0x3CC3, frame_id=fid, rows_seen=len(roi_rows), rows_bad=rows_bad,
             height=ROI, width=ROI, checksum=int(roi.astype(np.int64).sum()) & 0xFFFFFFFF)
    if tracked:
        x, y, z, good = match(roi, tmpl)
        e.update(flags=flags_base | 8 | (4 if good else 0), score=min(z, SCORE_SAT))
        if good:
            e.update(x=x, y=y)
    else:
        e.update(flags=flags_base, score=0, x=0, y=0)
    return e


@cocotb.test()
async def run_test(dut):
    tb = TB(dut)
    await tb.init()
    cocotb.start_soon(tb.collector())
    rng = np.random.default_rng(7)
    exp, names = [], []

    def expect(name, e):
        names.append(name)
        exp.append(e)

    async def settle():
        # one tracked frame in flight at a time, as the host does (see row_stats.v S_WAIT)
        await tb.wait_results(len(exp))

    # warm-up: P1-size frame (untracked) so the board learns the host MAC
    await tb.send(row_pkt(0xEEEEEEEE, 0, 4, 1, b"\0\0\0\0"))
    await tb.wait_results(1, 400_000)
    assert tb.results and tb.results[0]["flags"] == 1, tb.results
    tb.results.clear()

    t1 = rng.integers(0, 256, (16, 16), dtype=np.uint8)
    t2 = rng.integers(0, 256, (16, 16), dtype=np.uint8)

    await tb.send(tmpl_pkt(t1))
    expect("template 1 ack", dict(magic=0x3CC4, checksum=int(t1.sum())))
    await settle()

    def roi_with(t, x, y, noise=0, bright=0):
        r = rng.integers(0, 256, (ROI, ROI)).astype(np.int64)
        if t is not None:
            r[y:y + 16, x:x + 16] = t.astype(np.int64) + bright + rng.integers(-noise, noise + 1, (16, 16))
        return np.clip(r, 0, 255).astype(np.uint8)

    async def send_frame(fid, roi, order=None, skip=()):
        order = range(ROI) if order is None else order
        for r in order:
            if r in skip:
                continue
            await tb.send(row_pkt(fid, r, ROI, ROI, roi[r]))

    fid = 100
    # tracked frames: planted template (exact, noisy, brightness-shifted), corners, and pure noise
    plant = [(0, 0, 0, 0), (64, 64, 0, 0), (33, 17, 3, 0), (5, 60, 0, 25), (40, 40, 8, -20)]
    for (x, y, nz, br) in plant:
        roi = roi_with(t1, x, y, nz, br)
        await send_frame(fid, roi)
        expect(f"tracked planted ({x},{y}) noise {nz} bright {br}", frame_exp(fid, list(roi), t1))
        await settle()
        fid += 1
    roi = roi_with(None, 0, 0)
    await send_frame(fid, roi)
    expect("tracked pure noise (reject expected)", frame_exp(fid, list(roi), t1))
    await settle()
    fid += 1

    # template swap between frames
    await tb.send(tmpl_pkt(t2))
    expect("template 2 ack", dict(magic=0x3CC4, checksum=int(t2.sum())))
    await settle()
    roi = roi_with(t2, 20, 50)
    await send_frame(fid, roi)
    expect("after template swap: t2 at (20,50)", frame_exp(fid, list(roi), t2))
    await settle()
    fid += 1

    # template sent in the middle of a frame: this frame still uses t2, the next one t1
    roi = roi_with(t2, 10, 10)
    for r in range(ROI):
        if r == 40:
            await tb.send(tmpl_pkt(t1))
            expect("template 1 ack (mid-frame)", dict(magic=0x3CC4, checksum=int(t1.sum())))
        await tb.send(row_pkt(fid, r, ROI, ROI, roi[r]))
    expect("frame with mid-frame template: still t2", frame_exp(fid, list(roi), t2))
    await settle()
    fid += 1
    roi = roi_with(t1, 30, 5)
    await send_frame(fid, roi)
    expect("next frame uses t1", frame_exp(fid, list(roi), t1))
    await settle()
    fid += 1

    # out-of-order rows: complete but untracked; the next frame must still track correctly
    roi = roi_with(t1, 12, 12)
    order = list(range(ROI))
    order[10], order[11] = order[11], order[10]
    await send_frame(fid, roi, order=order)
    expect("rows 10/11 swapped: complete, untracked", frame_exp(fid, list(roi), t1, tracked=False))
    await settle()
    fid += 1
    roi = roi_with(t1, 50, 25)
    await send_frame(fid, roi)
    expect("tracked after out-of-order frame", frame_exp(fid, list(roi), t1))
    await settle()
    fid += 1

    # incomplete frame (rows 0-39), closed by the next frame
    roi = roi_with(t1, 1, 1)
    await send_frame(fid, roi, order=range(40))
    expect("incomplete frame closed by next", dict(magic=0x3CC3, frame_id=fid, flags=2, rows_seen=40, rows_bad=0,
                                                   checksum=int(roi[:40].astype(np.int64).sum()) & 0xFFFFFFFF,
                                                   x=0, y=0, score=0))
    fid += 1
    roi = roi_with(t1, 60, 2)
    await send_frame(fid, roi)
    expect("tracked after incomplete frame", frame_exp(fid, list(roi), t1))
    await settle()
    fid += 1

    # bad row (bad magic) then the same row re-sent good; FCS-bad row then re-sent
    roi = roi_with(t1, 22, 44)
    for r in range(ROI):
        if r == 5:
            await tb.send(row_pkt(fid, r, ROI, ROI, roi[r], magic=0x1111))
        if r == 30:
            await tb.send(row_pkt(fid, r, ROI, ROI, roi[r]), fcs_bad=True)
        await tb.send(row_pkt(fid, r, ROI, ROI, roi[r]))
    expect("bad-magic row + FCS-bad row, both re-sent", frame_exp(fid, list(roi), t1, rows_bad=1))
    await settle()
    fid += 1

    # short row (79 px) inside an ROI frame: dropped as bad; frame completes with the re-sent row
    roi = roi_with(t1, 44, 3)
    for r in range(ROI):
        if r == 70:
            await tb.send(row_pkt(fid, r, ROI, ROI, roi[r][:79]))
        await tb.send(row_pkt(fid, r, ROI, ROI, roi[r]))
    expect("79-px row dropped, re-sent", frame_exp(fid, list(roi), t1, rows_bad=1))
    await settle()
    fid += 1

    # P1-size frame (32x8) in between: untracked; bad template packet: no ack
    p1 = rng.integers(0, 256, (8, 32), dtype=np.uint8)
    for r in range(8):
        await tb.send(row_pkt(fid, r, 32, 8, p1[r]))
    expect("P1-size frame untracked", dict(magic=0x3CC3, frame_id=fid, flags=1, rows_seen=8, width=32, height=8,
                                           checksum=int(p1.astype(np.int64).sum()), x=0, y=0, score=0))
    fid += 1
    await tb.send(tmpl_pkt(t2, extra=b"\x00"))         # 257 bytes: wrong length, no ack
    roi = roi_with(t1, 7, 64)
    await send_frame(fid, roi)
    expect("bad template ignored, t1 still active", frame_exp(fid, list(roi), t1))
    fid += 1

    await tb.wait_results(len(exp))
    for _ in range(4000):
        await RisingEdge(dut.clk)

    got = list(tb.results)
    bad = 0
    for i, (n, e) in enumerate(zip(names, exp)):
        g = got[i] if i < len(got) else None
        ok = g is not None and all(g[k] == v for k, v in e.items())
        if ok and g["magic"] == 0x3CC3 and g["flags"] & 8:
            ok = g["t_rx_start"] <= g["t_rx_end"] <= g["t_result"]
        tb.log.info("%-48s %s", n, "PASS" if ok else "FAIL")
        if not ok:
            bad += 1
            tb.log.error("  expected %s", e)
            tb.log.error("  got      %s", None if g is None else {k: g[k] for k in F})
    if len(got) > len(exp):
        tb.log.error("%d extra results: %s", len(got) - len(exp), got[len(exp):])
    lat = [(g["t_result"] - g["t_rx_end"]) for g in got if g["magic"] == 0x3CC3 and g["flags"] & 8]
    if lat:
        tb.log.info("tracker latency after the last row: %d..%d cycles of 125 MHz", min(lat), max(lat))
    assert len(got) == len(exp), f"{len(got)} results, expected {len(exp)}"
    assert bad == 0, f"{bad} checks failed"


# cocotb-test runner
rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "rtl"))
proc_dir = os.path.abspath(os.path.join(tests_dir, "..", "..", "..", "rtl", "processing"))
eth_rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "lib", "eth", "rtl"))
axis_rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "lib", "eth", "lib", "axis", "rtl"))


def test_p2_zsad(request):
    eth = ["eth_mac_1g_rgmii_fifo", "eth_mac_1g_rgmii", "iddr", "oddr", "ssio_ddr_in",
           "rgmii_phy_if", "eth_mac_1g", "axis_gmii_rx", "axis_gmii_tx", "lfsr", "eth_axis_rx",
           "eth_axis_tx", "udp_complete", "udp_checksum_gen", "udp", "udp_ip_rx", "udp_ip_tx",
           "ip_complete", "ip", "ip_eth_rx", "ip_eth_tx", "ip_arb_mux", "arp", "arp_cache",
           "arp_eth_rx", "arp_eth_tx", "eth_arb_mux"]
    axis = ["arbiter", "priority_encoder", "axis_fifo", "axis_async_fifo", "axis_async_fifo_adapter"]
    srcs = [os.path.join(rtl_dir, f) for f in ("fpga_core.v", "row_stats.v", "zsad_core.sv", "hex_display.v")]
    srcs += [os.path.join(proc_dir, f) for f in ("line_buffer.sv", "window_buffer.sv", "template_match.sv")]
    srcs += [os.path.join(eth_rtl_dir, f + ".v") for f in eth]
    srcs += [os.path.join(axis_rtl_dir, f + ".v") for f in axis]
    cocotb_test.simulator.run(
        python_search=[tests_dir, host_dir],
        verilog_sources=srcs,
        toplevel="fpga_core",
        module=os.path.splitext(os.path.basename(__file__))[0],
        sim_build=os.path.join(tests_dir, "sim_build"),
        compile_args=["-Wno-fatal", "-Wno-WIDTH", "-Wno-LATCH", "-Wno-MULTIDRIVEN", "-Wno-UNOPTFLAT",
                      "-Wno-CASEINCOMPLETE", "-Wno-PINMISSING", "-Wno-SYNCASYNCNET", "-O2"],
    )
