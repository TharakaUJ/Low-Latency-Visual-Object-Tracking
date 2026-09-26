// adder_tree.sv -- parameterized signed N-input adder tree with a pipeline
// register inserted every REG_EVERY combinational addition levels, and a
// valid/tag bus carried alongside the data through the same registers so a
// caller never has to hand-compute the tree's latency.
//
// Timing rule (docs/implementation_plan.md): at most REG_EVERY (default 2)
// combinational adder levels between registers. All N inputs must already be
// the same width W (sign-extend before instantiating) -- this avoids any
// width growth bookkeeping across recursion levels.
//
// Internally implemented as a self-instantiating (recursive) generate: each
// level pairwise-sums N inputs down to ceil(N/2), optionally registers, and
// recurses until N==1. This produces a balanced tree without hand-unrolling
// per N.

module adder_tree #(
    parameter int N         = 8,
    parameter int W         = 16,   // width of every element (already sign-extended to the final width)
    parameter int REG_EVERY = 2,
    parameter int TAG_W     = 1
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  valid_i,
    input  logic signed [W-1:0]   din_i [N],
    input  logic [TAG_W-1:0]      tag_i,
    output logic                  valid_o,
    output logic signed [W-1:0]   dout_o,
    output logic [TAG_W-1:0]      tag_o
);
  adder_stage #(.N(N), .W(W), .REG_EVERY(REG_EVERY), .TAG_W(TAG_W), .LEVEL(0)) u_stage (
      .clk     (clk),
      .rst_n   (rst_n),
      .valid_i (valid_i),
      .din_i   (din_i),
      .tag_i   (tag_i),
      .valid_o (valid_o),
      .dout_o  (dout_o),
      .tag_o   (tag_o)
  );
endmodule


module adder_stage #(
    parameter int N         = 8,
    parameter int W         = 16,
    parameter int REG_EVERY = 2,
    parameter int TAG_W     = 1,
    parameter int LEVEL     = 0     // combinational levels since the last register
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  valid_i,
    input  logic signed [W-1:0]   din_i [N],
    input  logic [TAG_W-1:0]      tag_i,
    output logic                  valid_o,
    output logic signed [W-1:0]   dout_o,
    output logic [TAG_W-1:0]      tag_o
);
  generate
    if (N == 1) begin : g_base
      assign dout_o  = din_i[0];
      assign valid_o = valid_i;
      assign tag_o   = tag_i;
    end else begin : g_rec
      localparam int N0 = (N + 1) / 2;
      logic signed [W-1:0] sum [N0];
      genvar i;
      for (i = 0; i < N0; i++) begin : g_pairs
        if (2 * i + 1 < N) begin : g_pair
          assign sum[i] = din_i[2*i] + din_i[2*i+1];
        end else begin : g_odd
          assign sum[i] = din_i[2*i];
        end
      end

      localparam bit DO_REG = ((LEVEL + 1) % REG_EVERY == 0);
      if (DO_REG) begin : g_withreg
        logic signed [W-1:0] sum_r [N0];
        logic                valid_r;
        logic [TAG_W-1:0]    tag_r;
        always_ff @(posedge clk or negedge rst_n) begin
          if (!rst_n) begin
            valid_r <= 1'b0;
          end else begin
            valid_r <= valid_i;
            if (valid_i) begin
              sum_r <= sum;
              tag_r <= tag_i;
            end
          end
        end
        adder_stage #(.N(N0), .W(W), .REG_EVERY(REG_EVERY), .TAG_W(TAG_W), .LEVEL(0)) u_next (
            .clk     (clk),
            .rst_n   (rst_n),
            .valid_i (valid_r),
            .din_i   (sum_r),
            .tag_i   (tag_r),
            .valid_o (valid_o),
            .dout_o  (dout_o),
            .tag_o   (tag_o)
        );
      end else begin : g_noreg
        adder_stage #(.N(N0), .W(W), .REG_EVERY(REG_EVERY), .TAG_W(TAG_W), .LEVEL(LEVEL+1)) u_next (
            .clk     (clk),
            .rst_n   (rst_n),
            .valid_i (valid_i),
            .din_i   (sum),
            .tag_i   (tag_i),
            .valid_o (valid_o),
            .dout_o  (dout_o),
            .tag_o   (tag_o)
        );
      end
    end
  endgenerate
endmodule
