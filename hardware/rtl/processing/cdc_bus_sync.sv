// cdc_bus_sync
//
// Crosses a multi-bit "quasi-static" bus (one that only changes occasionally
// and is held stable for many destination-clock cycles between updates,
// e.g. boundary_x/boundary_y updated once per video frame) from src_clk to
// dst_clk domain.
//
// Why not just double-flop each bit of the bus directly? Because different
// bits can resolve metastability on different cycles, so a plain 2-FF-per-bit
// synchronizer on a bus can hand the destination domain a torn/incoherent
// value for one cycle. Here we only synchronize a single-bit "update"
// strobe across the boundary (safe, standard 2FF), and only latch the whole
// bus into the destination domain once that strobe has fully resolved -
// by which point src_data has long since settled (it changed at most once,
// far in the past relative to the sync latency), so the capture is coherent.
//
// This module is intended for buses that update at most every few dozen
// destination-clock cycles (frame-rate, config-rate signals). It is NOT
// suitable for a bus that toggles every cycle.

module cdc_bus_sync #(
    parameter int WIDTH = 20
)(
    input  wire               src_clk,
    input  wire               src_rst_n,
    input  wire [WIDTH-1:0]   src_data,
    input  wire               src_valid,   // 1-cycle pulse in src_clk domain when src_data is updated

    input  wire               dst_clk,
    input  wire               dst_rst_n,
    output reg  [WIDTH-1:0]   dst_data
);

    // ---- source domain: toggle marks each update ----
    reg toggle_src;
    always_ff @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n)
            toggle_src <= 1'b0;
        else if (src_valid)
            toggle_src <= ~toggle_src;
    end

    // ---- destination domain: 2-FF sync + edge detect ----
    (* ASYNC_REG = "TRUE" *) reg [1:0] sync_ff;
    reg toggle_dst_d;

    always_ff @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            sync_ff      <= 2'b00;
            toggle_dst_d <= 1'b0;
        end else begin
            sync_ff      <= {sync_ff[0], toggle_src};
            toggle_dst_d <= sync_ff[1];
        end
    end

    wire capture_pulse = sync_ff[1] ^ toggle_dst_d;

    always_ff @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n)
            dst_data <= {WIDTH{1'b0}};
        else if (capture_pulse)
            dst_data <= src_data;
    end

endmodule
