# DE2-115 Ethernet hardware-in-the-loop tracking

The server (PC) sends grayscale frames to the DE2-115 over Gigabit Ethernet, one UDP packet per image row. The FPGA tracks the target and sends back one small result packet per frame. The server never gets the frame back: it draws the box on its own copy and checks every result against a bit-exact host model ("FPGA = model").

Call it hardware in the loop, not "on the drone". Scaling to a ~16 px target always runs on the server. The ROI crop runs on the server (P2, P3 `CROP=server`) or in the FPGA (P3 `CROP=fpga`).

Running log with every measurement: `docs/demo_log.md`.

## Quick start (on the server, in `hardware/ethernet/`)
```
make help                         # all targets
make build-zsad                   # Quartus build (~3 min); build-s3x8 ~9 min
make program-zsad                 # JTAG (volatile: reprogram after a power cycle)
make check TRACKER=zsad CROP=fpga SEQ=Walking         # board vs model, whole sequence
make demo  TRACKER=zsad CROP=fpga SEQ=Walking         # live page: http://100.76.229.14:8090/ (Tailscale)
make sim-zsad                     # cocotb + Verilator testbench (no board needed)
```

## Setup
- **Board:** DE2-115, ENET0 port, jumper JP1 on pins 1-2 (RGMII). SW14/SW15 select the 7-segment view (see below); SW0/SW1 do not work on this board.
- **Network:** lab LAN `10.8.100.0/24`. The board has static IP `10.8.100.230` (picked as free with nmap; not reserved: if DHCP ever hands it out, change `local_ip` in `rtl/fpga_core.v`), MAC `02:00:0a:08:64:e6`. It answers ARP; there is no ICMP, so `ping` does not work. If ARP fails, re-seat the cable: on 2026-10-05 the first jack/cable reached another segment (10.8.96.x).
- **Tools:**
  - Quartus Prime Lite 25.1std in `~/altera_lite`.
  - Verilator 5.052 and iverilog 13 in a user-space micromamba env, `~/tools/mamba/envs/hdl` (apt has iverilog 11 and Verilator 4.038, both too old for `template_match.sv` / cocotb).
  - Python sim env `.venv-sim` (`make venv-sim`).
  - The host scripts use the system `python3` (numpy, opencv) and read OTB-100 from the research tree (read-only).
- **Builds:** `make` inside a project uses `SHELL=/bin/bash`: the upstream `quartus.mk` uses bash `let` and hangs under dash.

## Flash: boot the demo without the USB cable
The FPGA forgets its design at power-off. To run with only the Ethernet cable, write a P3 design to the
board's EPCS64 flash once over the USB-Blaster; the board then loads it at every power-up (SW19 = RUN).
1. `make flash-backup`: reads the factory image (Terasic default demo) to
   `~/fpga_flash_backup/de2_115_epcs64_factory.pof` (+ `.sha256`). Once; it never overwrites the backup.
2. `make flash-check-backup`: the flash still matches the backup (checks the backup can be used to restore).
3. `make flash-zsad` or `make flash-s3x8`: writes and verifies the design (.jic). Refuses without a backup.
4. Unplug USB, plug Ethernet, power-cycle: the board answers on 10.8.100.230 as with `make program-...`.
5. Before returning the board: `make flash-restore` (USB again), power-cycle: the factory demo is back.
Only one design is in the flash at a time; switching tracker = step 3 again.

## Layout
| path | what |
|---|---|
| `third_party/verilog-ethernet` | alexforencich/verilog-ethernet @ 77320a9 (MIT): RGMII MAC, ARP/IP/UDP |
| `p1_echo/` | upstream DE2-115 UDP echo with our IP and debug LEDs (bring-up only) |
| `p1_rows/` | P1: row protocol, per-frame row count and pixel checksum (`rtl/row_stats.v`) |
| `p2_zsad/` | P2: + ZSAD tracker on a server-cropped 80×80 ROI (`rtl/row_stats.v`, `rtl/zsad_core.sv`) |
| `p3_track/` | P3: crop in the RTL, FPGA-held position, swappable tracker, no in-flight limit |
| `p3_track/fpga_zsad`, `p3_track/fpga_s3x8` | the two Quartus projects of P3 (same RTL, macro `TRACKER_S3X8`) |
| `host/` | server-side tools (protocol, models, checks, demo, stress, offline) |
| `results/` | `summary.md` per run (videos, raw data and per-frame CSVs are git-ignored) |

The user's tracker RTL in `hardware/rtl/processing/` (`window_buffer`, `line_buffer`, `template_match`) is used **unchanged**. So is the E48 S-3x8 RTL (`p3_track/rtl/s3x8_top.v`, see its PROVENANCE file).

## Clocks and data path (P3)
```
ENET0 RGMII ── verilog-ethernet MAC/UDP (125 MHz) ── row_stats (125 MHz) ──► axis_async_fifo ──► tracker core (clk_trk)
                                                       │  ◄─────────────── result (toggle + data) ───────────┘
                                                       └─► result packet (UDP)
```
| build | tracker core | ROI | template | clk_trk | resources (P3) |
|---|---|---|---|---|---|
| zsad | `zsad_core.sv` → `window_buffer` + `template_match` (ZSAD, reject > 8192 = hold) | 80 | 256 B gray | 41.67 MHz (template_match Fmax ~47) | 27 % LE, 0 mult |
| s3x8 | `s3x8_core.sv` → `s3x8_top` (3 conv × 8 ch int8, L1, 49 × 49) | 72 | 2048 B int8 features | 62.5 MHz (E48 Fmax 77) | 54 % LE, 60 mult |

## Protocol (UDP port 1234, little-endian)
**Downlink**
- Row: `0x5AA5, frame_id u32, row u16, width u16, height u16` + `width` pixels.
- Template chunk (P3): `0x5AA6, offset u16` + bytes. P2 uses `0x5AA6` + 256 bytes, with no offset.
- Set position (P3): `0x5AA7, tx u16, ty u16`. This is the top-left of the 16×16 target window, in frame pixels.

**Uplink**
- P1/P2: 40 bytes. P3: 44 bytes (`+ roi_x u16, roi_y u16`).
- Fields:
  - `magic`: 0x3CC3 frame, 0x3CC4 template ack, 0x3CC5 position ack
  - `flags`
  - `frame_id`, `rows_seen`, `rows_bad`, `height`, `width`
  - `checksum`: sum of the good-row pixels
  - `t_rx_start`, `t_rx_end`, `t_result`: 125 MHz cycle counter
  - `x`, `y`: P2 = best position in the ROI; P3 = the FPGA's new target position in frame pixels
  - `score`
- Flags: bit0 complete, bit1 closed by a newer frame, bit2 good, bit3 tracked, bit4 tracker timeout, bit5 cropped in the RTL.

**Rules**
- A frame closes when all rows have arrived, or when a row of another frame_id arrives (marked incomplete).
- It is tracked only if it is complete, its rows arrived in order, and it is at least ROI × ROI.
- P3 crop: `origin = clamp(t − (ROI−16)/2, 0, size − ROI)`. After a good result, `t = origin + best + MARGIN` (MARGIN 0 for ZSAD, 4 for S-3x8). A frame of exactly ROI × ROI has origin (0, 0), which is the server-crop mode. Frames smaller than the ROI are padded by the server.
- **Pipelining (P3):**
  - The receiver keeps running while the tracker works, with one pending result.
  - It stalls only (a) at the first row of a cropped frame while the previous result is still outstanding, because the new origin depends on it, or (b) when a second trackable frame completes while one result is pending.
  - P2 stopped receiving for every tracked frame. Back-to-back 80×80 frames at line rate lost rows there (`results/p2_stress_burst`).

## Board status display (all bitstreams)
- **LEDG:** 0-1 link speed (2 = 1000), 2 good RX frame seen, 3 bad FCS seen, 4 bad frame seen, 5 ARP seen, 6 frame to our MAC seen, 7 frame sent.
- **LEDR17 (P3 s3x8):** E48 line overrun seen (should stay off).
- **7-segment views:** both down = frames done | bad rows; SW14 = last RX source IP; SW15 = last RX destination IP; both up = MAC bad-FCS | good counts.

## Results so far (details and commands in `docs/demo_log.md`)
- **P1:** 10 000 frames 640×480 at 30 fps and at max rate (886 Mbit/s): 0 lost, 0 bad, 0 checksum errors. Fault injection 20/20 in simulation, 19/19 on the board.
- **P2 (ZSAD, server crop):** FPGA = model on every frame:
  - Walking 411/411, Jumping 312/312, BlurOwl 630/630, Bolt 349/349; a looped run 3875/3875.
  - Tracker time 157 µs per 80×80 frame at line rate.
- **P3: WORK IN PROGRESS, not yet working.** Both builds fit (zsad 27 % LE; s3x8 54 % LE, 60 multipliers, timing met). The host S-3x8 model is bit-exact with the E48 RTL reference cases. But the P3 ZSAD testbench fails: the tracker returns no result for the first FPGA-crop frame (receiver timeout after 10 ms), and nothing comes back after that. Debug plan and board test list: `docs/NEXT_SESSION.md`.

## Regenerate everything
`make build-all && make sim-all`, then with the board: `make program-p1 loopback faults`, `make program-p2 stress-p2`, `make program-zsad check-all TRACKER=zsad`, `make program-s3x8 check-all TRACKER=s3x8`.
