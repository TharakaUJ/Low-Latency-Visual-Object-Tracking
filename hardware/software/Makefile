# ==============================================================================
# CONFIGURATION
# ==============================================================================

# QUARTUS_ROOTDIR should point to:
#   <IntelFPGA installation>/quartus
#
# Example:
#   export QUARTUS_ROOTDIR=$HOME/intelFPGA_lite/25.3/quartus
#
HOST_INSTALL_PATH := $(abspath $(QUARTUS_ROOTDIR)/..)
PROJECT_ROOT := $(abspath ../..)
BSP_DIR := $(abspath ./bsp)
APP_DIR := $(abspath ./app)
SRC_MAIN := $(abspath ./src/main.c)
SOPCINFO := $(PROJECT_ROOT)/hardware/rtl/soc_system/microcontroller.sopcinfo

IMAGE_NAME         := niosv-env
CONTAINER_WORK_DIR := /workspace


# ==============================================================================
# TARGETS
# ==============================================================================

.PHONY: build shell clean check bsp app download firmware

# Build the Docker image
build:
	@echo "Building Nios V Docker image..."
	docker build \
		-t $(IMAGE_NAME) \
		-f ./toolchain/dockerfile \
		.


# Start an interactive Nios V shell
#
# The IntelFPGA installation is mounted read-only because the container
# only needs the Nios V/RiscFree tools.
#
# The current project directory is mounted as /workspace so that
# firmware sources and build artifacts remain on the host.
shell: build
	@echo "Launching Nios V shell inside Docker..."
	docker run -it --rm \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		-v "$$(pwd):$(CONTAINER_WORK_DIR)" \
		-w "$(CONTAINER_WORK_DIR)" \
		$(IMAGE_NAME)


# Verify that the expected Nios V tools are available
check: build
	@echo "Checking Nios V toolchain..."
	docker run --rm \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		$(IMAGE_NAME) \
		bash -c '\
			echo "=== Toolchain ==="; \
			echo "riscv32-gcc: $$(which riscv32-unknown-elf-gcc)"; \
			echo "niosv-bsp:   $$(which niosv-bsp)"; \
			echo "niosv-app:   $$(which niosv-app)"; \
			echo "cmake:       $$(which cmake)"; \
			echo "make:        $$(which make)"; \
			echo ""; \
			echo "=== Versions ==="; \
			riscv32-unknown-elf-gcc --version | head -n 1; \
			cmake --version | head -n 1; \
		'


# Regenerate the BSP from the SOPC design.
bsp:
	niosv-bsp -c --type=hal --sopcinfo=$(SOPCINFO) $(BSP_DIR)/settings.bsp


# Build the application from the BSP and source file.
app: bsp
	niosv-app --app-dir=$(APP_DIR) --bsp-dir=$(BSP_DIR) --srcs=$(SRC_MAIN)


# Download the built ELF to the target.
download: app
	cd $(APP_DIR) && niosv-download -g app.elf -i 0 -d 0 -c 1


# Full firmware flow: BSP, app, and download.
firmware: download


# Remove the Docker image
clean:
	@echo "Removing Nios V Docker image..."
	docker rmi $(IMAGE_NAME) 2>/dev/null || true