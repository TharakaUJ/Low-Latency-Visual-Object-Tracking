TEST ?= matcher

BUILD_DIR := build
TEST_FILE := tests/$(TEST).f
OUTPUT := $(BUILD_DIR)/$(TEST).vvp

.PHONY: sim run clean

sim:
	mkdir -p $(BUILD_DIR)
	iverilog -g2012 -o $(OUTPUT) -c $(TEST_FILE)

run: sim
	vvp $(OUTPUT)

clean:
	rm -rf $(BUILD_DIR)

sim_all:
	@for test in $(shell ls tests/*.f); do \
		test_name=$$(basename $$test .f); \
		echo "==============================="; \
		echo "Running test: $$test_name"; \
		echo "==============================="; \
		make TEST=$$test_name run; \
	done