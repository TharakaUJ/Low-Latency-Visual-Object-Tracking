# P3 builds (Quartus Lite on PATH): make zsad | make s3x8 | make all
.PHONY: all zsad s3x8 clean
all: zsad s3x8
zsad:
	cd fpga_zsad && $(MAKE) SHELL=/bin/bash
s3x8:
	cd fpga_s3x8 && $(MAKE) SHELL=/bin/bash
clean:
	cd fpga_zsad && $(MAKE) clean; cd fpga_s3x8 && $(MAKE) clean
