`timescale 1ns/1ps
// Interlace test: field A holds the target at (33,4), field B (1/50 s later) at (33,11).
//   -DPER_FIELD : TD_VS once per field  (A, VS, B, VS, A, ...)
//   (default)   : TD_VS once per frame  (A lines then B lines, VS)
//   -DGATE=0/1  : field_gate ENABLE
module tb;
    parameter int WIN = 16, W = 64, FL = 32, H = 2*FL;
    localparam XW = $clog2(W), YW = $clog2(H);
`ifdef PER_FIELD
    localparam bit PF = 1;
`else
    localparam bit PF = 0;
`endif
    logic clk = 0, rst_n = 0;
    always #18.5 clk = ~clk;
    logic dval = 0, fdone = 0; logic [7:0] pix = 0;
    logic [7:0] win [WIN-1:0][WIN-1:0];
    logic wvalid, dv_g, ss; logic [XW-1:0] ax; logic [YW-1:0] ay;
    logic [9:0] bx, by; logic [31:0] dbg;
    logic tw = 0; logic [7:0] twi = 0, twd = 0;

    field_gate #(.ENABLE(`GATE), .VS_PER_FIELD(PF), .FIELD_LINES(FL), .IMG_W(W)) fg (
        .clk(clk), .rst_n(rst_n), .dv_in(dval), .frame_done(fdone), .dv_out(dv_g), .search_start(ss));
    window_buffer #(.WIN(WIN), .IMG_W(W), .IMG_H(H)) wb (
        .clk(clk), .rst_n(rst_n), .clock_enable(dv_g), .frame_done(fdone),
        .data_in(pix), .window_out(win), .window_valid(wvalid), .anchor_x(ax), .anchor_y(ay));
    template_match #(.WIN(WIN), .IMG_W(W), .IMG_H(H), .RADIUS(0)) tm (
        .clk(clk), .rst_n(rst_n), .search_start(ss), .window_valid(wvalid),
        .data_in(win), .current_x(ax), .current_y(ay),
        .temp_boundary_x(bx), .temp_boundary_y(by), .debug_data(dbg),
        .tmpl_wr_pulse(tw), .tmpl_wr_index(twi), .tmpl_wr_data(twd));

    logic [7:0] img [0:H-1][0:W-1];
    logic [7:0] patch [0:WIN-1][0:WIN-1];
    int unsigned seed;
    function automatic int unsigned rnd(); seed = seed*1103515245 + 12345; return seed >> 16; endfunction

    task automatic make_field(input int base, input int s, input int px, input int py);
        seed = s;
        for (int y = 0; y < FL; y++) for (int x = 0; x < W; x++) img[base+y][x] = 8'(100 + rnd()%41);
        for (int r = 0; r < WIN; r++) for (int c = 0; c < WIN; c++)
`ifndef PER_FIELD
            // frame mode: make field A's copy slightly imperfect so an UNGATED matcher would
            // prefer the exact copy in field B -> test discriminates
            img[base+py+r][px+c] = (base == 0) ? 8'(int'(patch[r][c]) + ((r*7+c*3)%5) - 2) : patch[r][c];
`else
            img[base+py+r][px+c] = patch[r][c];
`endif
    endtask
    task automatic stream(input int base);   // FL lines starting at img row `base`
        for (int y = 0; y < FL; y++) begin
            for (int x = 0; x < W; x++) begin
                @(negedge clk); dval = 1; pix = img[base+y][x];
                @(negedge clk); dval = 0;
            end
            repeat (6) @(negedge clk);
        end
    endtask
    task automatic vs(input string tag, input int ex, input int ey);
        automatic int gx, gy;
        repeat (20) @(negedge clk);
        gx = bx; gy = by;
        @(negedge clk); fdone = 1; @(negedge clk); fdone = 0;
        $display("%-36s got (%0d,%0d)  expected (%0d,%0d)  %s", tag, gx, gy, ex, ey,
                 (gx==ex && gy==ey) ? "PASS" : "  <-- differs");
    endtask

    initial begin
        seed = 32'hC0FFEE;
        for (int r = 0; r < WIN; r++) for (int c = 0; c < WIN; c++) patch[r][c] = 8'(100 + rnd()%41);
        repeat (5) @(negedge clk); rst_n = 1; repeat (3) @(negedge clk);
        for (int i = 0; i < WIN*WIN; i++) begin @(negedge clk); tw = 1; twi = i; twd = patch[i/WIN][i%WIN]; end
        @(negedge clk); tw = 0; repeat (4) @(negedge clk);
        @(negedge clk); fdone = 1; @(negedge clk); fdone = 0;

        for (int k = 0; k < 3; k++) begin
            make_field(0,  100+k, 33, 4);
            make_field(FL, 200+k, 33, 11);
`ifdef PER_FIELD
            if (`GATE) begin
                // kept field = whichever follows reset (here: B). Nothing to report until the first
                // kept field has finished; after that the result must be constant.
                stream(0);  vs($sformatf("frame %0d: after field A (dropped)", k), (k==0) ? 0 : 33, (k==0) ? 0 : 11);
                stream(FL); vs($sformatf("frame %0d: after field B (kept)", k), 33, 11);
            end else begin
                stream(0);  vs($sformatf("frame %0d: after field A", k), 33, 4);
                stream(FL); vs($sformatf("frame %0d: after field B", k), 33, 11);
            end
`else
            stream(0); stream(FL); vs($sformatf("frame %0d: after A+B lines", k), 33, 4);
`endif
        end
        $finish;
    end
endmodule
