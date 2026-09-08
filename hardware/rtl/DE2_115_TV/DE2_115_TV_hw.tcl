# TCL File for Platform Designer / Qsys component wrapper
# Regenerated to match the trimmed-down DE2_115_TV.v top level
#
# module DE2_115_TV
#
package require -exact qsys 16.1

set_module_property DESCRIPTION "DE2-115 TV Box top level (custom video capture + process_top) wrapped for Platform Designer"
set_module_property NAME DE2_115_TV
set_module_property VERSION 1.0
set_module_property INTERNAL false
set_module_property OPAQUE_ADDRESS_MAP true
set_module_property GROUP "DE2-115 Board"
set_module_property AUTHOR "User"
set_module_property DISPLAY_NAME "DE2-115 TV Box"
set_module_property INSTANTIATE_IN_SYSTEM_MODULE true
set_module_property EDITABLE true
set_module_property REPORT_TO_TALKBACK false
set_module_property ALLOW_GREYBOX_GENERATION false
set_module_property REPORT_HIERARCHY false

#
# file sets
#
add_fileset QUARTUS_SYNTH QUARTUS_SYNTH "" ""
set_fileset_property QUARTUS_SYNTH TOP_LEVEL DE2_115_TV
set_fileset_property QUARTUS_SYNTH ENABLE_RELATIVE_INCLUDE_PATHS false
set_fileset_property QUARTUS_SYNTH ENABLE_FILE_OVERWRITE_MODE true

add_fileset_file DE2_115_TV.v          VERILOG PATH DE2_115_TV.v TOP_LEVEL_FILE

# ---- DE2_115_TV children actually instantiated today ----
add_fileset_file TD_Detect.v           VERILOG PATH TD_Detect.v
add_fileset_file Reset_Delay.v         VERILOG PATH Reset_Delay.v
add_fileset_file ITU_656_Decoder.v     VERILOG PATH ITU_656_Decoder.v
add_fileset_file DIV.v                 VERILOG PATH DIV.v
add_fileset_file DIV.qip               OTHER   PATH DIV.qip
add_fileset_file YUV422_to_444.v       VERILOG PATH YUV422_to_444.v
add_fileset_file YCbCr2RGB.v           VERILOG PATH YCbCr2RGB.v
add_fileset_file VGA_Ctrl.v            VERILOG PATH VGA_Ctrl.v
add_fileset_file Line_Buffer.v         VERILOG PATH Line_Buffer.v
add_fileset_file Line_Buffer.qip       OTHER   PATH Line_Buffer.qip
add_fileset_file I2C_AV_Config.v       VERILOG PATH I2C_AV_Config.v
add_fileset_file I2C_Controller.v      VERILOG PATH I2C_Controller.v

# ---- SDRAM frame buffer ----
add_fileset_file Sdram_Control_4Port.v VERILOG PATH Sdram_Control_4Port/Sdram_Control_4Port.v
add_fileset_file Sdram_PLL.v           VERILOG PATH Sdram_Control_4Port/Sdram_PLL.v
add_fileset_file Sdram_PLL.qip         OTHER   PATH Sdram_Control_4Port/Sdram_PLL.qip
add_fileset_file Sdram_Params.h        OTHER   PATH Sdram_Control_4Port/Sdram_Params.h
add_fileset_file Sdram_RD_FIFO.v       VERILOG PATH Sdram_Control_4Port/Sdram_RD_FIFO.v
add_fileset_file Sdram_RD_FIFO.qip     OTHER   PATH Sdram_Control_4Port/Sdram_RD_FIFO.qip
add_fileset_file Sdram_WR_FIFO.v       VERILOG PATH Sdram_Control_4Port/Sdram_WR_FIFO.v
add_fileset_file Sdram_WR_FIFO.qip     OTHER   PATH Sdram_Control_4Port/Sdram_WR_FIFO.qip
add_fileset_file command.v             VERILOG PATH Sdram_Control_4Port/command.v
add_fileset_file control_interface.v   VERILOG PATH Sdram_Control_4Port/control_interface.v
add_fileset_file sdr_data_path.v       VERILOG PATH Sdram_Control_4Port/sdr_data_path.v

# ---- processing/ (process_top and children) ----
# NOTE: verify this file actually contains module `avalon_slave_top`,
# since that's what process_top.sv instantiates - rename here if needed.
add_fileset_file avalon_interface.sv   SYSTEM_VERILOG PATH ../processing/avalon_interface.sv
add_fileset_file cdc_bus_sync.sv       SYSTEM_VERILOG PATH ../processing/cdc_bus_sync.sv
add_fileset_file cdc_pulse_sync.sv     SYSTEM_VERILOG PATH ../processing/cdc_pulse_sync.sv
add_fileset_file window_buffer.sv      SYSTEM_VERILOG PATH ../processing/window_buffer.sv
add_fileset_file template_match.sv     SYSTEM_VERILOG PATH ../processing/template_match.sv
add_fileset_file process_top.sv        SYSTEM_VERILOG PATH ../processing/process_top.sv

add_fileset SIM_VERILOG SIM_VERILOG "" ""
set_fileset_property SIM_VERILOG TOP_LEVEL DE2_115_TV
set_fileset_property SIM_VERILOG ENABLE_RELATIVE_INCLUDE_PATHS false
set_fileset_property SIM_VERILOG ENABLE_FILE_OVERWRITE_MODE true

#
# parameters (forwarded to process_top's WIN / IMG_W / IMG_H if you want
# them tunable from Platform Designer - optional, delete if not needed)
#
add_parameter WIN INTEGER 16
set_parameter_property WIN DEFAULT_VALUE 16
set_parameter_property WIN DISPLAY_NAME "Template match window size"
set_parameter_property WIN TYPE INTEGER
set_parameter_property WIN UNITS None
set_parameter_property WIN HDL_PARAMETER true

#
# connection point clk (CLOCK_50 - Avalon / processing 50MHz domain)
#
add_interface clk clock end
set_interface_property clk clockRate 50000000
set_interface_property clk ENABLED true
add_interface_port clk CLOCK_50 clk Input 1

#
# connection point reset (active-low, synchronous to clk)
#
add_interface reset reset end
set_interface_property reset associatedClock clk
set_interface_property reset synchronousEdges DEASSERT
set_interface_property reset ENABLED true
add_interface_port reset reset_n reset_n Input 1

#
# connection point avs - Avalon-MM slave (process_top register file)
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

add_interface_port avs avs_address    address       Input  9
add_interface_port avs avs_read       read          Input  1
add_interface_port avs avs_readdata   readdata      Output 32
add_interface_port avs avs_write      write         Input  1
add_interface_port avs avs_writedata  writedata     Input  32
add_interface_port avs avs_waitrequest waitrequest  Output 1

#
# connection point conduit_leds
#
add_interface conduit_leds conduit end
set_interface_property conduit_leds associatedClock clk
set_interface_property conduit_leds associatedReset reset
set_interface_property conduit_leds ENABLED true
add_interface_port conduit_leds LEDG ledg Output 9
add_interface_port conduit_leds LEDR ledr Output 18

#
# connection point conduit_vga
#
add_interface conduit_vga conduit end
set_interface_property conduit_vga associatedClock clk
set_interface_property conduit_vga associatedReset reset
set_interface_property conduit_vga ENABLED true
add_interface_port conduit_vga VGA_B       vga_b       Output 8
add_interface_port conduit_vga VGA_BLANK_N vga_blank_n Output 1
add_interface_port conduit_vga VGA_CLK     vga_clk     Output 1
add_interface_port conduit_vga VGA_G       vga_g       Output 8
add_interface_port conduit_vga VGA_HS      vga_hs      Output 1
add_interface_port conduit_vga VGA_R       vga_r       Output 8
add_interface_port conduit_vga VGA_SYNC_N  vga_sync_n  Output 1
add_interface_port conduit_vga VGA_VS      vga_vs      Output 1

#
# connection point conduit_i2c
#
add_interface conduit_i2c conduit end
set_interface_property conduit_i2c associatedClock clk
set_interface_property conduit_i2c associatedReset reset
set_interface_property conduit_i2c ENABLED true
add_interface_port conduit_i2c I2C_SCLK i2c_sclk Output 1
add_interface_port conduit_i2c I2C_SDAT i2c_sdat Bidir  1

#
# connection point conduit_tvdecoder
#
add_interface conduit_tvdecoder conduit end
set_interface_property conduit_tvdecoder associatedClock clk
set_interface_property conduit_tvdecoder associatedReset reset
set_interface_property conduit_tvdecoder ENABLED true
add_interface_port conduit_tvdecoder TD_CLK27   td_clk27   Input  1
add_interface_port conduit_tvdecoder TD_DATA    td_data    Input  8
add_interface_port conduit_tvdecoder TD_HS      td_hs      Input  1
add_interface_port conduit_tvdecoder TD_RESET_N td_reset_n Output 1
add_interface_port conduit_tvdecoder TD_VS      td_vs      Input  1

#
# connection point conduit_sdram
#
add_interface conduit_sdram conduit end
set_interface_property conduit_sdram associatedClock clk
set_interface_property conduit_sdram associatedReset reset
set_interface_property conduit_sdram ENABLED true
add_interface_port conduit_sdram DRAM_ADDR  dram_addr  Output 13
add_interface_port conduit_sdram DRAM_BA    dram_ba    Output 2
add_interface_port conduit_sdram DRAM_CAS_N dram_cas_n Output 1
add_interface_port conduit_sdram DRAM_CKE   dram_cke   Output 1
add_interface_port conduit_sdram DRAM_CLK   dram_clk   Output 1
add_interface_port conduit_sdram DRAM_CS_N  dram_cs_n  Output 1
add_interface_port conduit_sdram DRAM_DQ    dram_dq    Bidir  32
add_interface_port conduit_sdram DRAM_DQM   dram_dqm   Output 4
add_interface_port conduit_sdram DRAM_RAS_N dram_ras_n Output 1
add_interface_port conduit_sdram DRAM_WE_N  dram_we_n  Output 1
