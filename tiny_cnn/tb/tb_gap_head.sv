// tb_gap_head.sv -- drives gap_head with 8 back-to-back tiles from
// vectors/tile0_layer3.hex (the golden L3 output for tile 0, replayed), and
// checks the emitted logits against vectors/tiles_expected.hex line 0.
`timescale 1ns/1ps
module tb_gap_head #(
    parameter int NTILES = 8
);
  localparam int COUT_IN = 32;
  localparam int N_SPATIAL = 16;
  localparam int TAG_W = 16;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic in_rd_ready, in_rd_start;
  logic [TAG_W-1:0] in_rd_tag;
  logic [$clog2(N_SPATIAL)-1:0] in_rd_addr;
  logic [COUT_IN*8-1:0] in_rd_data;
  logic in_rd_done;

  logic res_valid;
  logic [TAG_W-1:0] res_tag;
  logic [7:0] res_logit0, res_logit1;

  gap_head #(
      .COUT_IN(COUT_IN), .N_SPATIAL(N_SPATIAL), .HEAD_COUT(2),
      .GAP_MULT(1140694085), .GAP_SHIFT(33), .GAP_OUT_ZP(0),
      .HEAD_MULT0(1151030682), .HEAD_SHIFT0(33),
      .HEAD_MULT1(1209549403), .HEAD_SHIFT1(33),
      .LOGIT_ZP(123), .TILE_TAG_W(TAG_W)
  ) dut (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(in_rd_ready), .in_rd_start(in_rd_start), .in_rd_tag(in_rd_tag),
      .in_rd_addr(in_rd_addr), .in_rd_data(in_rd_data), .in_rd_done(in_rd_done),
      .res_valid(res_valid), .res_tag(res_tag), .res_logit0(res_logit0), .res_logit1(res_logit1)
  );

  logic [7:0] in_mem [0:N_SPATIAL-1][0:COUT_IN-1];
  logic in_bank_full, in_bank_reading;
  int tiles_fed = 0;
  assign in_rd_ready = in_bank_full && !in_bank_reading;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin in_bank_full <= 1'b1; in_bank_reading <= 1'b0; end
    else begin
      if (in_rd_start) in_bank_reading <= 1'b1;
      if (in_rd_done) begin
        in_bank_reading <= 1'b0; tiles_fed++;
        in_bank_full <= (tiles_fed < NTILES);
      end
    end
  end
  assign in_rd_tag = tiles_fed[TAG_W-1:0];

  always_ff @(posedge clk) begin
    for (int c = 0; c < COUT_IN; c++)
      in_rd_data[c*8 +: 8] <= in_mem[in_rd_addr][c];
  end

  int tiles_done = 0, errors = 0;
  logic [7:0] exp0, exp1;

  initial begin
    int fd, r;
    logic [255:0] word;
    fd = $fopen("vectors/tile0_layer3.hex", "r");
    for (int p = 0; p < N_SPATIAL; p++) begin
      r = $fscanf(fd, "%h\n", word);
      for (int c = 0; c < COUT_IN; c++) in_mem[p][c] = word[c*8 +: 8];
    end
    $fclose(fd);

    fd = $fopen("vectors/tiles_expected.hex", "r");
    r = $fscanf(fd, "%h %h\n", exp0, exp1);
    $fclose(fd);

    rst_n = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;

    wait (tiles_done == NTILES);
    repeat (5) @(posedge clk);
    if (errors == 0) $display("PASS %0d/%0d", tiles_done, NTILES);
    else $display("FAIL %0d", errors);
    $finish;
  end

  always_ff @(posedge clk) begin
    if (res_valid) begin
      tiles_done++;
      if (res_logit0 !== exp0 || res_logit1 !== exp1) begin
        $display("FAIL tile %0d: got=(%0d,%0d) exp=(%0d,%0d)", tiles_done-1, res_logit0, res_logit1, exp0, exp1);
        errors++;
      end else begin
        $display("tile %0d: logits=(%0d,%0d) OK", tiles_done-1, res_logit0, res_logit1);
      end
    end
  end

  initial begin
    #2000000;
    $display("FAIL: timeout");
    $finish;
  end
endmodule
