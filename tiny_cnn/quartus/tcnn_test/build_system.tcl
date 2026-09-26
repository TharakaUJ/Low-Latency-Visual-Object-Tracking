package require -exact qsys 16.1

create_system {tcnn_test_sys}
set_project_property DEVICE {EP4CE115F29C7}
set_project_property DEVICE_FAMILY {Cyclone IV E}

# ---- clock ----
add_instance clk_0 clock_source
set_instance_parameter_value clk_0 {clockFrequency} {50000000}

# ---- Nios V/m ----
add_instance intel_niosv_m_0 intel_niosv_m
set_instance_parameter_value intel_niosv_m_0 {AUTO_DEVICE} {EP4CE115F29C7}
set_instance_parameter_value intel_niosv_m_0 {AUTO_DEVICE_SPEEDGRADE} {7}
set_instance_parameter_value intel_niosv_m_0 {deviceFamily} {Cyclone IV E}
set_instance_parameter_value intel_niosv_m_0 {clockFrequency} {50000000}
set_instance_parameter_value intel_niosv_m_0 {enableAvalonInterface} {true}
set_instance_parameter_value intel_niosv_m_0 {enableDebug} {true}
set_instance_parameter_value intel_niosv_m_0 {resetOffset} {0}
set_instance_parameter_value intel_niosv_m_0 {resetSlave} {onchip_memory2_0.s1}

# ---- on-chip RAM, 64KB (same size as fpga_cnn_pipeline's, see its
# build_system.tcl note on why 32KB was not enough for the HAL/libc-linked
# firmware app) ----
add_instance onchip_memory2_0 altera_avalon_onchip_memory2
set_instance_parameter_value onchip_memory2_0 {deviceFamily} {Cyclone IV E}
set_instance_parameter_value onchip_memory2_0 {memorySize} {65536}
set_instance_parameter_value onchip_memory2_0 {dataWidth} {32}
set_instance_parameter_value onchip_memory2_0 {dualPort} {false}
set_instance_parameter_value onchip_memory2_0 {writable} {true}
set_instance_parameter_value onchip_memory2_0 {initMemContent} {true}
set_instance_parameter_value onchip_memory2_0 {blockType} {AUTO}

# ---- JTAG UART ----
add_instance jtag_uart_0 altera_avalon_jtag_uart
set_instance_parameter_value jtag_uart_0 {readBufferDepth} {512}
set_instance_parameter_value jtag_uart_0 {writeBufferDepth} {512}
set_instance_parameter_value jtag_uart_0 {readIRQThreshold} {8}
set_instance_parameter_value jtag_uart_0 {writeIRQThreshold} {8}

# ---- System ID ----
add_instance sysid_0 altera_avalon_sysid_qsys
set_instance_parameter_value sysid_0 {id} {3221225474}

# ---- Tiny-CNN Avalon slave (custom, tcnn_avalon_slave_hw.tcl in this directory) ----
add_instance tcnn_avalon_slave_0 tcnn_avalon_slave
set_instance_parameter_value tcnn_avalon_slave_0 {GEN_DIR} \
    {/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn/gen/}

# ---- clock/reset fanout ----
foreach inst {intel_niosv_m_0 jtag_uart_0 sysid_0} {
    add_connection clk_0.clk $inst.clk
    add_connection clk_0.clk_reset $inst.reset
}
add_connection clk_0.clk onchip_memory2_0.clk1
add_connection clk_0.clk_reset onchip_memory2_0.reset1

# tcnn_avalon_slave_0 runs on the same 50 MHz clk_0 domain as everything
# else (all 4 conv_layer stages were proven in Verilator to sit comfortably
# inside a 1024-cycle/tile budget with room to spare -- Gate C1/F1 measured
# 1037 cycles/tile, see progress_log.md -- so no separate slower clock
# domain is expected to be needed here; confirmed or refuted by this
# phase's quartus_sta run).
add_connection clk_0.clk tcnn_avalon_slave_0.clk
add_connection clk_0.clk_reset tcnn_avalon_slave_0.reset

# ---- CPU data/instruction masters -> slaves ----
add_connection intel_niosv_m_0.data_manager onchip_memory2_0.s1
add_connection intel_niosv_m_0.data_manager jtag_uart_0.avalon_jtag_slave
add_connection intel_niosv_m_0.data_manager sysid_0.control_slave
add_connection intel_niosv_m_0.data_manager tcnn_avalon_slave_0.avs
add_connection intel_niosv_m_0.instruction_manager onchip_memory2_0.s1
add_connection intel_niosv_m_0.data_manager intel_niosv_m_0.dm_agent
add_connection intel_niosv_m_0.data_manager intel_niosv_m_0.timer_sw_agent
add_connection intel_niosv_m_0.instruction_manager intel_niosv_m_0.dm_agent

# ---- JTAG UART IRQ ----
add_connection intel_niosv_m_0.platform_irq_rx jtag_uart_0.irq

# ---- base addresses (auto_assign_base_addresses does not distribute
# addresses in this Quartus/qsys-script install -- see
# fpga_cnn_pipeline/quartus/cnn_test/build_system.tcl's own note; set
# explicitly, same pattern) ----
set_connection_parameter_value intel_niosv_m_0.data_manager/onchip_memory2_0.s1 baseAddress 0x00000000
set_connection_parameter_value intel_niosv_m_0.instruction_manager/onchip_memory2_0.s1 baseAddress 0x00000000
set_connection_parameter_value intel_niosv_m_0.data_manager/intel_niosv_m_0.dm_agent baseAddress 0x00010000
set_connection_parameter_value intel_niosv_m_0.instruction_manager/intel_niosv_m_0.dm_agent baseAddress 0x00010000
set_connection_parameter_value intel_niosv_m_0.data_manager/intel_niosv_m_0.timer_sw_agent baseAddress 0x00020000
set_connection_parameter_value intel_niosv_m_0.data_manager/sysid_0.control_slave baseAddress 0x00030000
set_connection_parameter_value intel_niosv_m_0.data_manager/jtag_uart_0.avalon_jtag_slave baseAddress 0x00031000
set_connection_parameter_value intel_niosv_m_0.data_manager/tcnn_avalon_slave_0.avs baseAddress 0x00032000

# ---- IRQ ----
set_connection_parameter_value intel_niosv_m_0.platform_irq_rx/jtag_uart_0.irq irqNumber 0

validate_system

save_system {tcnn_test_sys.qsys}
puts "SYSTEM SAVED OK"
