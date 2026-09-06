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

IMAGE_NAME         := niosv-env
CONTAINER_WORK_DIR := /workspace


# ==============================================================================
# TARGETS
# ==============================================================================

.PHONY: build shell clean check

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


# Remove the Docker image
clean:
	@echo "Removing Nios V Docker image..."
	docker rmi $(IMAGE_NAME) 2>/dev/null || true