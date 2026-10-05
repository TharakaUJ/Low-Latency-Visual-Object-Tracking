# Ethernet HIL demo log

Plan: object_tracking/presentation/demo/plan_P0_P1.md (approved 2026-10-05).

## 2026-10-05
- P0: JTAG OK (USB-Blaster, device 020F70DD = EP4CE115). Branch ethernet-demo created from 9636bf3 (#17).
- Port ENET0, JP1 = 1-2 (RGMII), confirmed by the user. Link: option C (lab LAN 10.8.100.0/24).
- Board IP 10.8.100.230 chosen by me: nmap -sn shows hosts .6-.50 (the DHCP leases look low), plus .199, .215, .216, .240, .245-.248, .254. .230 gives no ping and no ARP reply (INCOMPLETE). Risk: DHCP could still hand it out later.
- verilog-ethernet cloned to hardware/ethernet/third_party/verilog-ethernet @ 77320a9 (upstream marked it deprecated; the code is unchanged).
- P1 step 1: example/DE2-115 copied to hardware/ethernet/p1_echo. Only change: local_ip 10.8.100.230, gateway 10.8.100.254, local_mac 02:00:0a:08:64:e6 (the default 02:00:00:00:00:00 is too generic for a shared LAN). The required IP change follows from option C; the MAC change is minor.
- Build of p1_echo: 5,570 LEs (5 %), 225,792 memory bits (6 %), timing met (worst setup slack 0.022 ns on the PLL clk[1] = 90-degree TX clock), no critical warnings.
- quartus_pgm over JTAG: configuration succeeded. quartus_pgm works.
- First test: no ARP reply from 10.8.100.230 (neigh FAILED), and 0/200 UDP echoes. Ping is not expected to work, because the example has no ICMP. Next: the user checks the cable and link LEDs on ENET0.
- User: ENET0 cable in, link LEDs on and blinking, LEDG all off, HEX all 0 (HEX shows the dest IP of the last UDP reply, so the board has never replied).
- Debug variant of p1_echo (rtl/fpga_core.v; the original is kept as fpga_core.v.echo_orig). LEDG[1:0] = MAC speed (0=10, 1=100, 2=1000), LEDG2 = good RX frame seen, LEDG3 = bad FCS seen, LEDG4 = bad frame seen, LEDG5 = ARP frame seen, LEDG6 = frame to our MAC seen, LEDG7 = TX frame sent (all sticky). HEX7..4 = bad-FCS count, HEX3..0 = good RX frame count (hex).
- Issue: the example quartus.mk rebuild loop uses the bash "let" builtin and hangs forever under /bin/sh (dash). Fix: run "make SHELL=/bin/bash".
- Debug build: timing met (worst 0.032 ns), programmed. Still 0/20 UDP replies and ARP INCOMPLETE. Waiting for the user to read the LEDs.
- Mistake: I ran "pkill -f make -u tharaka" on the server to stop the hung build. It also killed my own SSH command and would have killed any other process of the user's with "make" in its command line.
- LED readout: LEDG1 (speed = 1000), LEDG2 (good RX), LEDG5 (ARP seen). Off: LEDG3/4 (no bad FCS or bad frames), LEDG6 (no unicast to our MAC), LEDG7 (never transmitted). The good-frame count was climbing (0x202).
- Broadcast test: the server sent 4096 UDP broadcasts to 10.8.100.255:1234 over about 5 s. The board count went from 0x202 to 0x373 (+369), which is background traffic only. The broadcasts did not arrive, and 0 replies came back.
- Conclusion: the board's RGMII RX works (1 Gb/s, no FCS errors). But the server's frames, broadcasts included, do not reach the board's wall port. The board is on a different L2 segment or VLAN from the server's eno1. This is not an FPGA fault. The TX path is still untested.
- Hex IP readout (SW15/SW14 select; SW0/SW1 do not work on this board): last RX src 10.8.96.203, dst 239.255.255.250 (SSDP). The board's port appeared to be on 10.8.96.x. The server reaches 10.8.96.0/24 through the router in one hop. I proposed moving the board to 10.8.96.120; not approved and not needed.
- The user re-seated the Ethernet cable and I reflashed. Now ARP resolves (02:00:0a:08:64:e6 REACHABLE), 50/50 unicast echoes and 4096/4096 broadcast echoes come back. The cause was the cable or jack, not the FPGA.
- P1 step 1 PASSED: 2000 echoes of 1024 B random data: 2000 ok, 0 corrupt, 0 lost. RTT p50 121 us, p95 152, p99 158, max 273 (Python socket, single packet in flight, lab LAN).
- P1 step 2: new design hardware/ethernet/p1_rows = p1_echo (with the debug LEDs) + rtl/row_stats.v replacing the UDP echo and FIFO (applied by p1_rows/rows_patch.py). Build: 6,882 LEs (6 %), timing met (worst setup slack 0.055 ns, PLL clk[0]); the only row_stats warnings are intended counter truncations. Hex default view = frames done | rows bad; SW15+SW14 both up = MAC bad-FCS | good counts.
- Protocol addition vs the plan: the downlink header also carries height u16 (magic, frame_id, row, width, height), so the FPGA knows when a frame ends; the result has 40 bytes (adds flags, height, width; x/y/score = 0). Duplicate rows are not detected (no row bitmap).
- No RTL simulation: there is no iverilog on the server and Questa has no license. Tested on the board directly.
- Host script hardware/ethernet/host/eth_loopback.py. First version measured RTT ~10.8 ms: an artifact of the busy-wait pacing holding the Python GIL (receiver thread waited for the 5 ms switch interval). Fixed: kernel SO_TIMESTAMPNS receive stamps, sleep-based pacing, and an fps formula over N-1 intervals.
- SANITY (10 frames 640x480, 30 fps; results/sanity_random and sanity_ramp): 10/10 results, all 480 rows, 0 bad rows, 0 checksum mismatches, for both patterns. 73.7 Mbit/s pixels. RTT from the last row sent to the result: p50 ~571 us (max 623). The host enqueues a frame in ~2.29 ms but the FPGA receives it over ~2.77 ms (line rate), so ~490 us of the RTT is the NIC queue draining. FPGA last row -> result = 0 cycles (no compute in P1).
- The user approved the long runs and said they will install iverilog (sudo needs a password, so I did not).
- LONG 30 fps (results/long_fps30, 333 s): 10000/10000 results, all frames complete, 0 bad rows, 0 checksum mismatches, 0 lost, 30.0 fps, 73.7 Mbit/s pixels (~83 on the wire). RTT from the last row sent: p50 573, p95 614, p99 645, max 736 us. From the first row sent: p50 2857, max 4506 us.
- LONG max rate (results/long_max, run uncapped as in the plan, 27.7 s): 10000/10000, 0 bad, 0 mismatches, 0 lost, 360.7 fps, 886 Mbit/s pixels (~994 on the wire = gigabit line rate). RTT from the last row: p50 574, p99 612, max 654 us. The FPGA receives a frame in 2772 us (line rate); the link, not the FPGA, is the limit.
- Note: my "wait until done" loop used pgrep -f with a pattern that matched its own command line, so it never ended. I killed exactly those 2 PIDs (70684, 70773).
- P1 DONE. Regenerate: make -C hardware/ethernet/p1_rows SHELL=/bin/bash; quartus_pgm --mode=jtag -o "P;hardware/ethernet/p1_rows/fpga/fpga.sof"; python3 hardware/ethernet/host/eth_loopback.py --fps 30 --frames 10000 --out results/long_fps30 (and --fps 0 for max).
- The user asked for fault injection (and installed iverilog 11.0 and verilator 4.038).
- Python reference model host/row_model.py (same rules as rtl/row_stats.v). Shared cases host/fault_cases.py: 20 cases (skipped, bad, short, long and truncated rows, an empty UDP packet, width 0, row >= height, height 0, an early-ended frame, a bad row with no open frame, a duplicate row (the known limitation), another UDP port, swapped rows, width 1460, frame_id wrap, two interleaved frames, bad Ethernet FCS (testbench only), and a final good frame). Each case ends with a 1-row flush frame.
- cocotb testbench p1_rows/tb/test_p1_rows.py (venv hardware/ethernet/.venv-sim: cocotb 1.9.2, cocotbext-eth 0.1.28, scapy; iverilog). It runs fpga_core (MAC + UDP + row_stats) over a simulated RGMII PHY. First run: 0 results. Testbench bug: the ARP reply to the board was queued behind all case packets, so the board's ARP lookup timed out and its results were dropped. Fixed with an ARP warm-up frame. Then **20/20 cases PASS**, bit-exact against the model, in 14 s.
- Board: host/eth_faults.py (same cases, minus the FCS case) -> **19/19 PASS** (results/faults/summary.md).
- Confirmed: an empty UDP payload is dropped by udp_ip_rx (header early termination) and cannot hang row_stats.
- Run: cd hardware/ethernet/p1_rows/tb && ../../.venv-sim/bin/pytest -q test_p1_rows.py ; python3 hardware/ethernet/host/eth_faults.py --out results/faults
- User decisions for P2: ZSAD first; crop on the server for the demo (in the real system it belongs in the FPGA; say so on screen); source OTB replay now, webcam later (none plugged in yet).

## 2026-10-05 (P2)
- P2 plan (presentation/demo/plan_P2.md) approved by the user. Choices: MJPEG page + MP4, ROI 80x80 (+-32), OTB sequences picked from an offline model run over all of OTB2015 (full table shown), git unstaged + .gitignore (the user staged them; nothing committed). The user will commit the P1 work themselves.
