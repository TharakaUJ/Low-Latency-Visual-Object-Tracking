// gap_fc_argmax.sv
// GlobalAveragePool over the last conv feature map, requantize to uint8,
// then a fully-connected layer + per-class fixed-point rescale + argmax.
//
//   gap_sum[c]   = sum over H*W of feat_u8[c,h,w]
//   gap_avg[c]   = round(gap_sum[c] / (H*W))                      (still in feat scale)
//   gap_u8[c]    = clamp(round(gap_avg[c]*GAP_MULT / 2^31), 0,255)
//   fc_acc[k]    = sum_c gap_u8[c]*fc_weight[k][c] + fc_bias[k]
//   fc_score[k]  = round(fc_acc[k]*fc_mult[k] / 2^31)             (signed, for compare only)
//   class        = argmax_k fc_score[k]

module gap_fc_argmax #(
    parameter int CF   = 32,
    parameter int HF   = 8,
    parameter int WF   = 8,
    parameter int NCLS = 5
) (
    input  logic clk,
    input  logic rst_n,
    input  logic start,
    output logic done,

    // feature-map RAM (from the last conv layer), read-only here
    output logic [$clog2(CF*HF*WF)-1:0] feat_addr,
    input  logic [7:0]                  feat_data,

    input  logic [31:0] gap_mult,                          // Q0.(gap_shift) unsigned mantissa
    input  logic [5:0]  gap_shift,
    input  logic signed [7:0]  fc_weight [0:NCLS-1][0:CF-1],
    input  logic signed [31:0] fc_bias   [0:NCLS-1],
    input  logic [31:0]        fc_mult   [0:NCLS-1],
    input  logic [5:0]         fc_shift  [0:NCLS-1],

    output logic [$clog2(NCLS)-1:0] class_id,
    output logic signed [31:0]      class_scores [0:NCLS-1] // exposed for debug/threshold checks
);

    localparam int NPIX = HF*WF;

    typedef enum logic [2:0] {S_IDLE, S_SUM, S_AVG, S_FC, S_ARGMAX, S_DONE} state_t;
    state_t state;

    int c, p, k;
    logic signed [31:0] gap_sum  [0:CF-1];
    logic signed [31:0] gap_u8i  [0:CF-1]; // requantized GAP output, stored as int (0..255)
    logic signed [63:0] tmp64;
    logic signed [39:0] fc_acc;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            done  <= 1'b0;
            c <= 0; p <= 0; k <= 0;
        end else begin
            unique case (state)

                S_IDLE: begin
                    done <= 1'b0;
                    if (start) begin
                        c <= 0; p <= 0;
                        for (int ii = 0; ii < CF; ii++) gap_sum[ii] <= 0;
                        feat_addr <= '0;
                        state <= S_SUM;
                    end
                end

                // accumulate one channel at a time over all H*W pixels
                S_SUM: begin
                    gap_sum[c] <= gap_sum[c] + $signed({1'b0, feat_data});
                    if (p == NPIX-1) begin
                        p <= 0;
                        if (c == CF-1) begin
                            c <= 0;
                            state <= S_AVG;
                        end else begin
                            c <= c + 1;
                            feat_addr <= (c+1)*NPIX;
                        end
                    end else begin
                        p <= p + 1;
                        feat_addr <= c*NPIX + (p+1);
                    end
                end

                S_AVG: begin
                    // average + requantize each channel, one per cycle
                    tmp64 = (gap_sum[c] + (NPIX/2)) / NPIX;      // rounded average, feat-scale domain
                    tmp64 = tmp64 * $signed({1'b0, gap_mult});
                    tmp64 = (tmp64 + (64'sd1 <<< (gap_shift-1))) >>> gap_shift;
                    gap_u8i[c] <= (tmp64 < 0) ? 32'sd0 : (tmp64 > 255) ? 32'sd255 : tmp64[31:0];
                    if (c == CF-1) begin
                        c <= 0; k <= 0;
                        state <= S_FC;
                    end else begin
                        c <= c + 1;
                    end
                end

                // one MAC per cycle: NCLS*CF cycles total (5*32=160 for this network)
                S_FC: begin
                    if (c == 0) fc_acc <= fc_bias[k];
                    fc_acc <= fc_acc + (gap_u8i[c] * fc_weight[k][c]);
                    if (c == CF-1) begin
                        c <= 0;
                        // one extra cycle latency to let fc_acc settle before requant
                        state <= S_ARGMAX;
                    end else begin
                        c <= c + 1;
                    end
                end

                S_ARGMAX: begin
                    tmp64 = fc_acc * $signed({1'b0, fc_mult[k]});
                    tmp64 = (tmp64 + (64'sd1 <<< (fc_shift[k]-1))) >>> fc_shift[k];
                    class_scores[k] <= tmp64[31:0];
                    if (k == 0 || tmp64 > class_scores[class_id]) class_id <= k[$clog2(NCLS)-1:0];
                    if (k == NCLS-1) begin
                        state <= S_DONE;
                    end else begin
                        k <= k + 1;
                        c <= 0;
                        state <= S_FC;
                    end
                end

                S_DONE: begin
                    done  <= 1'b1;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
