"""cocotb testbench: p1_rows fpga_core (MAC + UDP stack + row_stats) over a simulated RGMII PHY.

Sends every case of host/fault_cases.py and checks each result packet against host/row_model.py.
Run:  cd hardware/ethernet/p1_rows/tb && ../../.venv-sim/bin/pytest -q test_p1_rows.py
"""
import logging
import os
import sys

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
from fault_cases import build_cases, expected          # noqa: E402
from row_model import CHECKED, parse_result, row_packet, RES      # noqa: E402

BOARD_MAC, BOARD_IP = "02:00:0a:08:64:e6", "10.8.100.230"
HOST_MAC, HOST_IP, HOST_PORT = "5a:51:52:53:54:55", "10.8.100.45", 5678


class TB:
    def __init__(self, dut):
        self.dut = dut
        self.log = SimLog("cocotb.tb")
        self.log.setLevel(logging.INFO)
        self.phy = RgmiiPhy(dut.phy0_txd, dut.phy0_tx_ctl, dut.phy0_tx_clk,
                            dut.phy0_rxd, dut.phy0_rx_ctl, dut.phy0_rx_clk, speed=1000e6)
        self.phy1 = RgmiiPhy(dut.phy1_txd, dut.phy1_tx_ctl, dut.phy1_tx_clk,
                             dut.phy1_rxd, dut.phy1_rx_ctl, dut.phy1_rx_clk, speed=1000e6)
        dut.phy0_int_n.setimmediatevalue(1)
        dut.phy1_int_n.setimmediatevalue(1)
        dut.btn.setimmediatevalue(0)
        dut.sw.setimmediatevalue(0)
        dut.clk.setimmediatevalue(0)
        dut.clk90.setimmediatevalue(0)
        self.results = []
        cocotb.start_soon(self._run_clk())
        for name in ("cocotb.fpga_core.phy0_rxd", "cocotb.fpga_core.phy0_txd",
                     "cocotb.fpga_core.phy1_rxd", "cocotb.fpga_core.phy1_txd"):
            logging.getLogger(name).setLevel(logging.WARNING)

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

    async def init(self):
        self.dut.rst.setimmediatevalue(0)
        for _ in range(10):
            await RisingEdge(self.dut.clk)
        self.dut.rst.value = 1
        for _ in range(10):
            await RisingEdge(self.dut.clk)
        self.dut.rst.value = 0

    async def collector(self):
        """Answer the board's ARP request for the host and collect result packets."""
        while True:
            f = await self.phy.tx.recv()
            pkt = Ether(bytes(f.get_payload()))
            if ARP in pkt and pkt[ARP].op == 1:
                assert pkt[ARP].pdst == HOST_IP and pkt[ARP].psrc == BOARD_IP
                rsp = Ether(src=HOST_MAC, dst=BOARD_MAC) / ARP(
                    hwtype=1, ptype=0x0800, hwlen=6, plen=4, op=2, hwsrc=HOST_MAC, psrc=HOST_IP,
                    hwdst=BOARD_MAC, pdst=BOARD_IP)
                await self.phy.rx.send(GmiiFrame.from_payload(rsp.build()))
            elif UDP in pkt:
                assert pkt[IP].src == BOARD_IP and pkt[IP].dst == HOST_IP
                assert pkt[UDP].sport == 1234 and pkt[UDP].dport == HOST_PORT
                data = bytes(pkt[UDP].payload)
                assert len(data) == RES.size, len(data)
                self.results.append(parse_result(data))
            else:
                raise AssertionError(f"unexpected frame from the board: {pkt!r}")

    async def send(self, dport, payload, fcs_bad):
        pkt = (Ether(src=HOST_MAC, dst=BOARD_MAC) / IP(src=HOST_IP, dst=BOARD_IP)
               / UDP(sport=HOST_PORT, dport=dport) / payload)
        frame = GmiiFrame.from_payload(pkt.build())
        if fcs_bad:
            frame.data[-1] ^= 0xFF           # last byte = FCS
        await self.phy.rx.send(frame)


@cocotb.test()
async def run_test(dut):
    tb = TB(dut)
    await tb.init()
    cocotb.start_soon(tb.collector())

    # warm-up: one 1-row frame so the board resolves the host MAC (ARP) before the cases;
    # otherwise the ARP reply would queue behind all case packets and results would be dropped
    await tb.send(1234, row_packet(0xEEEEEEEE, 0, 4, 1, b"\x00\x00\x00\x00"), False)
    async def wait_one():
        while len(tb.results) < 1:
            await RisingEdge(dut.clk)
    await with_timeout(wait_one(), 200_000, "ns")
    assert tb.results[0]["frame_id"] == 0xEEEEEEEE and tb.results[0]["flags"] == 1
    tb.results.clear()

    cases = build_cases()
    exp = expected(cases)
    n_exp = sum(len(e) for e in exp)
    for case in cases:
        for dport, payload, fcs_bad in case["packets"]:
            await tb.send(dport, payload, fcs_bad)

    async def wait_all():
        while len(tb.results) < n_exp:
            await RisingEdge(dut.clk)
    try:
        await with_timeout(wait_all(), 2_000_000, "ns")
    except SimTimeoutError:
        tb.log.error("timeout: %d of %d results received", len(tb.results), n_exp)
    for _ in range(2000):                      # catch any extra result
        await RisingEdge(dut.clk)

    got = list(tb.results)
    flat = [e for es in exp for e in es]
    for i in range(max(len(got), len(flat))):
        g = {f: got[i][f] for f in CHECKED} if i < len(got) else None
        e = {f: flat[i][f] for f in CHECKED} if i < len(flat) else None
        if g != e:
            tb.log.error("first mismatch at result %d:\n  expected %s\n  got      %s", i, e, g)
            break
    bad = 0
    k = 0
    for case, e in zip(cases, exp):
        g = got[k:k + len(e)]
        k += len(e)
        ok = len(g) == len(e) and all(all(gi[f] == ei[f] for f in CHECKED) for gi, ei in zip(g, e))
        ok = ok and all(gi["t_rx_start"] <= gi["t_rx_end"] <= gi["t_result"] for gi in g)
        tb.log.info("%-45s %s  (%d results)", case["name"], "PASS" if ok else "FAIL", len(e))
        if not ok:
            bad += 1
            tb.log.error("  expected %s", [{f: ei[f] for f in CHECKED} for ei in e])
            tb.log.error("  got      %s", [{f: gi[f] for f in CHECKED} for gi in g])
    assert len(got) == n_exp, f"{len(got)} results, expected {n_exp}"
    assert bad == 0, f"{bad} cases failed"
    assert int(dut.row_stats_inst.state.value) == 0, "row_stats not idle at the end"


# cocotb-test runner
rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "rtl"))
eth_rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "lib", "eth", "rtl"))
axis_rtl_dir = os.path.abspath(os.path.join(tests_dir, "..", "lib", "eth", "lib", "axis", "rtl"))


def test_p1_rows(request):
    eth = ["eth_mac_1g_rgmii_fifo", "eth_mac_1g_rgmii", "iddr", "oddr", "ssio_ddr_in",
           "rgmii_phy_if", "eth_mac_1g", "axis_gmii_rx", "axis_gmii_tx", "lfsr", "eth_axis_rx",
           "eth_axis_tx", "udp_complete", "udp_checksum_gen", "udp", "udp_ip_rx", "udp_ip_tx",
           "ip_complete", "ip", "ip_eth_rx", "ip_eth_tx", "ip_arb_mux", "arp", "arp_cache",
           "arp_eth_rx", "arp_eth_tx", "eth_arb_mux"]
    axis = ["arbiter", "priority_encoder", "axis_fifo", "axis_async_fifo", "axis_async_fifo_adapter"]
    srcs = [os.path.join(rtl_dir, f) for f in ("fpga_core.v", "row_stats.v", "hex_display.v")]
    srcs += [os.path.join(eth_rtl_dir, f + ".v") for f in eth]
    srcs += [os.path.join(axis_rtl_dir, f + ".v") for f in axis]
    cocotb_test.simulator.run(
        python_search=[tests_dir, host_dir],
        verilog_sources=srcs,
        toplevel="fpga_core",
        module=os.path.splitext(os.path.basename(__file__))[0],
        sim_build=os.path.join(tests_dir, "sim_build"),
    )
