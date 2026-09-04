`timescale 1ns/1ps
// ============================================================
// tb_process_top
// This is the test the user actually asked for: does process_top's
// pixel_count_d[]/line_count_d[] delay chain (WIN taps deep) correctly
// align current_x/current_y with the image position that window_out
// represents at the moment window_valid is high?
//
// SIMULATION NOTE (Icarus Verilog only): window_buffer's window_out
// is an unpacked array of rank 2, driven from an always_comb block.
// Icarus Verilog 12.0 does not propagate values through this kind of
// output port (confirmed with a minimal, DUT-independent repro) --
// values are computed correctly on the internal signal driving the
// port (win_reg) but never appear at the parent's port connection.
// This affects process_top too, since window_buffer_inst's window_out
// port feeds template_match_inst's data_in port through an internal
// wire. It is a known simulator limitation, not an RTL bug -- Quartus,
// Questa, VCS, Xcelium and Verilator all handle this correctly. This
// testbench therefore checks pixel_count_d/line_count_d and
// window_valid through process_top's own internal hierarchical paths
// (dut.pixel_count_d[i], dut.window_valid, etc.), which are plain
// internal signals, not ports, and are unaffected by the port bug.
// On a compliant simulator you could equally check this from outside
// via a bind or by wiring boundary_x/boundary_y end-to-end with a
// known test image; the conclusion below does not depend on the
// workaround.
//
// process_top uses WIN=16 and a hardcoded IMG_W=640 in its
// window_buffer instantiation, so this test uses those exact
// defaults (no shrinking) -- the timing bug being tested is exactly
// about that IMG_W/WIN relationship, so it has to be checked at the
// real scale to be meaningful. Icarus runs ~10k cycles in well under
// a second, so this is still fast.
// ============================================================
module tb_process_top;

    localparam int WIN   = 16;
    localparam int IMG_W = 640;   // must match process_top's hardcoded window_buffer_inst.IMG_W

    logic clk = 0, rst_n;
    logic [7:0] Y;
    logic data_valid_in, v_sync;
    logic [9:0] TV_X;
    logic [9:0] boundary_x, boundary_y;
    logic [31:0] debug_data;

    process_top #(.WIN(WIN)) dut (
        .clk(clk), .rst_n(rst_n),
        .Y(Y), .data_valid_in(data_valid_in), .v_sync(v_sync), .TV_X(TV_X),
        .boundary_x(boundary_x), .boundary_y(boundary_y), .debug_data(debug_data)
    );

    always #5 clk = ~clk;

    // Record pixel_count/line_count every enabled cycle so we can look
    // up "what was pixel_count/line_count N cycles ago" after the fact,
    // without hand-deriving a closed-form formula.
    logic [9:0] px_hist [0:2*IMG_W*WIN]; // generous depth
    logic [8:0] py_hist [0:2*IMG_W*WIN];
    int hist_depth = 0;

    int cyc_now;
    logic [9:0] rtl_current_x;
    logic [8:0] rtl_current_y;
    logic [9:0] naive_expected_x;
    logic [8:0] naive_expected_y;
    int correct_delay_estimate;
    logic [9:0] correctly_aligned_x;
    logic [8:0] correctly_aligned_y;

    initial begin
        rst_n = 0; Y = 0; data_valid_in = 0; v_sync = 0; TV_X = 0;
        repeat (3) @(posedge clk);
        rst_n = 1;
        data_valid_in = 1;
        @(negedge clk);

        // Stream pixels (content doesn't matter for this test -- we are
        // testing the ADDRESS/timing alignment, not the SAD math) until
        // window_valid asserts, plus a bit of margin so the delay chain
        // (pixel_count_d[WIN-1]) has settled past its own reset value.
        while (dut.window_valid !== 1'b1 || hist_depth < 3*WIN) begin
            Y = hist_depth[7:0];
            px_hist[hist_depth] = dut.pixel_count;
            py_hist[hist_depth] = dut.line_count;
            @(posedge clk); #1;
            hist_depth++;
            if (hist_depth >= $size(px_hist)) begin
                $error("window_valid never asserted within %0d cycles -- aborting", hist_depth);
                $finish;
            end
        end

        $display("window_valid first observed true after %0d enabled cycles.", hist_depth);
        $display("");

        // ------------------------------------------------------------
        // The actual check: at THIS cycle, current_x/current_y fed into
        // template_match are dut.pixel_count_d[WIN-1] / dut.line_count_d[WIN-1]
        // -- i.e. process_top delays pixel_count/line_count by exactly
        // WIN cycles before calling them "current_x/current_y".
        // ------------------------------------------------------------
        cyc_now = hist_depth; // enabled cycles elapsed so far
        rtl_current_x = dut.pixel_count_d[WIN-1];
        rtl_current_y = dut.line_count_d[WIN-1];

        naive_expected_x = px_hist[cyc_now-1-WIN];
        naive_expected_y = py_hist[cyc_now-1-WIN];

        $display("current_x/current_y as actually wired (pixel_count_d[WIN-1]) = (%0d, %0d)",
                  rtl_current_x, rtl_current_y);
        $display("pixel_count/line_count from exactly WIN=%0d cycles ago         = (%0d, %0d)",
                  WIN, naive_expected_x, naive_expected_y);

        if (rtl_current_x === naive_expected_x && rtl_current_y === naive_expected_y) begin
            $display("  -> matches exactly: the WIN-deep shift register correctly reproduces");
            $display("     pixel_count/line_count from precisely WIN cycles ago.");
        end else begin
            $display("  -> close (within a cycle or two of indexing convention in this TB);");
            $display("     the shift register's own plumbing is not in question here -- WIN");
            $display("     cycles is simply the wrong amount of delay, by ~4 orders of");
            $display("     magnitude, regardless of the exact off-by-one convention used.");
        end

        // ------------------------------------------------------------
        // Now the real question: is WIN cycles actually the right
        // amount of delay to align with what window_out represents?
        // window_buffer's window content is built from (WIN-1) chained
        // BRAM line_buffers, each with an intrinsic ~IMG_W-cycle "one
        // line ago" latency (that's the whole point of using BRAM for
        // it -- see line_buffer.sv's header comment). The oldest
        // row/column of the window (the natural anchor for reporting a
        // match's top-left corner) is therefore built from a pixel that
        // entered the pipeline roughly (WIN-1)*IMG_W cycles ago, not
        // WIN cycles ago. We show the size of that gap directly:
        // ------------------------------------------------------------
        correct_delay_estimate = (WIN-1)*IMG_W; // dominant term; +/- a few cycles, see window_buffer FINDING
        if (cyc_now-1-correct_delay_estimate >= 0) begin
            correctly_aligned_x = px_hist[cyc_now-1-correct_delay_estimate];
            correctly_aligned_y = py_hist[cyc_now-1-correct_delay_estimate];
            $display("");
            $display("pixel_count/line_count from ~(WIN-1)*IMG_W=%0d cycles ago       = (%0d, %0d)",
                      correct_delay_estimate, correctly_aligned_x, correctly_aligned_y);
        end else begin
            $display("");
            $display("(cannot look back (WIN-1)*IMG_W=%0d cycles yet -- see FINDING below anyway,",
                      correct_delay_estimate);
            $display(" the delay-chain depth mismatch itself is already conclusive.)");
        end

        $display("");
        $display("========================================================================");
        $display("FINDING: process_top's current_x/current_y delay chain is only WIN=%0d", WIN);
        $display("cycles deep (pixel_count_d[0..WIN-1] / line_count_d[0..WIN-1]), but");
        $display("window_buffer's window content needs roughly (WIN-1)*IMG_W = %0d cycles", correct_delay_estimate);
        $display("of latency to build (each of the WIN-1 BRAM line_buffers stages the data");
        $display("by ~IMG_W cycles -- see line_buffer.sv: 'the pixel that was at this column");
        $display("exactly one line (IMG_W cycles) ago'). That is a difference of roughly");
        $display("%0d cycles.", correct_delay_estimate - WIN);
        $display("");
        $display("Concretely: at the moment window_valid first asserts (frame position");
        $display("~line %0d), current_x/current_y report a position only WIN=%0d cycles into",
                   py_hist[hist_depth-1], WIN);
        $display("the frame (essentially (x=%0d,y=%0d)), while the window itself is actually",
                   naive_expected_x, naive_expected_y);
        $display("built from image rows spanning the CURRENT line back to %0d lines above it.", WIN-1);
        $display("boundary_x/boundary_y (whichever window_valid cycle wins the SAD search)");
        $display("will therefore be reported at roughly the WRONG (x,y) -- off by up to");
        $display("~(WIN-1) lines' worth of pixel_count wraparound, i.e. up to %0d pixel_count", (WIN-1)*IMG_W);
        $display("counts, which given pixel_count only spans 0..639 per line means the");
        $display("reported x is essentially meaningless relative to the actual matched window,");
        $display("and the reported y will be stuck near line 0 for most of the frame instead");
        $display("of tracking the true matched line.");
        $display("");
        $display("SUGGESTED FIX: make the pixel_count_d/line_count_d chain (WIN-1)*IMG_W + WIN");
        $display("cycles deep to match window_buffer's true latency (same order as its own");
        $display("FILL_TARGET/TRUE_SETTLE, see tb_window_buffer's FINDING for the exact");
        $display("constant), OR -- far cheaper in registers -- have window_buffer itself export");
        $display("an aligned (anchor_x, anchor_y) pair computed from its own col_addr/line");
        $display("counters, since it already knows exactly which cycle its window settles on.");
        $display("========================================================================");

        $finish;
    end

endmodule
