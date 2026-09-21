// Feeds only ONE of the two interlaced fields to the window buffer / matcher.
//
// Why: the two fields of a frame are sampled 1/50 (1/60) s apart and sit half a
// frame-line apart vertically. If both are processed, the target's position
// (and its ZSAD) alternates at field rate -> boundary_x/y jitter, and a
// template cut from one field matches the other one slightly worse.
//
// VS_PER_FIELD = 1 : TD_VS pulses once per FIELD (50/60 Hz). Every second VS
//                    period is dropped. search_start fires only for the kept one,
//                    so the matcher's "lost" counter and best-so-far are untouched
//                    by the dropped field (boundary simply holds).
// VS_PER_FIELD = 0 : TD_VS pulses once per FRAME and the stream is field 0 lines
//                    followed by field 1 lines. Lines >= FIELD_LINES are dropped
//                    (288 PAL / 253 NTSC, must match the second-field start).
// ENABLE = 0       : transparent (old behaviour).
//
// Which of the two fields is kept is whatever happens to follow reset (VS_PER_FIELD=1);
// it is constant afterwards. A template cut from the other field only adds a
// constant half-line offset.
module field_gate #(
    parameter bit ENABLE       = 1'b1,
    parameter bit VS_PER_FIELD = 1'b1,
    parameter int FIELD_LINES  = 288,
    parameter int IMG_W        = 640
)(
    input  logic clk,
    input  logic rst_n,
    input  logic dv_in,
    input  logic frame_done,      // 1-cycle pulse on VS rising edge
    output logic dv_out,          // -> window_buffer.clock_enable
    output logic search_start     // -> template_match.search_start
);
    logic keep;
    logic [$clog2(IMG_W)-1:0] col;
    logic [10:0] line;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            keep <= 1'b1; col <= '0; line <= '0;
        end else if (frame_done) begin
            keep <= ~keep; col <= '0; line <= '0;
        end else if (dv_in) begin
            if (col == IMG_W-1) begin col <= '0; line <= line + 1'b1; end
            else                col <= col + 1'b1;
        end
    end

    always_comb begin
        if (!ENABLE) begin
            dv_out       = dv_in;
            search_start = frame_done;
        end else if (VS_PER_FIELD) begin
            dv_out       = dv_in & keep;
            search_start = frame_done & keep;      // `keep` = field that is ending
        end else begin
            dv_out       = dv_in & (line < FIELD_LINES);
            search_start = frame_done;
        end
    end
endmodule
