`timescale 1ns/1ps
// Streams synthetic frames through window_buffer + template_match and checks
// temp_boundary_x/y (= top-left of the best window).
//   iverilog -g2012 -DNEW ...  -> new design (+ RADIUS/REJECT tests)
//   iverilog -g2012 ...        -> original design, for comparison
module tb;
    parameter int WIN = 16, W = 64, H = 48;
    parameter int GAP = 1;              // idle clocks between valid samples (0 = back-to-back)
    localparam XW = $clog2(W), YW = $clog2(H);

    logic clk = 0, rst_n = 0;
    always #18.5 clk = ~clk;            // 27 MHz-ish

    logic dval = 0, fdone = 0;
    logic [7:0] pix = 0;
    logic [7:0] win [WIN-1:0][WIN-1:0];
    logic wvalid;
    logic [XW-1:0] ax;
    logic [YW-1:0] ay;
    logic [9:0] bx, by;
    logic [31:0] dbg;
    logic tw = 0; logic [7:0] twi = 0, twd = 0;

    window_buffer #(.WIN(WIN), .IMG_W(W), .IMG_H(H)) wb (
        .clk(clk), .rst_n(rst_n), .clock_enable(dval), .frame_done(fdone),
        .data_in(pix), .window_out(win), .window_valid(wvalid),
        .anchor_x(ax), .anchor_y(ay));

`ifdef NEW
    template_match #(.WIN(WIN), .IMG_W(W), .IMG_H(H),
                     .RADIUS(`RADIUS), .REJECT_SAD(1500), .LOST_MAX(3)) tm (
`else
    template_match #(.WIN(WIN), .IMG_W(W), .IMG_H(H)) tm (
`endif
        .clk(clk), .rst_n(rst_n), .search_start(fdone), .window_valid(wvalid),
        .data_in(win), .current_x(ax), .current_y(ay),
        .temp_boundary_x(bx), .temp_boundary_y(by), .debug_data(dbg),
        .tmpl_wr_pulse(tw), .tmpl_wr_index(twi), .tmpl_wr_data(twd));

    // ---- image helpers -------------------------------------------------
    logic [7:0] img [0:H-1][0:W-1];
    logic [7:0] patch [0:WIN-1][0:WIN-1];
    int unsigned seed;
    function automatic int unsigned rnd();
        seed = seed * 1103515245 + 12345;
        return seed >> 16;
    endfunction

    task automatic make_bg(input int unsigned s, input int offset);
        seed = s;
        for (int y = 0; y < H; y++) for (int x = 0; x < W; x++)
            img[y][x] = 8'(100 + (rnd() % 41) + offset);
    endtask
    task automatic paste(input int px, input int py, input int offset);
        for (int r = 0; r < WIN; r++) for (int c = 0; c < WIN; c++)
            img[py+r][px+c] = 8'(int'(patch[r][c]) + offset);
    endtask

    task automatic stream_frame();
        for (int y = 0; y < H; y++) begin
            for (int x = 0; x < W; x++) begin
                @(negedge clk); dval = 1; pix = img[y][x];
                repeat (GAP) begin @(negedge clk); dval = 0; end
            end
            @(negedge clk); dval = 0;
            repeat (6) @(negedge clk);          // horizontal blanking
        end
        repeat (20) @(negedge clk);             // flush pipeline
    endtask

    task automatic end_frame(input string name, input int ex, input int ey);
        // outputs are valid right before frame_done; sample then pulse it
        automatic int gx = bx, gy = by;
        @(negedge clk); fdone = 1; @(negedge clk); fdone = 0;
        $display("%-34s got (%0d,%0d) expected (%0d,%0d)  %s", name, gx, gy, ex, ey,
                 (gx==ex && gy==ey) ? "PASS" : "FAIL");
    endtask

    task automatic load_template();
        for (int i = 0; i < WIN*WIN; i++) begin
            @(negedge clk); tw = 1; twi = i; `ifdef FLIP
            twd = patch[WIN-1-i/WIN][i%WIN];
`else
            twd = patch[i/WIN][i%WIN];
`endif
        end
        @(negedge clk); tw = 0;
        repeat (4) @(negedge clk);
    endtask

    initial begin
        // reference patch = a piece of noise
        seed = 32'hC0FFEE;
        for (int r = 0; r < WIN; r++) for (int c = 0; c < WIN; c++)
            patch[r][c] = 8'(100 + (rnd() % 41));

        repeat (5) @(negedge clk); rst_n = 1; repeat (3) @(negedge clk);
        load_template();
        @(negedge clk); fdone = 1; @(negedge clk); fdone = 0;

        make_bg(1, 0);  paste(33, 17, 0);
        stream_frame(); end_frame("A: patch at (33,17)", 33, 17);

        make_bg(2, 0);  paste(33, 17, 30);
        stream_frame(); end_frame("B: same, +30 brightness", 33, 17);

        make_bg(3, 0);  paste(40, 25, 0);
        stream_frame(); end_frame("C: moved to (40,25)", 40, 25);

`ifdef NEW
  `ifdef RADIUS_ON
        // target jumps far outside the search radius: result must HOLD, then
        // after LOST_MAX (=3) lost frames the full-frame search must re-acquire it
        for (int k = 0; k < 4; k++) begin
            make_bg(10+k, 0);  paste(0, 0, 0);
            stream_frame();
            end_frame($sformatf("D%0d: jump to (0,0), radius-limited", k), (k < 3) ? 40 : 0, (k < 3) ? 25 : 0);
        end
  `else
        make_bg(4, 0);  paste(0, 0, 0);
        stream_frame(); end_frame("D: patch in top-left corner (0,0)", 0, 0);
  `endif
`else
        make_bg(4, 0);  paste(0, 0, 0);
        stream_frame(); end_frame("D: patch in top-left corner (0,0)", 0, 0);
`endif

`ifdef RADIUS_ON
        // (0,0) -> (48,32) is outside RADIUS=8 as well: hold for 3 frames, then re-acquire
        for (int k = 0; k < 4; k++) begin
            make_bg(20+k, 0);  paste(48, 32, 0);
            stream_frame();
            end_frame($sformatf("E%0d: jump to (48,32), radius-limited", k), (k < 3) ? 0 : 48, (k < 3) ? 0 : 32);
        end
`else
        make_bg(5, 0);  paste(48, 32, 0);
        stream_frame(); end_frame("E: patch bottom-right (48,32)", 48, 32);
`endif
`ifdef NEW
        make_bg(6, 0);
        stream_frame(); end_frame("F: no target -> hold last (48,32)", 48, 32);
`endif
        $finish;
    end
endmodule
