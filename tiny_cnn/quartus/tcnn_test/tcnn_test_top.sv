// tcnn_test_top.sv -- DE2-115 board-level top for the standalone tiny-cnn
// test system. Wraps the generated Platform Designer system (Nios V/m +
// on-chip RAM + JTAG UART + sysid + tcnn_avalon_slave) with board I/O:
// CLOCK_50, KEY[0] reset, and a heartbeat LED.
//
// Single clock domain, CLOCK_50 (50 MHz) -- see build_system.tcl's note:
// all 4 conv_layer stages measured comfortably inside the 1024-cycle/tile
// budget in Verilator (Gate C1/F1: 1037 cycles/tile), so no PLL / separate
// clock domain was built for this component. tcnn_avalon_slave does not
// (yet) export a busy/mismatch conduit, so LEDG[1]/LEDR[0] are left dark
// rather than wired to something meaningless -- a worthwhile follow-up, not
// required for this phase's fit/timing gate.
module tcnn_test_top (
    input  logic        CLOCK_50,
    input  logic [3:0]  KEY,       // KEY[0] = reset, active low
    output logic [8:0]  LEDG,
    output logic [17:0] LEDR
);

  wire rst_n = KEY[0];

  tcnn_test_sys u_sys (
    .clk_clk(CLOCK_50),
    .reset_reset_n(rst_n)
  );

  // heartbeat: system clock alive
  logic [24:0] heartbeat_ctr;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) heartbeat_ctr <= '0;
    else        heartbeat_ctr <= heartbeat_ctr + 1'b1;
  end
  assign LEDG[0]    = heartbeat_ctr[24];
  assign LEDG[8:1]  = 8'h00;
  assign LEDR       = 18'h00000;

endmodule
