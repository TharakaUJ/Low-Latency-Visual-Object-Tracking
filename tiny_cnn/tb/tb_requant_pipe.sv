// tb_requant_pipe.sv -- U1: vectors/requant_vectors.txt issued back-to-back
// (a new input every cycle, no gaps), checked in order against the expected
// output byte.
`timescale 1ns/1ps
module tb_requant_pipe;
  localparam int TAG_W = 16;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic                    valid_i;
  logic signed [31:0]      acc_i;
  logic signed [31:0]      mult_i;
  logic [5:0]              shift_i;
  logic signed [15:0]      zp_i;
  logic [TAG_W-1:0]        tag_i;
  logic                    valid_o;
  logic [7:0]              out_u8_o;
  logic [TAG_W-1:0]        tag_o;

  requant_pipe #(.ACC_W(32), .TAG_W(TAG_W)) dut (
      .clk(clk), .rst_n(rst_n),
      .valid_i(valid_i), .acc_i(acc_i), .mult_i(mult_i), .shift_i(shift_i),
      .out_zp_i(zp_i), .tag_i(tag_i),
      .valid_o(valid_o), .out_u8_o(out_u8_o), .tag_o(tag_o)
  );

  int unsigned n_vec;
  logic [31:0] v_acc   [0:20000];
  logic [31:0] v_mult  [0:20000];
  logic [7:0]  v_shift [0:20000];
  logic [7:0]  v_zp    [0:20000];
  logic [7:0]  v_exp   [0:20000];

  int errors = 0, checked = 0;
  logic [7:0] exp_q [$];

  initial begin
    int fd, r;
    logic [31:0] a, m; logic [7:0] s, z, o;
    fd = $fopen("vectors/requant_vectors.txt", "r");
    if (fd == 0) begin
      $display("FAIL: cannot open vectors/requant_vectors.txt");
      $finish;
    end
    n_vec = 0;
    while (!$feof(fd)) begin
      r = $fscanf(fd, "%h %h %h %h %h\n", a, m, s, z, o);
      if (r != 5) begin
        break;
      end
      v_acc[n_vec] = a; v_mult[n_vec] = m; v_shift[n_vec] = s;
      v_zp[n_vec] = z; v_exp[n_vec] = o;
      n_vec++;
    end
    $fclose(fd);
    $display("loaded %0d vectors", n_vec);

    rst_n = 0; valid_i = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;
    @(posedge clk);

    for (int i = 0; i < n_vec; i++) begin
      acc_i   = v_acc[i];
      mult_i  = v_mult[i];
      shift_i = v_shift[i][5:0];
      zp_i    = {8'h0, v_zp[i]};
      tag_i   = i[TAG_W-1:0];
      valid_i = 1'b1;
      exp_q.push_back(v_exp[i]);
      @(posedge clk);
    end
    valid_i = 1'b0;

    repeat (20) @(posedge clk);

    if (checked != n_vec) begin
      $display("FAIL: only checked %0d/%0d", checked, n_vec);
      errors++;
    end
    if (errors == 0) $display("PASS %0d/%0d", checked, n_vec);
    else $display("FAIL %0d", errors);
    $finish;
  end

  always @(posedge clk) begin
    if (valid_o) begin
      automatic logic [7:0] exp;
      if (exp_q.size() == 0) begin
        $display("FAIL: unexpected valid_o, empty queue");
        errors++;
      end else begin
        exp = exp_q.pop_front();
        checked++;
        if (out_u8_o !== exp) begin
          $display("FAIL @%0d: tag=%0d got=%0d exp=%0d", checked, tag_o, out_u8_o, exp);
          errors++;
        end
      end
    end
  end
endmodule
