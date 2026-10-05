# DE2-115 Ethernet hardware-in-the-loop tracking demo: one entry point for build, program, simulate, run.
# Run on the server from hardware/ethernet/.  `make help` lists the targets.
#
# Bitstreams (all JTAG/volatile: reprogram after a power cycle):
#   p1  = p1_rows           P1 row protocol + checksums (loopback, fault tests)       40-byte results
#   p2  = p2_zsad           P2 ZSAD, server-side 80x80 crop (board-tested 2026-10-06) 40-byte results
#   zsad= p3_track zsad     P3 ZSAD, crop in the RTL or server, no in-flight limit    44-byte results
#   s3x8= p3_track s3x8     P3 S-3x8 (E48), crop in the RTL or server                 44-byte results

QUARTUS_BIN ?= $(HOME)/altera_lite/25.1std/quartus/bin
HDL_BIN     ?= $(HOME)/tools/mamba/envs/hdl/bin
PY          ?= python3
VENV        := $(CURDIR)/.venv-sim
BOARD_IP    ?= 10.8.100.230
SEQ         ?= Walking
TRACKER     ?= zsad
CROP        ?= fpga
FRAMES      ?= 0
FPS         ?= 30
RESULTS     := $(CURDIR)/results

QPATH := PATH=$(QUARTUS_BIN):$$PATH
SOF_p1   := p1_rows/fpga/fpga.sof
SOF_p2   := p2_zsad/fpga/fpga.sof
SOF_zsad := p3_track/fpga_zsad/fpga.sof
SOF_s3x8 := p3_track/fpga_s3x8/fpga.sof

.PHONY: help venv-sim build-p1 build-p2 build-zsad build-s3x8 build-all \
        program-p1 program-p2 program-zsad program-s3x8 jtag \
        sim-p1 sim-p2 sim-zsad sim-s3x8 sim-all \
        loopback faults stress-p2 offline check check-all demo demo-loop timing

help:
	@echo "Build (Quartus Lite):  make build-p1 | build-p2 | build-zsad | build-s3x8 | build-all"
	@echo "Program over JTAG:     make program-p1 | program-p2 | program-zsad | program-s3x8   (make jtag = list cable)"
	@echo "Simulate (cocotb):     make sim-p1 (icarus) | sim-p2 | sim-zsad | sim-s3x8 (Verilator 5) | sim-all"
	@echo "Timing summary:        make timing"
	@echo "Board tests:"
	@echo "  P1 bitstream:        make loopback | faults"
	@echo "  P2 bitstream:        make stress-p2"
	@echo "  P3 bitstream:        make check TRACKER=zsad|s3x8 CROP=fpga|server SEQ=Walking FRAMES=0"
	@echo "                       make check-all TRACKER=...   (4 demo sequences, both crop modes)"
	@echo "                       make demo TRACKER=... CROP=... SEQ=...   (live page http://100.76.229.14:8090/)"
	@echo "Offline model (no board): make offline   (ZSAD over OTB-100)"
	@echo "Variables: BOARD_IP=$(BOARD_IP) SEQ=$(SEQ) TRACKER=$(TRACKER) CROP=$(CROP) FRAMES=$(FRAMES) FPS=$(FPS)"

# ---------------------------------------------------------------- setup
venv-sim: $(VENV)/bin/pytest
$(VENV)/bin/pytest:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -q "cocotb==1.9.2" cocotb-test cocotbext-eth scapy pytest numpy

# ---------------------------------------------------------------- build
build-p1:
	cd p1_rows && $(QPATH) $(MAKE) SHELL=/bin/bash
build-p2:
	cd p2_zsad && $(QPATH) $(MAKE) SHELL=/bin/bash
build-zsad:
	cd p3_track && $(QPATH) $(MAKE) zsad
build-s3x8:
	cd p3_track && $(QPATH) $(MAKE) s3x8
build-all: build-p1 build-p2 build-zsad build-s3x8

timing:
	@for d in p1_rows/fpga p2_zsad/fpga p3_track/fpga_zsad p3_track/fpga_s3x8; do \
	  [ -f $$d/fpga.sta.rpt ] || continue; echo "== $$d"; \
	  grep -h -E "^; Total logic elements  |^; Total memory bits  |^; Embedded Multiplier 9" $$d/fpga.fit.rpt | head -3; \
	  grep -A9 "Slow 1200mV 85C Model Setup Summary" $$d/fpga.sta.rpt | grep -E "^; (alt|enet)" | sed "s/altpll_component|auto_generated|pll1|//"; \
	done

# ---------------------------------------------------------------- program
jtag:
	$(QUARTUS_BIN)/jtagconfig
program-%:
	@test -f "$(SOF_$*)" || (echo "no bitstream $(SOF_$*): run make build-$*"; exit 1)
	$(QUARTUS_BIN)/quartus_pgm --no_banner --mode=jtag -o "P;$(SOF_$*)"

# ---------------------------------------------------------------- simulate
sim-p1: venv-sim
	cd p1_rows/tb && SIM=icarus $(VENV)/bin/pytest -q test_p1_rows.py
sim-p2: venv-sim
	cd p2_zsad/tb && PATH=$(HDL_BIN):$$PATH SIM=verilator $(VENV)/bin/pytest -q -rA test_p2_zsad.py
sim-zsad: venv-sim
	cd p3_track/tb && PATH=$(HDL_BIN):$$PATH SIM=verilator TRACKER=zsad $(VENV)/bin/pytest -q -rA test_p3.py
sim-s3x8: venv-sim
	cd p3_track/tb && PATH=$(HDL_BIN):$$PATH SIM=verilator TRACKER=s3x8 $(VENV)/bin/pytest -q -rA test_p3.py
sim-all: sim-p1 sim-p2 sim-zsad sim-s3x8

# ---------------------------------------------------------------- board tests and demo
loopback:
	cd host && $(PY) eth_loopback.py --ip $(BOARD_IP) --fps $(FPS) --frames 10000 --out $(RESULTS)/loopback_fps$(FPS)
faults:
	cd host && $(PY) eth_faults.py --ip $(BOARD_IP) --out $(RESULTS)/faults
stress-p2:
	cd host && $(PY) p2_stress.py --ip $(BOARD_IP) --mode inflight --frames 5000 --out $(RESULTS)/p2_stress_inflight
	cd host && $(PY) p2_stress.py --ip $(BOARD_IP) --mode burst --frames 2000 --out $(RESULTS)/p2_stress_burst
offline:
	cd host && $(PY) zsad_offline.py --roi 80 --target-px 16 --out $(RESULTS)/p2_offline
check:
	cd host && $(PY) check3.py --ip $(BOARD_IP) --tracker $(TRACKER) --crop $(CROP) --seq $(SEQ) --frames $(FRAMES) \
	  --fps $(FPS) --out $(RESULTS)/p3_check_$(TRACKER)_$(CROP)_$(SEQ)
check-all:
	for s in Walking Jumping BlurOwl Bolt; do for c in fpga server; do \
	  $(MAKE) --no-print-directory check TRACKER=$(TRACKER) CROP=$$c SEQ=$$s || exit 1; done; done
demo:
	cd host && $(PY) demo.py --ip $(BOARD_IP) --tracker $(TRACKER) --crop $(CROP) --source otb --seq $(SEQ) --fps $(FPS) \
	  --out $(RESULTS)/demo3_$(TRACKER)_$(CROP)_$(SEQ)
demo-loop:
	cd host && $(PY) demo.py --ip $(BOARD_IP) --tracker $(TRACKER) --crop $(CROP) --source otb --seq $(SEQ) --fps $(FPS) \
	  --loop --no-video --out $(RESULTS)/demo3_loop
