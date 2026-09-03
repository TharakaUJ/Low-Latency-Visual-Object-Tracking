// Single BRAM-based line delay.
// Read-before-write on the same address: dout returns whatever pixel was
// stored in this column BEFORE this cycle's write, i.e. the pixel that was
// at this column exactly one line (IMG_W cycles) ago. That is exactly the
// "row above" delay a video window buffer needs, and Quartus will infer
// this directly as a single M9K/M4K block (no LEs used for storage).
module line_buffer #(
    parameter int WIDTH = 8,
    parameter int IMG_W = 640
)(
    input  logic clk,
    input  logic wr_en,
    input  logic [$clog2(IMG_W)-1:0] addr,
    input  logic [WIDTH-1:0] din,
    output logic [WIDTH-1:0] dout
);

    (* ramstyle = "M9K" *) logic [WIDTH-1:0] mem [0:IMG_W-1];

    always_ff @(posedge clk) begin
        dout <= mem[addr];   // read old value
        if (wr_en)
            mem[addr] <= din; // then write new value
    end

endmodule
