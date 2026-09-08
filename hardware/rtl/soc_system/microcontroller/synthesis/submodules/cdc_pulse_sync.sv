// cdc_pulse_sync
//
// Safely moves a single-cycle pulse from src_clk domain into dst_clk domain.
// Uses a toggle flop in the source domain (so the CDC boundary only ever
// carries one bit that changes at most once per source pulse), then a
// standard 2-flop synchronizer in the destination domain, followed by edge
// detection to regenerate a single-cycle pulse there.
//
// Requirements / caveats:
//  - src_pulse must be at most 1 clk-cycle wide and must not re-assert
//    again until the previous one has had time to propagate (a handshake /
//    busy signal at the call site should guarantee this - see
//    avalon_slave_top's busy/waitrequest logic).
//  - Both resets are assumed asynchronous, active-low, and eventually
//    released synchronously to their own domain (typical FPGA reset tree).

module cdc_pulse_sync (
    input  wire src_clk,
    input  wire src_rst_n,
    input  wire src_pulse,

    input  wire dst_clk,
    input  wire dst_rst_n,
    output wire dst_pulse
);

    // ---- source domain: toggle on every pulse ----
    reg toggle_src;
    always_ff @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n)
            toggle_src <= 1'b0;
        else if (src_pulse)
            toggle_src <= ~toggle_src;
    end

    // ---- destination domain: 2-FF synchronizer + edge detect ----
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

    assign dst_pulse = sync_ff[1] ^ toggle_dst_d;

endmodule
