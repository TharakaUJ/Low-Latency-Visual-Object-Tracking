// tb_slave.sv -- Gate S1: drives tcnn_avalon_slave.sv through an Avalon-MM
// bus-functional model (same task style as
// fpga_cnn_pipeline/tb/tb_cnn_slave.sv): register sanity, strip upload via
// STRIP_ADDR/STRIP_DATA, run frames, read results back via RES_ADDR/RES_DATA,
// check counters. Uses the small 64x48 vectors (12 tiles/frame) so the test
// stays fast; Gate F1 (tb_top) already proved bit-exactness at full 640x480.
`timescale 1ns/1ps
module tb_slave;
  localparam int MAX_W = 640;
  localparam int MAX_STRIP_H = 48;
  localparam string STRIP_HEX = "vectors/strip_rand64x48.hex";
  localparam string EXPECTED_CSV = "vectors/frame_rand64x48_64x48_expected.csv";
  localparam int FRAME_W = 64;
  localparam int FRAME_H = 48;
  localparam int STRIP_H = 48;
  localparam int NFRAMES = 2;
  localparam int PITCH = MAX_W/16;

  logic clk = 0, rst_n = 0;
  logic [4:0]  avs_address;
  logic        avs_read, avs_write;
  logic [31:0] avs_writedata, avs_readdata;
  logic        avs_waitrequest;

  tcnn_avalon_slave #(.MAX_W(MAX_W), .MAX_STRIP_H(MAX_STRIP_H), .GEN_DIR("gen/")) dut (
      .clk(clk), .rst_n(rst_n),
      .avs_address(avs_address), .avs_read(avs_read), .avs_readdata(avs_readdata),
      .avs_write(avs_write), .avs_writedata(avs_writedata), .avs_waitrequest(avs_waitrequest)
  );
  always #5 clk = ~clk;

  logic [31:0] rd_val;
  task automatic avs_wr(input [4:0] addr, input [31:0] data);
    avs_address = addr; avs_writedata = data; avs_write = 1'b1; avs_read = 1'b0;
    @(posedge clk); #1;
    avs_write = 1'b0;
  endtask
  task automatic avs_rd(input [4:0] addr, output [31:0] data);
    avs_address = addr; avs_read = 1'b1; avs_write = 1'b0;
    @(posedge clk); #1;
    data = avs_readdata;
    avs_read = 1'b0;
  endtask

  int errors;
  task automatic expect_eq(input [31:0] got, input [31:0] exp, input string what);
    if (got !== exp) begin
      $display("FAIL: %s: got %0d (0x%h) expected %0d (0x%h)", what, got, got, exp, exp);
      errors++;
    end
  endtask

  task automatic test_registers();
    avs_rd(5'd0, rd_val);
    expect_eq(rd_val, 32'h5443_4E31, "ID");
    avs_rd(5'd1, rd_val);
    expect_eq(rd_val[7:0], 8'h0A, "VERSION.interval_code");
    for (int i = 0; i < 20; i++) begin
      logic [31:0] v;
      v = $urandom();
      avs_wr(5'd2, v);
      avs_rd(5'd2, rd_val);
      expect_eq(rd_val, v, "SCRATCH readback");
    end
    $display("S1a (registers) done, errors so far=%0d", errors);
  endtask

  // upload the strip through STRIP_ADDR/STRIP_DATA (address auto-increments
  // on the RTL side after each STRIP_DATA write), then run NFRAMES frames and
  // check every result via RES_ADDR/RES_DATA against the expected CSV.
  task automatic test_run();
    int fd, r;
    logic [23:0] word;
    int idx;
    int band, tcol, l0, l1;
    string line;
    int n_expected;
    int exp_band [0:4095], exp_tcol [0:4095], exp_l0 [0:4095], exp_l1 [0:4095];

    avs_wr(5'd9, 32'h0);   // STRIP_ADDR = 0
    fd = $fopen(STRIP_HEX, "r");
    idx = 0;
    while (!$feof(fd)) begin
      automatic int row = idx / FRAME_W;
      automatic int col = idx % FRAME_W;
      r = $fscanf(fd, "%h\n", word);
      if (r != 1) break;
      // strip_addr auto-increments by 1 per STRIP_DATA write on the RTL
      // side, so re-seed STRIP_ADDR whenever the tight-packed source index
      // and the fixed-pitch (MAX_W) destination address diverge (i.e. every
      // row boundary, since FRAME_W < MAX_W here).
      if (col == 0) avs_wr(5'd9, row*MAX_W);
      avs_wr(5'd10, {8'h0, word});
      idx++;
    end
    $fclose(fd);
    $display("S1b: uploaded %0d strip words", idx);

    fd = $fopen(EXPECTED_CSV, "r");
    r = $fgets(line, fd); // header
    n_expected = 0;
    while (!$feof(fd)) begin
      r = $fscanf(fd, "%d,%d,%d,%d\n", band, tcol, l0, l1);
      if (r != 4) break;
      exp_band[n_expected] = band; exp_tcol[n_expected] = tcol;
      exp_l0[n_expected] = l0; exp_l1[n_expected] = l1;
      n_expected++;
    end
    $fclose(fd);
    $display("S1b: loaded %0d expected result rows", n_expected);

    avs_wr(5'd5, FRAME_W);
    avs_wr(5'd6, FRAME_H);
    avs_wr(5'd7, STRIP_H);
    avs_wr(5'd8, NFRAMES);
    avs_wr(5'd3, 32'h0000_0001);  // CTRL.start

    begin
      int timeout;
      timeout = 0;
      avs_rd(5'd4, rd_val);
      while (!rd_val[1] && timeout < 2_000_000) begin
        avs_rd(5'd4, rd_val);
        timeout++;
      end
      if (!rd_val[1]) begin
        $display("FAIL: STATUS.done never asserted (timeout)");
        errors++;
      end
    end

    begin
      int row_errors = 0;
      logic [31:0] cyc, tdone, mism, mn, mx;
      for (int i = 0; i < n_expected; i++) begin
        automatic int addr = exp_band[i]*PITCH + exp_tcol[i];
        avs_wr(5'd11, addr);
        avs_rd(5'd12, rd_val);
        if (rd_val[7:0] !== exp_l0[i][7:0] || rd_val[15:8] !== exp_l1[i][7:0]) begin
          $display("FAIL band=%0d tcol=%0d got=(%0d,%0d) exp=(%0d,%0d)",
                    exp_band[i], exp_tcol[i], rd_val[7:0], rd_val[15:8], exp_l0[i], exp_l1[i]);
          row_errors++;
        end
      end
      avs_rd(5'd13, cyc); avs_rd(5'd14, tdone); avs_rd(5'd15, mism);
      avs_rd(5'd16, mn); avs_rd(5'd17, mx);
      $display("S1b: cycles=%0d tiles_done=%0d res_mismatch=%0d min_gap=%0d max_gap=%0d",
                cyc, tdone, mism, mn, mx);
      expect_eq(mism, 32'd0, "RES_MISMATCH");
      if (row_errors == 0) $display("S1b PASS %0d/%0d rows", n_expected, n_expected);
      else begin
        $display("S1b FAIL %0d row errors", row_errors);
        errors += row_errors;
      end
    end
  endtask

  initial begin
    errors = 0;
    rst_n = 0; avs_address = 0; avs_read = 0; avs_write = 0; avs_writedata = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;
    @(posedge clk); #1;

    test_registers();
    test_run();
    // regression: a SECOND top-level run (separate CTRL.start pulse, after
    // the first has fully reached done) must also work -- frame_player's
    // P_DONE state used to only leave for P_IDLE on this pulse, silently
    // consuming it without ever reaching P_RUN, so every other run produced
    // zero pixels and stalled (found via board bring-up).
    test_run();

    if (errors == 0) $display("PASS");
    else $display("FAIL: %0d errors", errors);
    $finish;
  end

  initial begin
    #200000000;
    $display("FAIL: timeout");
    $finish;
  end
endmodule
