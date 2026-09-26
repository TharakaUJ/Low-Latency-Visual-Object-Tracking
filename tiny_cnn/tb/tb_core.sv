// tb_core.sv -- C1: pushes vectors/tiles.hex (1000 tiles) through
// tcnn_core's L0in producer port back-to-back (as fast as l0in_wr_ready
// allows), checks every emitted logit pair against
// vectors/tiles_expected.hex bit-exact, IN ORDER (tag = tile index), and
// measures the steady-state cycle interval between consecutive results.
`timescale 1ns/1ps
module tb_core;
  localparam int TAG_W = 16;
  localparam int NTILES = 1000;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic l0in_wr_ready, l0in_wr_start;
  logic [TAG_W-1:0] l0in_wr_tag;
  logic l0in_wr_en;
  logic [$clog2(16*16)-1:0] l0in_wr_addr;
  logic [3*8-1:0] l0in_wr_data;
  logic l0in_wr_done;

  logic res_valid;
  logic [TAG_W-1:0] res_tag;
  logic [7:0] res_logit0, res_logit1;
  logic [31:0] dbg_tiles_committed;

  tcnn_core #(.GEN_DIR("gen/"), .TILE_TAG_W(TAG_W)) dut (
      .clk(clk), .rst_n(rst_n),
      .l0in_wr_ready(l0in_wr_ready), .l0in_wr_start(l0in_wr_start), .l0in_wr_tag(l0in_wr_tag),
      .l0in_wr_en(l0in_wr_en), .l0in_wr_addr(l0in_wr_addr), .l0in_wr_data(l0in_wr_data), .l0in_wr_done(l0in_wr_done),
      .res_valid(res_valid), .res_tag(res_tag), .res_logit0(res_logit0), .res_logit1(res_logit1),
      .dbg_tiles_committed(dbg_tiles_committed)
  );

  logic [23:0] tile_mem [0:NTILES-1][0:255];
  logic [7:0]  exp0 [0:NTILES-1];
  logic [7:0]  exp1 [0:NTILES-1];

  // producer: push tiles as fast as wr_ready allows
  int tiles_pushed = 0;
  initial begin
    l0in_wr_start = 0; l0in_wr_tag = '0; l0in_wr_en = 0; l0in_wr_addr = '0; l0in_wr_data = '0; l0in_wr_done = 0;
    wait (rst_n);
    @(posedge clk);
    for (int t = 0; t < NTILES; t++) begin
      while (!l0in_wr_ready) @(posedge clk);
      l0in_wr_start = 1'b1;
      l0in_wr_tag   = t[TAG_W-1:0];
      @(posedge clk);
      l0in_wr_start = 1'b0;
      for (int a = 0; a < 256; a++) begin
        l0in_wr_en   = 1'b1;
        l0in_wr_addr = a[$clog2(256)-1:0];
        l0in_wr_data = tile_mem[t][a][23:0];
        @(posedge clk);
      end
      l0in_wr_en = 1'b0;
      l0in_wr_done = 1'b1;
      @(posedge clk);
      l0in_wr_done = 1'b0;
      tiles_pushed++;
    end
  end

  int errors = 0;
  int tiles_checked = 0;
  longint unsigned cyc = 0;
  longint unsigned last_res_cyc = 0;
  longint unsigned min_gap = 64'hFFFFFFFF, max_gap = 0;

  always_ff @(posedge clk) cyc <= cyc + 1;

  always_ff @(posedge clk) begin
    if (res_valid) begin
      automatic longint unsigned gap = cyc - last_res_cyc;
      if (tiles_checked > 0) begin
        if (gap < min_gap) min_gap = gap;
        if (gap > max_gap) max_gap = gap;
      end
      last_res_cyc = cyc;
      if (res_tag != tiles_checked[TAG_W-1:0]) begin
        $display("FAIL: out-of-order result, got tag=%0d expected tile=%0d", res_tag, tiles_checked);
        errors++;
      end else if (res_logit0 !== exp0[tiles_checked] || res_logit1 !== exp1[tiles_checked]) begin
        $display("FAIL tile %0d: got=(%0d,%0d) exp=(%0d,%0d)", tiles_checked, res_logit0, res_logit1,
                  exp0[tiles_checked], exp1[tiles_checked]);
        errors++;
      end
      tiles_checked++;
    end
  end

  initial begin
    int fd, r;
    logic [23:0] pxword;
    fd = $fopen("vectors/tiles.hex", "r");
    for (int t = 0; t < NTILES; t++)
      for (int a = 0; a < 256; a++) begin
        r = $fscanf(fd, "%h\n", pxword);
        tile_mem[t][a] = pxword;
      end
    $fclose(fd);

    fd = $fopen("vectors/tiles_expected.hex", "r");
    for (int t = 0; t < NTILES; t++) begin
      r = $fscanf(fd, "%h %h\n", exp0[t], exp1[t]);
    end
    $fclose(fd);

    rst_n = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;

    wait (tiles_checked == NTILES);
    repeat (5) @(posedge clk);

    if (errors == 0)
      $display("PASS %0d/%0d tiles, min_gap=%0d max_gap=%0d cycles", tiles_checked, NTILES, min_gap, max_gap);
    else
      $display("FAIL %0d", errors);
    $finish;
  end

  initial begin
    #200000000;
    $display("FAIL: timeout, checked %0d/%0d", tiles_checked, NTILES);
    $finish;
  end
endmodule
