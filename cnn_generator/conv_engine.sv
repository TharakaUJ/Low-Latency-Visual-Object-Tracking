// conv_engine.sv
// Generic sequential 3x3 conv (pad=1) + bias + fixed-point requant + ReLU-clamp engine.
// Reused for every conv layer of the network; the per-layer weight/bias/mult ROM
// arrays live in tinycnn_pkg.sv and are wired in from tinycnn_top.sv.
//
// Fixed-point requant scheme (matches the Python reference model):
//   acc      = sum(in_u8 * w_i8) + bias_i32                       (int32-range accumulator)
//   requant  = (acc * mult + (1<<(shift-1))) >>> shift             (mult: Q0.(shift) unsigned mantissa,
//                                                                    per-channel mult/shift pair --
//                                                                    see q31_mult_shift() in the generator)
//   out_u8   = CLAMP ? clamp(requant, 0, 255) : requant            (clamp folds in the ReLU)
//
// Activation memories are simple external byte-wide RAMs (one read port in,
// one write port out) so the same engine can chain layer-to-layer via
// ping-pong buffers in tinycnn_top.sv.

module conv_engine #(
    parameter int CIN    = 4,
    parameter int COUT   = 4,
    parameter int HIN    = 64,
    parameter int WIN    = 64,
    parameter int STRIDE = 1,
    parameter bit CLAMP  = 1'b1,                       // 1 = fold ReLU + clamp to [0,255]
    parameter int HOUT   = (HIN + 2 - 3) / STRIDE + 1,
    parameter int WOUT   = (WIN + 2 - 3) / STRIDE + 1,
    parameter int IN_AW  = (CIN*HIN*WIN <= 1) ? 1 : $clog2(CIN*HIN*WIN),
    parameter int OUT_AW = (COUT*HOUT*WOUT <= 1) ? 1 : $clog2(COUT*HOUT*WOUT)
) (
    input  logic clk,
    input  logic rst_n,
    input  logic start,
    output logic done,

    // input activation RAM (read-only here)
    output logic [IN_AW-1:0]  in_addr,
    input  logic [7:0]        in_data,

    // output activation RAM (write-only here)
    output logic [OUT_AW-1:0] out_addr,
    output logic [7:0]        out_data,
    output logic              out_we,

    // per-layer constants, wired from tinycnn_pkg.sv at instantiation time
    input  logic signed [7:0]  weight [0:COUT-1][0:CIN-1][0:2][0:2],
    input  logic signed [31:0] bias   [0:COUT-1],
    input  logic [31:0]        mult   [0:COUT-1],
    input  logic [5:0]         shift  [0:COUT-1]
);

    typedef enum logic [2:0] {S_IDLE, S_FETCH, S_MAC, S_REQUANT, S_WRITE, S_NEXT, S_DONE} state_t;
    state_t state;

    // loop counters
    int co, oh, ow, ci, kh, kw;
    int ih, iw;
    logic signed [39:0] acc;      // room for CIN*3*3*255*127 accumulation, generous margin
    logic signed [63:0] prod;

    function automatic logic in_bounds(input int r, input int c);
        return (r >= 0) && (r < HIN) && (c >= 0) && (c < WIN);
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            done  <= 1'b0;
            co <= 0; oh <= 0; ow <= 0; ci <= 0; kh <= 0; kw <= 0;
            acc <= '0;
            out_we <= 1'b0;
        end else begin
            out_we <= 1'b0;
            unique case (state)

                S_IDLE: begin
                    done <= 1'b0;
                    if (start) begin
                        co <= 0; oh <= 0; ow <= 0; ci <= 0; kh <= 0; kw <= 0;
                        acc <= bias[0];
                        state <= S_FETCH;
                    end
                end

                // issue read address for (ci, ih, iw); result observed next cycle in S_MAC
                S_FETCH: begin
                    ih = oh*STRIDE - 1 + kh;
                    iw = ow*STRIDE - 1 + kw;
                    in_addr <= (ci*HIN*WIN) + (ih*WIN) + iw; // only valid if in_bounds
                    state <= S_MAC;
                end

                S_MAC: begin
                    ih = oh*STRIDE - 1 + kh;
                    iw = ow*STRIDE - 1 + kw;
                    if (in_bounds(ih, iw))
                        acc <= acc + ($signed({1'b0, in_data}) * weight[co][ci][kh][kw]);
                    // advance (ci,kh,kw) triple nested loop
                    if (kw == 2) begin
                        kw <= 0;
                        if (kh == 2) begin
                            kh <= 0;
                            if (ci == CIN-1) begin
                                ci <= 0;
                                state <= S_REQUANT;
                            end else begin
                                ci <= ci + 1;
                                state <= S_FETCH;
                            end
                        end else begin
                            kh <= kh + 1;
                            state <= S_FETCH;
                        end
                    end else begin
                        kw <= kw + 1;
                        state <= S_FETCH;
                    end
                end

                S_REQUANT: begin
                    prod = acc * $signed({1'b0, mult[co]});
                    prod = (prod + (64'sd1 <<< (shift[co]-1))) >>> shift[co];
                    state <= S_WRITE;
                end

                S_WRITE: begin
                    out_addr <= (co*HOUT*WOUT) + (oh*WOUT) + ow;
                    if (CLAMP) begin
                        if (prod < 0)        out_data <= 8'd0;
                        else if (prod > 255) out_data <= 8'd255;
                        else                 out_data <= prod[7:0];
                    end else begin
                        out_data <= prod[7:0]; // unused when CLAMP=0 (see gap_fc_argmax for signed path)
                    end
                    out_we <= 1'b1;
                    state  <= S_NEXT;
                end

                S_NEXT: begin
                    if (ow == WOUT-1) begin
                        ow <= 0;
                        if (oh == HOUT-1) begin
                            oh <= 0;
                            if (co == COUT-1) begin
                                state <= S_DONE;
                            end else begin
                                co  <= co + 1;
                                acc <= bias[co+1];
                                state <= S_FETCH;
                            end
                        end else begin
                            oh  <= oh + 1;
                            acc <= bias[co];
                            state <= S_FETCH;
                        end
                    end else begin
                        ow  <= ow + 1;
                        acc <= bias[co];
                        state <= S_FETCH;
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
