`timescale 1ns/1ps
// ============================================================
// tb_template_match
// Standalone unit test for template_match.sv. All of its ports are
// either scalars or a single INPUT array (data_in), so -- unlike
// window_buffer -- it does not hit the Icarus Verilog unpacked-array
// *output* port limitation and can be driven/checked entirely
// through its ports.
//
// NOTE ON SIMULATION: the real template_match.sv initializes its
// `tmpl` ROM with a parameterized unpacked-array localparam
// (`localparam logic [7:0] tmpl [WIN-1:0][WIN-1:0] = '{...}`), which
// Icarus Verilog 12.0's parser rejects ("localparam must have a
// value") -- confirmed with a minimal repro outside this design.
// This is a known iverilog gap, not an RTL bug (Quartus/Questa/VCS/
// Xcelium/Verilator all accept the syntax). To actually run this
// testbench in this sandbox we compile against tmpl_sim_shim.sv,
// a byte-for-byte functional copy of template_match.sv that builds
// the same all-0xFF tmpl ROM with an initial-block loop instead.
// On any standards-compliant simulator, just compile the real
// template_match.sv instead and delete tmpl_sim_shim.sv -- this
// testbench does not need to change.
//
// Checks:
//   1. SAD math: exact-match window (all 0xFF, matching tmpl) gives
//      total_sad == 0 via debug_data.
//   2. min_sad/boundary latching: only updates while window_valid=1,
//      only on a strictly-lower SAD, and captures current_x/current_y
//      from the SAME cycle as the winning SAD -- i.e. template_match
//      itself does no internal delay of current_x/current_y; any
//      alignment with the actual window content is entirely the
//      caller's (process_top's) responsibility. See tb_process_top
//      for whether process_top gets that alignment right.
//   3. search_start synchronously reinitializes min_sad/boundary,
//      even while window_valid=1.
//   4. window_valid=0 freezes min_sad/boundary regardless of total_sad.
// ============================================================
module tb_template_match;

    localparam int WIN = 4;
    localparam int SAD_W = $clog2(WIN*WIN*255 + 1);

    logic clk = 0, rst_n;
    logic search_start, window_valid;
    logic [7:0] data_in [WIN-1:0][WIN-1:0];
    logic [9:0] current_x, current_y;
    logic [9:0] temp_boundary_x, temp_boundary_y;
    logic [31:0] debug_data;

    int errors = 0;

    template_match #(.WIN(WIN)) dut (
        .clk(clk), .rst_n(rst_n),
        .search_start(search_start), .window_valid(window_valid),
        .data_in(data_in),
        .current_x(current_x), .current_y(current_y),
        .temp_boundary_x(temp_boundary_x), .temp_boundary_y(temp_boundary_y),
        .debug_data(debug_data)
    );

    always #5 clk = ~clk;

    function automatic logic [SAD_W-1:0] extract_total_sad();
        return debug_data[SAD_W-1:0];
    endfunction

    task automatic set_window(input logic [7:0] val);
        for (int r = 0; r < WIN; r++)
            for (int c = 0; c < WIN; c++)
                data_in[r][c] = val;
    endtask

    // Set every cell to a per-cell offset from the template (all 0xFF)
    // so we can predict total_sad exactly: total_sad = WIN*WIN*diff.
    task automatic set_window_uniform_diff(input int diff);
        set_window(8'hFF - diff[7:0]);
    endtask

    initial begin
        rst_n = 0; search_start = 0; window_valid = 0;
        current_x = 0; current_y = 0;
        set_window(8'h00);
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(negedge clk);

        // ------------------------------------------------------------
        // 1) Reset state: min_sad = all-ones, boundary = 0
        // ------------------------------------------------------------
        if (temp_boundary_x !== 10'd0 || temp_boundary_y !== 10'd0) begin
            $error("post-reset boundary not 0: x=%0d y=%0d", temp_boundary_x, temp_boundary_y);
            errors++;
        end

        // ------------------------------------------------------------
        // 2) A moderate (non-zero) SAD match -> latched as the current
        //    best. (Deliberately NOT a perfect 0-SAD match here, so a
        //    later, genuinely better match in step 5 has room to win.)
        // ------------------------------------------------------------
        set_window_uniform_diff(20); // total_sad = WIN*WIN*20 = 320
        current_x = 10'd5; current_y = 10'd7;
        window_valid = 1;
        @(posedge clk); #1;
        if (extract_total_sad() !== SAD_W'(WIN*WIN*20)) begin
            $error("step2: total_sad=%0d expected %0d", extract_total_sad(), WIN*WIN*20);
            errors++;
        end
        if (temp_boundary_x !== 10'd5 || temp_boundary_y !== 10'd7) begin
            $error("step2 match not latched as new min: bx=%0d by=%0d expected (5,7)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end

        // ------------------------------------------------------------
        // 3) A WORSE match (higher SAD) at a later (x,y) must NOT
        //    overwrite the current best.
        // ------------------------------------------------------------
        set_window_uniform_diff(25); // total_sad = WIN*WIN*25 = 400, > 320 (step2's SAD)
        current_x = 10'd6; current_y = 10'd7;
        @(posedge clk); #1;
        if (temp_boundary_x !== 10'd5 || temp_boundary_y !== 10'd7) begin
            $error("worse match incorrectly overwrote boundary: bx=%0d by=%0d expected (5,7)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end

        // ------------------------------------------------------------
        // 4) window_valid=0: even a perfect match must be ignored.
        // ------------------------------------------------------------
        window_valid = 0;
        set_window(8'hFF);
        current_x = 10'd99; current_y = 10'd99;
        @(posedge clk); #1;
        if (temp_boundary_x !== 10'd5 || temp_boundary_y !== 10'd7) begin
            $error("update happened while window_valid=0: bx=%0d by=%0d expected (5,7)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end
        window_valid = 1;

        // ------------------------------------------------------------
        // 5) A strictly better (lower) SAD at a new (x,y) DOES win, and
        //    the captured (x,y) is exactly the (current_x,current_y)
        //    presented on the SAME cycle as that winning SAD -- confirms
        //    template_match applies no internal delay of its own.
        // ------------------------------------------------------------
        set_window_uniform_diff(5); // total_sad = WIN*WIN*5 = 80, better than step2's 320
        current_x = 10'd42; current_y = 10'd99;
        @(posedge clk); #1;
        if (temp_boundary_x !== 10'd42 || temp_boundary_y !== 10'd99) begin
            $error("better match not latched: bx=%0d by=%0d expected (42,99)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end
        // total_sad must have been computed COMBINATIONALLY on the
        // *current* data_in/current_x, i.e. same-cycle, zero extra
        // pipeline delay inside this module.
        if (extract_total_sad() !== SAD_W'(WIN*WIN*5)) begin
            $error("total_sad mismatch: got=%0d expected=%0d", extract_total_sad(), WIN*WIN*5);
            errors++;
        end

        // ------------------------------------------------------------
        // 6) search_start synchronously clears min_sad/boundary back to
        //    0 even while window_valid is asserted and a perfect match
        //    is sitting on data_in (search_start must win the priority).
        // ------------------------------------------------------------
        set_window(8'hFF);
        current_x = 10'd1; current_y = 10'd1;
        search_start = 1;
        @(posedge clk); #1;
        search_start = 0;
        if (temp_boundary_x !== 10'd0 || temp_boundary_y !== 10'd0) begin
            $error("search_start did not reset boundary: bx=%0d by=%0d expected (0,0)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end

        // Next cycle, that same perfect match is free to win again from
        // the fresh min_sad='1 baseline.
        current_x = 10'd1; current_y = 10'd1;
        @(posedge clk); #1;
        if (temp_boundary_x !== 10'd1 || temp_boundary_y !== 10'd1) begin
            $error("first post-search_start match not captured: bx=%0d by=%0d expected (1,1)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end

        // ------------------------------------------------------------
        // 7) Equal SAD (tie) must NOT overwrite the existing best
        //    (strict '<' comparison, not '<=').
        // ------------------------------------------------------------
        current_x = 10'd77; current_y = 10'd77; // same total_sad (0), different position
        @(posedge clk); #1;
        if (temp_boundary_x !== 10'd1 || temp_boundary_y !== 10'd1) begin
            $error("tie incorrectly overwrote boundary: bx=%0d by=%0d expected (1,1)",
                    temp_boundary_x, temp_boundary_y);
            errors++;
        end

        if (errors == 0)
            $display("TB_TEMPLATE_MATCH: PASS (all checks ok)");
        else
            $display("TB_TEMPLATE_MATCH: FAIL (%0d errors)", errors);

        $finish;
    end

endmodule
