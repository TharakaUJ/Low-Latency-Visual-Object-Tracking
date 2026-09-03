`timescale 1ns/1ps

module tb_process_top;

logic clk;
logic rst_n;
logic [7:0] Y;
logic v_sync;
logic h_sync;
logic [9:0] boundary_x;
logic [9:0] boundary_y; 


process_top dut (
    .clk(clk),
    .rst_n(rst_n),
    .Y(Y),
    .v_sync(v_sync),
    .h_sync(h_sync),
    .boundary_x(boundary_x),
    .boundary_y(boundary_y)
);


initial begin
    clk = 0;
    rst_n = 0;
    Y = 0;
    v_sync = 0;
    h_sync = 0;
    forever #5 clk = ~clk; // 100MHz clock
end





endmodule