// Single BRAM line delay with SEPARATE read and write addresses (simple
// dual-port). The read address is driven one sample ahead of the write
// address by window_buffer, so the pixel "one line ago" is already sitting on
// dout when the current sample arrives - even if valid samples arrive on
// back-to-back clocks. (The old single-address version only lined up because
// TV_DVAL happens to have an idle clock between samples.)
module line_buffer #(
    parameter int WIDTH = 8,
    parameter int IMG_W = 640
)(
    input  logic clk,
    input  logic wr_en,
    input  logic [$clog2(IMG_W)-1:0] wr_addr,
    input  logic [$clog2(IMG_W)-1:0] rd_addr,
    input  logic [WIDTH-1:0] din,
    output logic [WIDTH-1:0] dout
);
    (* ramstyle = "M9K" *) logic [WIDTH-1:0] mem [0:IMG_W-1];

    always_ff @(posedge clk) begin
        dout <= mem[rd_addr];
        if (wr_en)
            mem[wr_addr] <= din;
    end
endmodule
