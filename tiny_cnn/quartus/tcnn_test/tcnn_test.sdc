# tcnn_test.sdc -- timing constraints for the Tiny-CNN engine test system.
#
# Single 50 MHz clock domain (CLOCK_50) for the whole system, including
# tcnn_avalon_slave/tcnn_core. All 4 conv_layer stages were designed and
# Verilator-verified around a fixed 1024-cycle/tile budget with margin
# (measured 1037 cycles/tile in Gate C1/F1), specifically to avoid the old
# fpga_cnn_pipeline project's B19 single-cycle MAC-accumulate timing
# failure -- see tiny_cnn/docs/implementation_plan.md's "Timing rules"
# section (no combinational RAM-output-to-multiplier path, at most 2 adder
# levels between registers, no wide muxes on MAC operands).

create_clock -name CLOCK_50 -period 20.000 [get_ports CLOCK_50]
derive_clock_uncertainty

# KEY[0] is an async, synchronously-deasserted reset -- not a clock, and its
# path into the design is a reset network, not a timed data path.
set_false_path -from [get_ports {KEY[0]}]

# status LEDs are slow, human-observed outputs -- not timing-critical.
set_false_path -to [get_ports {LEDG[*]}]
set_false_path -to [get_ports {LEDR[*]}]

# JTAG (programming + the JTAG UART's own hub) is constrained by the
# jtag_uart/altera_jtag_sld_node IP's own internal SDC, not this file.
