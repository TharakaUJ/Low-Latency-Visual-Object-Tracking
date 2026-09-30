# TCL File for Platform Designer / Qsys component wrapper
#
# module tcnn_avalon_slave (tiny_cnn/rtl/tcnn_avalon_slave.sv)
#
# Register map: tiny_cnn/docs/implementation_plan.md's Avalon register table.
package require -exact qsys 16.1

set_module_property DESCRIPTION "Layer-pipelined Tiny-CNN accelerator: frame_player + tile_feeder + tcnn_core + result_sink behind an Avalon-MM register map"
set_module_property NAME tcnn_avalon_slave
set_module_property VERSION 1.0
set_module_property INTERNAL false
set_module_property OPAQUE_ADDRESS_MAP true
set_module_property GROUP "Tiny-CNN"
set_module_property AUTHOR "User"
set_module_property DISPLAY_NAME "TCNN Avalon Slave"
set_module_property INSTANTIATE_IN_SYSTEM_MODULE true
set_module_property EDITABLE true
set_module_property REPORT_TO_TALKBACK false
set_module_property ALLOW_GREYBOX_GENERATION false
set_module_property REPORT_HIERARCHY false

#
# file sets
#
add_fileset QUARTUS_SYNTH QUARTUS_SYNTH "" ""
set_fileset_property QUARTUS_SYNTH TOP_LEVEL tcnn_avalon_slave
set_fileset_property QUARTUS_SYNTH ENABLE_RELATIVE_INCLUDE_PATHS false
set_fileset_property QUARTUS_SYNTH ENABLE_FILE_OVERWRITE_MODE true

# generated package (defines `TCNN_GEN etc.) -- compiled first
add_fileset_file tcnn_pkg.sv          SYSTEM_VERILOG PATH ../../gen/tcnn_pkg.sv

add_fileset_file adder_tree.sv        SYSTEM_VERILOG PATH ../../rtl/adder_tree.sv
add_fileset_file requant_pipe.sv      SYSTEM_VERILOG PATH ../../rtl/requant_pipe.sv
add_fileset_file fmap_pingpong.sv     SYSTEM_VERILOG PATH ../../rtl/fmap_pingpong.sv
add_fileset_file conv_layer.sv        SYSTEM_VERILOG PATH ../../rtl/conv_layer.sv
add_fileset_file gap_head.sv          SYSTEM_VERILOG PATH ../../rtl/gap_head.sv
add_fileset_file tcnn_core.sv         SYSTEM_VERILOG PATH ../../rtl/tcnn_core.sv
add_fileset_file tile_feeder.sv       SYSTEM_VERILOG PATH ../../rtl/tile_feeder.sv
add_fileset_file frame_player.sv      SYSTEM_VERILOG PATH ../../rtl/frame_player.sv
add_fileset_file result_sink.sv       SYSTEM_VERILOG PATH ../../rtl/result_sink.sv
add_fileset_file tcnn_avalon_slave.sv SYSTEM_VERILOG PATH ../../rtl/tcnn_avalon_slave.sv TOP_LEVEL_FILE

add_fileset SIM_VERILOG SIM_VERILOG "" ""
set_fileset_property SIM_VERILOG TOP_LEVEL tcnn_avalon_slave
set_fileset_property SIM_VERILOG ENABLE_RELATIVE_INCLUDE_PATHS false
set_fileset_property SIM_VERILOG ENABLE_FILE_OVERWRITE_MODE true

#
# parameters
#
add_parameter GEN_DIR STRING "gen/"
set_parameter_property GEN_DIR DEFAULT_VALUE "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn/gen/"
set_parameter_property GEN_DIR DISPLAY_NAME "Generated ROM directory (absolute path, trailing slash)"
set_parameter_property GEN_DIR TYPE STRING
set_parameter_property GEN_DIR UNITS None
set_parameter_property GEN_DIR HDL_PARAMETER true

#
# connection point clk
#
add_interface clk clock end
set_interface_property clk clockRate 50000000
set_interface_property clk ENABLED true
add_interface_port clk clk clk Input 1

#
# connection point reset (active-low, synchronous to clk)
#
add_interface reset reset end
set_interface_property reset associatedClock clk
set_interface_property reset synchronousEdges DEASSERT
set_interface_property reset ENABLED true
add_interface_port reset rst_n reset_n Input 1

#
# connection point avs - Avalon-MM slave (32-bit, word-addressed, 19 registers -> 5-bit address)
#
add_interface avs avalon end
set_interface_property avs addressUnits WORDS
set_interface_property avs associatedClock clk
set_interface_property avs associatedReset reset
set_interface_property avs bitsPerSymbol 8
set_interface_property avs burstOnBurstBoundariesOnly false
set_interface_property avs burstcountUnits WORDS
set_interface_property avs explicitAddressSpan 0
set_interface_property avs holdTime 0
set_interface_property avs linewrapBursts false
set_interface_property avs maximumPendingReadTransactions 0
set_interface_property avs maximumPendingWriteTransactions 0
set_interface_property avs readLatency 0
set_interface_property avs readWaitTime 1
set_interface_property avs setupTime 0
set_interface_property avs timingUnits Cycles
set_interface_property avs writeWaitTime 0
set_interface_property avs ENABLED true

add_interface_port avs avs_address     address      Input  5
add_interface_port avs avs_read        read         Input  1
add_interface_port avs avs_readdata    readdata     Output 32
add_interface_port avs avs_write       write        Input  1
add_interface_port avs avs_writedata   writedata    Input  32
add_interface_port avs avs_waitrequest waitrequest  Output 1
