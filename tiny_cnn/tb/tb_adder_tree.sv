// tb_adder_tree.sv -- U2: random N-input vectors issued back-to-back (a new
// input every cycle), checked against a software sum, tag kept aligned.
`timescale 1ns/1ps
module tb_adder_tree;
  localparam int N = 27;
  localparam int W = 16;
  localparam int TAG_W = 10;
  localparam int NVEC = 5000;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic                valid_i;
  logic signed [W-1:0] din_i [N];
  logic [TAG_W-1:0]    tag_i;
  logic                valid_o;
  logic signed [W-1:0] dout_o;
  logic [TAG_W-1:0]    tag_o;

  adder_tree #(.N(N), .W(W), .REG_EVERY(2), .TAG_W(TAG_W)) dut (
      .clk(clk), .rst_n(rst_n), .valid_i(valid_i), .din_i(din_i), .tag_i(tag_i),
      .valid_o(valid_o), .dout_o(dout_o), .tag_o(tag_o)
  );

  // reference queue: (tag, expected sum)
  int unsigned exp_tag  [$];
  logic signed [W-1:0] exp_sum [$];

  int errors = 0;
  int sent = 0, checked = 0;

  initial begin
    rst_n = 0; valid_i = 0; tag_i = '0;
    for (int i = 0; i < N; i++) din_i[i] = '0;
    repeat (5) @(posedge clk);
    rst_n = 1;
    @(posedge clk);

    for (int v = 0; v < NVEC; v++) begin
      automatic logic signed [W-1:0] arr [N];
      automatic longint sum = 0;
      for (int i = 0; i < N; i++) begin
        arr[i] = $urandom_range(0, (1<<W)-1) - (1<<(W-1))/4; // biased small range, avoids overflow
        sum += arr[i];
      end
      din_i  = arr;
      tag_i  = v[TAG_W-1:0];
      valid_i = 1'b1;
      exp_tag.push_back(v);
      exp_sum.push_back(sum[W-1:0]);
      @(posedge clk);
      sent++;
    end
    valid_i = 1'b0;
    for (int i = 0; i < N; i++) din_i[i] = '0;

    // drain latency
    repeat (40) @(posedge clk);

    if (checked != NVEC) begin
      $display("FAIL: only checked %0d/%0d vectors (missing outputs)", checked, NVEC);
      errors++;
    end

    if (errors == 0) $display("PASS %0d/%0d", checked, NVEC);
    else $display("FAIL %0d", errors);
    $finish;
  end

  always @(posedge clk) begin
    if (valid_o) begin
      automatic int et;
      automatic logic signed [W-1:0] es;
      if (exp_tag.size() == 0) begin
        $display("FAIL: unexpected valid_o with empty expected queue at t=%0t", $time);
        errors++;
      end else begin
        et = exp_tag.pop_front();
        es = exp_sum.pop_front();
        checked++;
        if (tag_o !== et[TAG_W-1:0] || dout_o !== es) begin
          $display("FAIL @%0d: tag_o=%0d exp=%0d dout_o=%0d exp=%0d", checked, tag_o, et, dout_o, es);
          errors++;
        end
      end
    end
  end
endmodule
