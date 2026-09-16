// dp_ram.sv
// Small synchronous-read dual-port byte RAM used to hold activations
// between pipeline stages (one producer writes, one consumer reads;
// the two never run concurrently in this sequential design).
module dp_ram #(
    parameter int DEPTH = 1024,
    parameter int AW    = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
) (
    input  logic clk,
    // write port
    input  logic             we,
    input  logic [AW-1:0]    waddr,
    input  logic [7:0]       wdata,
    // read port (synchronous, 1-cycle latency)
    input  logic [AW-1:0]    raddr,
    output logic [7:0]       rdata
);
    (* ram_style = "block" *) logic [7:0] mem [0:DEPTH-1];

    always_ff @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        rdata <= mem[raddr];
    end
endmodule
