# ==============================================================================
# CONFIGURATION
# ==============================================================================

# QUARTUS_ROOTDIR should point to:
#   <IntelFPGA installation>/quartus
#
# Example:
#   export QUARTUS_ROOTDIR=$HOME/src/Quartus/Installation/quartus

#
HOST_INSTALL_PATH := $(abspath $(QUARTUS_ROOTDIR)/..)
NIOSV_ROOT := $(HOST_INSTALL_PATH)/niosv
PROJECT_ROOT := $(abspath ..)

IMAGE_NAME         := niosv-env
CONTAINER_WORK_DIR := /workspace

BSP_DIR := $(CONTAINER_WORK_DIR)/firmware/bsp
APP_DIR := $(CONTAINER_WORK_DIR)/firmware/app
SRC_MAIN := $(CONTAINER_WORK_DIR)/firmware/src/main.c
SOPCINFO := $(CONTAINER_WORK_DIR)/rtl/soc_system/microcontroller.sopcinfo

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

# Start an interactive Nios V shell (for manual debugging)
shell: build
	@echo "Launching Nios V shell inside Docker..."
	docker run -it --rm \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		-v "$(PROJECT_ROOT):$(CONTAINER_WORK_DIR)" \
		-w "$(CONTAINER_WORK_DIR)" \
		$(IMAGE_NAME)

# Verify that the expected Nios V tools are available inside the container
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

# Regenerate the BSP from the SOPC design INSIDE the Docker container.
bsp: build
	@echo "Generating BSP inside Docker..."
	docker run --rm \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		-v "$(PROJECT_ROOT):$(CONTAINER_WORK_DIR)" \
		-w "$(CONTAINER_WORK_DIR)" \
		$(IMAGE_NAME) \
		niosv-bsp -c --type=hal --sopcinfo=$(SOPCINFO) $(BSP_DIR)/settings.bsp

# Build the application from the BSP and source file INSIDE the Docker container.
app: bsp
	@echo "Building application inside Docker..."
	docker run --rm \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		-v "$(PROJECT_ROOT):$(CONTAINER_WORK_DIR)" \
		-w "$(CONTAINER_WORK_DIR)" \
		$(IMAGE_NAME) \
		niosv-app --app-dir=$(APP_DIR) --bsp-dir=$(BSP_DIR) --srcs=$(SRC_MAIN)

build_app: app
	@echo "Compiling application inside Docker..."
	docker run --rm \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		-v "$(PROJECT_ROOT):$(CONTAINER_WORK_DIR)" \
		-w "$(APP_DIR)" \
		$(IMAGE_NAME) \
		bash -c "cmake . && make"

# Download the built ELF to the target using hardware pass-through.
download: build_app
	@echo "Downloading firmware via Docker..."
	docker run --rm --privileged -v /dev/bus/usb:/dev/bus/usb \
		-v "$(HOST_INSTALL_PATH):/opt/intelFPGA_lite:ro" \
		-v "$(PROJECT_ROOT):$(CONTAINER_WORK_DIR)" \
		-w "$(CONTAINER_WORK_DIR)/app" \
		$(IMAGE_NAME) \
		niosv-download -g app.elf -i 0 -d 0 -c 1

# Full firmware flow: BSP, app, and download.
firmware: download

# Remove the Docker image
clean:
	@echo "Removing Nios V Docker image..."
	docker rmi $(IMAGE_NAME) 2>/dev/null || true
