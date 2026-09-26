// tb_conv_layer.sv -- drives one conv_layer instance (parameters overridden
// per layer at build time via Verilator's -G flags, see Makefile) through
// NTILES tiles back-to-back, feeding it from a behavioral fake fmap source
// and draining into a behavioral sink, checking output fmap words against
// vectors/tile0_layer{LAYER}.hex (tile 0's dump, replayed NTILES times) and
// measuring the steady-state cycles/tile.
`timescale 1ns/1ps
module tb_conv_layer #(
    parameter int LAYER   = 0,
    parameter int CIN     = 3,
    parameter int COUT    = 16,
    parameter int IN_HW   = 16,
    parameter int OUT_HW  = 8,
    parameter int STRIDE  = 2,
    parameter int CIN_PAR = 3,
    parameter int NPASS   = 1,
    parameter int NTILES  = 8
);
  localparam int NPIX_IN  = IN_HW*IN_HW;
  localparam int NPIX_OUT = OUT_HW*OUT_HW;
  localparam int TAG_W = 16;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic          in_rd_ready;
  logic          in_rd_start;
  logic [TAG_W-1:0] in_rd_tag;
  logic [$clog2(NPIX_IN)-1:0] in_rd_addr;
  logic [CIN*8-1:0] in_rd_data;
  logic          in_rd_done;

  logic          out_wr_ready;
  logic          out_wr_start;
  logic [TAG_W-1:0] out_wr_tag;
  logic          out_wr_en;
  logic [$clog2(NPIX_OUT)-1:0] out_wr_addr;
  logic [COUT*8-1:0] out_wr_data;
  logic          out_wr_done;

  conv_layer #(
      .CIN(CIN), .COUT(COUT), .IN_HW(IN_HW), .OUT_HW(OUT_HW), .STRIDE(STRIDE), .PAD(1),
      .CIN_PAR(CIN_PAR), .NPASS(NPASS), .LAYER(LAYER),
      .OUT_ZP(0), .TILE_TAG_W(TAG_W)
  ) dut (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(in_rd_ready), .in_rd_start(in_rd_start), .in_rd_tag(in_rd_tag),
      .in_rd_addr(in_rd_addr), .in_rd_data(in_rd_data), .in_rd_done(in_rd_done),
      .out_wr_ready(out_wr_ready), .out_wr_start(out_wr_start), .out_wr_tag(out_wr_tag),
      .out_wr_en(out_wr_en), .out_wr_addr(out_wr_addr), .out_wr_data(out_wr_data),
      .out_wr_done(out_wr_done)
  );

  logic [7:0] in_mem [0:NPIX_IN-1][0:CIN-1];
  logic [7:0] exp_mem [0:NPIX_OUT-1][0:COUT-1];

  logic in_bank_full;
  logic in_bank_reading;
  int tiles_fed = 0;

  assign in_rd_ready = in_bank_full && !in_bank_reading;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      in_bank_full <= 1'b1;
      in_bank_reading <= 1'b0;
    end else begin
      if (in_rd_start) in_bank_reading <= 1'b1;
      if (in_rd_done) begin
        in_bank_reading <= 1'b0;
        tiles_fed++;
        if (tiles_fed < NTILES) in_bank_full <= 1'b1;
        else in_bank_full <= 1'b0;
      end
    end
  end
  assign in_rd_tag = tiles_fed[TAG_W-1:0];

  // matches fmap_pingpong's real read port: 1-cycle synchronous latency
  always_ff @(posedge clk) begin
    for (int ci = 0; ci < CIN; ci++)
      in_rd_data[ci*8 +: 8] <= in_mem[in_rd_addr][ci];
  end

  assign out_wr_ready = 1'b1;
  int tiles_done = 0;
  int errors = 0;
  logic [7:0] out_capture [0:NPIX_OUT-1][0:COUT-1];
  longint unsigned tile_start_cycle;
  longint unsigned cyc = 0;
  longint unsigned interval_last = 0;

  always_ff @(posedge clk) cyc <= cyc + 1;

  always_ff @(posedge clk) begin
    if (out_wr_en) begin
      for (int co = 0; co < COUT; co++)
        out_capture[out_wr_addr][co] <= out_wr_data[co*8 +: 8];
    end
    if (out_wr_start) tile_start_cycle <= cyc;
    if (out_wr_done) begin
      interval_last <= cyc - tile_start_cycle;
      tiles_done++;
      for (int p = 0; p < NPIX_OUT; p++) begin
        for (int co = 0; co < COUT; co++) begin
          if (out_capture[p][co] !== exp_mem[p][co]) begin
            $display("FAIL tile %0d pix %0d ch %0d: got=%0d exp=%0d", tiles_done-1, p, co,
                      out_capture[p][co], exp_mem[p][co]);
            errors++;
          end
        end
      end
      $display("tile %0d done: interval=%0d cycles", tiles_done-1, cyc - tile_start_cycle);
    end
  end

  initial begin
    int fd, r;
    logic [255:0] word;   // wide enough for COUT*8 up to 32 channels
    if (LAYER == 0) begin
      fd = $fopen("vectors/tiles.hex", "r");
      for (int p = 0; p < NPIX_IN; p++) begin
        r = $fscanf(fd, "%h\n", word);
        in_mem[p][0] = word[7:0]; in_mem[p][1] = word[15:8]; in_mem[p][2] = word[23:16];
      end
      $fclose(fd);
    end else begin
      fd = $fopen($sformatf("vectors/tile0_layer%0d.hex", LAYER-1), "r");
      for (int p = 0; p < NPIX_IN; p++) begin
        r = $fscanf(fd, "%h\n", word);
        for (int ci = 0; ci < CIN; ci++) in_mem[p][ci] = word[ci*8 +: 8];
      end
      $fclose(fd);
    end

    fd = $fopen($sformatf("vectors/tile0_layer%0d.hex", LAYER), "r");
    for (int p = 0; p < NPIX_OUT; p++) begin
      r = $fscanf(fd, "%h\n", word);
      for (int co = 0; co < COUT; co++) exp_mem[p][co] = word[co*8 +: 8];
    end
    $fclose(fd);

    rst_n = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;

    wait (tiles_done == NTILES);
    repeat (5) @(posedge clk);

    if (errors == 0) $display("PASS %0d/%0d tiles, last interval=%0d cycles", tiles_done, NTILES, interval_last);
    else $display("FAIL %0d", errors);
    $finish;
  end

  initial begin
    #5000000;
    $display("FAIL: timeout");
    $finish;
  end
endmodule
