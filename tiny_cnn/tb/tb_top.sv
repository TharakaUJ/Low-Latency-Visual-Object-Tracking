// tb_top.sv -- Gate F1: uploads a strip, replays it as NFRAMES full frames
// through frame_player -> tile_feeder -> tcnn_core -> result_sink, checks
// every result bit-exact against the expected CSV (frame 0's positions
// repeat for every later frame, since the strip repeats), and reports
// measured cycles / fps / RES_MISMATCH.
`timescale 1ns/1ps
module tb_top #(
    parameter string STRIP_HEX = "vectors/strip_rand64x48.hex",
    parameter string EXPECTED_CSV = "vectors/frame_rand64x48_64x48_expected.csv",
    parameter int FRAME_W = 64,
    parameter int FRAME_H = 48,
    parameter int STRIP_H = 48,
    parameter int NFRAMES = 2,
    parameter int MAX_W = 640,
    parameter int MAX_STRIP_H = 48
);
  localparam int TAG_W = 16;
  localparam int PITCH = MAX_W/16;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic strip_wr_en;
  logic [$clog2(MAX_W*MAX_STRIP_H)-1:0] strip_wr_addr;
  logic [23:0] strip_wr_data;
  logic start;
  logic [15:0] frame_w, frame_h, strip_h, nframes;
  logic [31:0] cycles, tiles_done, res_mismatch, min_gap, max_gap;
  logic run_done;
  logic [15:0] res_rd_addr;
  logic [15:0] res_rd_data;

  tcnn_top_sim #(.MAX_W(MAX_W), .MAX_STRIP_H(MAX_STRIP_H), .GEN_DIR("gen/"), .TILE_TAG_W(TAG_W)) dut (
      .clk(clk), .rst_n(rst_n),
      .strip_wr_en(strip_wr_en), .strip_wr_addr(strip_wr_addr), .strip_wr_data(strip_wr_data),
      .start(start), .frame_w(frame_w), .frame_h(frame_h), .strip_h(strip_h), .nframes(nframes),
      .cycles(cycles), .tiles_done(tiles_done), .res_mismatch(res_mismatch),
      .min_gap(min_gap), .max_gap(max_gap), .run_done(run_done),
      .res_rd_addr(res_rd_addr), .res_rd_data(res_rd_data)
  );

  int n_expected;
  logic [15:0] exp_band [0:4095];
  logic [15:0] exp_tcol [0:4095];
  logic [7:0]  exp_l0 [0:4095];
  logic [7:0]  exp_l1 [0:4095];

  initial begin
    int fd, r;
    int band, tcol, l0, l1;
    string line;
    logic [23:0] word;
    int idx;

    // the strip file is packed tightly at FRAME_W per row, but frame_player's
    // strip_mem is addressed at a FIXED pitch of MAX_W (so the address never
    // depends on a runtime frame width) -- re-pitch on upload.
    // one throwaway edge before the first real write: without it, the very
    // first upload write (address 0) races the first posedge of `clk` and
    // is silently missed in this simulator, even though `strip_wr_en` was
    // set with a blocking assignment "before" it — a testbench-only
    // artifact (every other address uploads fine; only address 0 in a run
    // was ever affected). Costs one cycle, harmless.
    @(posedge clk);
    fd = $fopen(STRIP_HEX, "r");
    idx = 0;
    while (!$feof(fd)) begin
      automatic int row = idx / FRAME_W;
      automatic int col = idx % FRAME_W;
      r = $fscanf(fd, "%h\n", word);
      if (r != 1) break;
      strip_wr_addr = (row*MAX_W + col);
      strip_wr_data = word;
      strip_wr_en = 1'b1;
      @(posedge clk);
      idx++;
    end
    strip_wr_en = 1'b0;
    $fclose(fd);
    $display("uploaded %0d strip words", idx);

    fd = $fopen(EXPECTED_CSV, "r");
    r = $fgets(line, fd); // header
    n_expected = 0;
    while (!$feof(fd)) begin
      r = $fscanf(fd, "%d,%d,%d,%d\n", band, tcol, l0, l1);
      if (r != 4) break;
      exp_band[n_expected] = band[15:0];
      exp_tcol[n_expected] = tcol[15:0];
      exp_l0[n_expected] = l0[7:0];
      exp_l1[n_expected] = l1[7:0];
      n_expected++;
    end
    $fclose(fd);
    $display("loaded %0d expected result rows", n_expected);

    frame_w = FRAME_W; frame_h = FRAME_H; strip_h = STRIP_H; nframes = NFRAMES;
    start = 1'b0;

    repeat (5) @(posedge clk);
    rst_n = 1'b1;
    @(posedge clk);
    start = 1'b1;
    @(posedge clk);
    start = 1'b0;

    wait (run_done);
    @(posedge clk);

    // check every expected row's stored result (still valid in the RAM
    // after the LAST frame, since mismatches only increment a counter and
    // never overwrite storage after frame 0)
    begin
      int errors = 0;
      for (int i = 0; i < n_expected; i++) begin
        automatic int addr = exp_band[i]*PITCH + exp_tcol[i];
        automatic logic [15:0] got;
        res_rd_addr = addr[15:0];
        @(posedge clk);
        got = res_rd_data;
        if (got[7:0] !== exp_l0[i] || got[15:8] !== exp_l1[i]) begin
          $display("FAIL band=%0d tcol=%0d got=(%0d,%0d) exp=(%0d,%0d)",
                    exp_band[i], exp_tcol[i], got[7:0], got[15:8], exp_l0[i], exp_l1[i]);
          errors++;
        end
      end
      $display("cycles=%0d tiles_done=%0d res_mismatch=%0d min_gap=%0d max_gap=%0d",
                cycles, tiles_done, res_mismatch, min_gap, max_gap);
      if (errors == 0 && res_mismatch == 0)
        $display("PASS %0d/%0d rows, 0 mismatches", n_expected, n_expected);
      else
        $display("FAIL %0d row errors, %0d res_mismatch", errors, res_mismatch);
    end
    $finish;
  end

  initial begin
    #500000000;
    $display("FAIL: timeout");
    $finish;
  end
endmodule
