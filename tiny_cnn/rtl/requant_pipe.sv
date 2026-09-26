// requant_pipe.sv -- TFLite-style per-channel requantization + implicit ReLU
// via uint8 clamp, registered in 4 stages so no single cycle carries a wide
// multiply straight into a wide shift/add (the timing failure that sank the
// old fpga_cnn_pipeline design, docs/review_findings.md B19).
//
// out_u8 = clamp( round_half_up( (acc * M0) >> shift ) + out_zp , 0, 255 )
//
// M0/shift come from quantize_multiplier() (fpga_cnn_pipeline/onnx_to_rtl.py):
// real_multiplier == M0 * 2^-shift EXACTLY, no extra 2^-31 factor (see that
// finding's B1). M0 is always in [2^30, 2^31), fits in an unsigned/positive
// 32-bit signed value.
//
// A tag (opaque to this module) rides alongside the pipeline so the caller
// can identify which output channel / tile this result belongs to.
module requant_pipe #(
    parameter int ACC_W = 32,
    parameter int TAG_W = 16
) (
    input  logic                     clk,
    input  logic                     rst_n,
    input  logic                     valid_i,
    input  logic signed [ACC_W-1:0]  acc_i,
    input  logic signed [31:0]       mult_i,   // M0, Q(shift) fixed point
    input  logic [5:0]               shift_i,
    input  logic signed [15:0]       out_zp_i,
    input  logic [TAG_W-1:0]         tag_i,
    output logic                     valid_o,
    output logic [7:0]               out_u8_o,
    output logic [TAG_W-1:0]         tag_o
);
  // stage 1: register operands
  logic signed [ACC_W-1:0] acc_q1;
  logic signed [31:0]      mult_q1;
  logic [5:0]              shift_q1;
  logic signed [15:0]      zp_q1;
  logic [TAG_W-1:0]        tag_q1;
  logic                    v_q1;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) v_q1 <= 1'b0;
    else begin
      v_q1 <= valid_i;
      if (valid_i) begin
        acc_q1   <= acc_i;
        mult_q1  <= mult_i;
        shift_q1 <= shift_i;
        zp_q1    <= out_zp_i;
        tag_q1   <= tag_i;
      end
    end
  end

  // stage 2: the multiply itself (one pipelined DSP-style multiply)
  logic signed [ACC_W+32-1:0] prod_q2;
  logic [5:0]                 shift_q2;
  logic signed [15:0]         zp_q2;
  logic [TAG_W-1:0]           tag_q2;
  logic                       v_q2;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) v_q2 <= 1'b0;
    else begin
      v_q2 <= v_q1;
      if (v_q1) begin
        prod_q2  <= acc_q1 * mult_q1;
        shift_q2 <= shift_q1;
        zp_q2    <= zp_q1;
        tag_q2   <= tag_q1;
      end
    end
  end

  // stage 3: add the round-half-up constant
  logic signed [ACC_W+32-1:0] rounded_q3;
  logic [5:0]                 shift_q3;
  logic signed [15:0]         zp_q3;
  logic [TAG_W-1:0]           tag_q3;
  logic                       v_q3;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) v_q3 <= 1'b0;
    else begin
      v_q3 <= v_q2;
      if (v_q2) begin
        rounded_q3 <= prod_q2 + ({{(ACC_W+31){1'b0}}, 1'b1} <<< (shift_q2 - 1));
        shift_q3   <= shift_q2;
        zp_q3      <= zp_q2;
        tag_q3     <= tag_q2;
      end
    end
  end

  // stage 4: shift, add zero point, clamp to uint8
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      valid_o  <= 1'b0;
      out_u8_o <= 8'd0;
    end else begin
      valid_o <= v_q3;
      if (v_q3) begin
        automatic logic signed [ACC_W+32-1:0] shifted;
        automatic logic signed [ACC_W+32-1:0] final_val;
        shifted   = rounded_q3 >>> shift_q3;
        // $signed(...) required: a part-select of a signed vector is always
        // unsigned in Verilog regardless of the vector's own signedness --
        // without the cast this addition silently zero-extends zp_q3
        // instead of sign-extending it (see fpga_cnn_pipeline's B12).
        final_val = $signed(shifted[31:0]) + zp_q3;
        if (final_val < 0)          out_u8_o <= 8'd0;
        else if (final_val > 255)   out_u8_o <= 8'd255;
        else                        out_u8_o <= final_val[7:0];
        tag_o <= tag_q3;
      end
    end
  end
endmodule
