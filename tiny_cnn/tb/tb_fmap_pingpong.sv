// tb_fmap_pingpong.sv -- U3: producer writes N tiles (tag=index, data=addr+tag*1000),
// consumer reads them back with random stalls on both sides; checks tag order
// and data content; also asserts a bank is never written while not FREE/WRITING
// as seen from the outside (implicitly, by wr_ready gating).
`timescale 1ns/1ps
module tb_fmap_pingpong;
  localparam int WORD_W = 16;
  localparam int DEPTH  = 32;
  localparam int TAG_W  = 12;
  localparam int NTILES = 500;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic wr_ready, wr_start; logic [TAG_W-1:0] wr_tag;
  logic wr_en; logic [$clog2(DEPTH)-1:0] wr_addr; logic [WORD_W-1:0] wr_data; logic wr_done;
  logic rd_ready, rd_start; logic [TAG_W-1:0] rd_tag;
  logic [$clog2(DEPTH)-1:0] rd_addr; logic [WORD_W-1:0] rd_data; logic rd_done;

  fmap_pingpong #(.WORD_W(WORD_W), .DEPTH(DEPTH), .TAG_W(TAG_W)) dut (
      .clk(clk), .rst_n(rst_n),
      .wr_ready(wr_ready), .wr_start(wr_start), .wr_tag(wr_tag),
      .wr_en(wr_en), .wr_addr(wr_addr), .wr_data(wr_data), .wr_done(wr_done),
      .rd_ready(rd_ready), .rd_start(rd_start), .rd_tag(rd_tag),
      .rd_addr(rd_addr), .rd_data(rd_data), .rd_done(rd_done)
  );

  int errors = 0;
  int unsigned wr_done_count = 0;
  int unsigned rd_done_count = 0;

  // producer process
  initial begin
    wr_start = 0; wr_en = 0; wr_addr = '0; wr_data = '0; wr_done = 0; wr_tag = '0;
    wait(rst_n);
    @(posedge clk);
    for (int t = 0; t < NTILES; t++) begin
      while (!wr_ready) @(posedge clk);
      wr_start = 1; wr_tag = t[TAG_W-1:0];
      @(posedge clk);
      wr_start = 0;
      for (int a = 0; a < DEPTH; a++) begin
        if ($urandom_range(0,4)==0) begin // random stall
          wr_en = 0; @(posedge clk);
        end
        wr_en = 1; wr_addr = a[$clog2(DEPTH)-1:0]; wr_data = a[WORD_W-1:0] + t*1000;
        @(posedge clk);
      end
      wr_en = 0;
      wr_done = 1;
      @(posedge clk);
      wr_done = 0;
      wr_done_count++;
    end
  end

  // consumer process
  initial begin
    logic [WORD_W-1:0] exp;
    rd_start = 0; rd_addr = '0; rd_done = 0;
    wait(rst_n);
    @(posedge clk);
    for (int t = 0; t < NTILES; t++) begin
      while (!rd_ready) @(posedge clk);
      rd_start = 1;
      @(posedge clk);
      rd_start = 0;
      if (rd_tag !== t[TAG_W-1:0]) begin
        $display("FAIL: tile %0d got tag %0d", t, rd_tag);
        errors++;
      end
      for (int a = 0; a < DEPTH; a++) begin
        if ($urandom_range(0,4)==0) @(posedge clk); // random stall before issuing addr
        rd_addr = a[$clog2(DEPTH)-1:0];
        @(posedge clk);
        @(posedge clk); // wait for 1-cycle read latency
        exp = a[WORD_W-1:0] + t*1000;
        if (rd_data !== exp) begin
          $display("FAIL: tile %0d addr %0d got %0d exp %0d", t, a, rd_data, exp);
          errors++;
        end
      end
      rd_done = 1;
      @(posedge clk);
      rd_done = 0;
      rd_done_count++;
    end

    repeat (10) @(posedge clk);
    if (wr_done_count != NTILES || rd_done_count != NTILES) begin
      $display("FAIL: wr_done_count=%0d rd_done_count=%0d exp=%0d", wr_done_count, rd_done_count, NTILES);
      errors++;
    end
    if (errors == 0) $display("PASS %0d/%0d", rd_done_count, NTILES);
    else $display("FAIL %0d", errors);
    $finish;
  end

  initial begin
    rst_n = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;
  end

  initial begin
    #2000000;
    $display("FAIL: timeout");
    $finish;
  end
endmodule
