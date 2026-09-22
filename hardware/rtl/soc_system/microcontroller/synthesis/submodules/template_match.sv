// Streaming template matcher: zero-mean SAD (ZSAD) + local search + rejection.
//
// For every complete window (1-cycle strobe `window_valid` from window_buffer):
//     d_i   = w_i - t_i
//     delta = (sum(w) - sum(t)) / N            (difference of the two means)
//     ZSAD  = sum_i | d_i - delta |            = SAD with both means removed
// so a global brightness offset (auto-gain, lighting change, shadow) no longer
// moves the minimum, and flat/blank windows are penalised by the template's own
// texture instead of scoring "medium" against everything like plain SAD does.
//
// Pipeline (all regs, one window per clock max, throughput independent of DVAL):
//   S0  d = w - t, per-row sum of w
//   S1  sumW -> delta, copy of d
//   S2  per-row sum of |d - delta|
//   S3  ZSAD = sum of the row sums
//   S4  compare / keep best
//
// Robustness features:
//   * RADIUS > 0 : once a good match exists, only positions within +-RADIUS
//                  (top-left coords) of the last good one compete. Stops the
//                  result jumping to a look-alike elsewhere in the picture.
//   * REJECT_SAD : if the frame's best ZSAD is above this, the match is treated
//                  as "not found" and the previous position is held.
//   * LOST_MAX   : after that many consecutive rejected frames the local-search
//                  restriction is dropped and the whole frame is searched again.
//
// temp_boundary_x/y = top-left corner of the best window, in the same
// (sample, line-since-VS) coordinates as window_buffer.anchor_x/y. They are
// valid combinationally right up to the cycle `search_start` fires.
module template_match #(
    parameter int WIN        = 16,
    parameter int IMG_W      = 640,
    parameter int IMG_H      = 480,
    parameter int IDX_WIDTH  = $clog2(WIN*WIN),
    parameter int RADIUS     = 64,     // 0 = always search the full frame
    parameter int LOST_MAX   = 8,
    parameter int REJECT_SAD = 8192    // ~32 grey levels mean |error| for a 16x16 window
)(
    input  logic clk,
    input  logic rst_n,
    input  logic search_start,        // frame boundary: latch result, restart search
    input  logic window_valid,        // 1-cycle strobe, window is new & fully inside frame
    input  logic [7:0] data_in [WIN-1:0][WIN-1:0],   // [row][col], row0 = top
    input  logic [$clog2(IMG_W)-1:0] current_x,      // top-left of data_in
    input  logic [$clog2(IMG_H)-1:0] current_y,
    output logic [9:0] temp_boundary_x,
    output logic [9:0] temp_boundary_y,
    output logic [31:0] debug_data,

    input  logic                  tmpl_wr_pulse,
    input  logic [IDX_WIDTH-1:0]  tmpl_wr_index,     // row*WIN + col
    input  logic [7:0]            tmpl_wr_data
);
    localparam int N     = WIN*WIN;
    localparam int SH    = $clog2(N);                 // N must be a power of two
    localparam int RS_W  = $clog2(WIN*255 + 1);       // per-row sum of pixels
    localparam int SUM_W = $clog2(N*255 + 1);         // whole-window sum
    localparam int RA_W  = $clog2(WIN*510 + 1);       // per-row sum of |e|
    localparam int SAD_W = $clog2(N*510 + 1);         // ZSAD
    localparam int XW    = $clog2(IMG_W);
    localparam int YW    = $clog2(IMG_H);

    // ------------------------------------------------------------------
    // template register file (host-writable through the CDC in process_top)
    // ------------------------------------------------------------------
    logic [7:0] tmpl [WIN-1:0][WIN-1:0];
    wire [$clog2(WIN)-1:0] tmpl_wr_row = tmpl_wr_index / WIN;
    wire [$clog2(WIN)-1:0] tmpl_wr_col = tmpl_wr_index % WIN;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int r = 0; r < WIN; r++)
                for (int c = 0; c < WIN; c++)
                    tmpl[r][c] <= 8'hFF;
        end else if (tmpl_wr_pulse) begin
            tmpl[tmpl_wr_row][tmpl_wr_col] <= tmpl_wr_data;
        end
    end

    // sum of template, re-registered every clock (changes only when host writes)
    logic [SUM_W-1:0] sumT_c, sumT;
    always_comb begin
        sumT_c = '0;
        for (int r = 0; r < WIN; r++)
            for (int c = 0; c < WIN; c++)
                sumT_c = sumT_c + SUM_W'(tmpl[r][c]);
    end
    always_ff @(posedge clk) sumT <= sumT_c;

    // ------------------------------------------------------------------
    // S0: d = w - t ; row sums of w
    // ------------------------------------------------------------------
    logic signed [8:0]   d0 [WIN-1:0][WIN-1:0];
    logic        [RS_W-1:0] rs0 [WIN-1:0];
    logic        [RS_W-1:0] rs_c [WIN-1:0];
    logic v0;
    logic [XW-1:0] x0;
    logic [YW-1:0] y0;

    always_comb begin
        for (int r = 0; r < WIN; r++) begin
            rs_c[r] = '0;
            for (int c = 0; c < WIN; c++)
                rs_c[r] = rs_c[r] + RS_W'(data_in[r][c]);
        end
    end

    always_ff @(posedge clk) begin
        for (int r = 0; r < WIN; r++) begin
            rs0[r] <= rs_c[r];
            for (int c = 0; c < WIN; c++)
                d0[r][c] <= $signed({1'b0, data_in[r][c]}) - $signed({1'b0, tmpl[r][c]});
        end
        x0 <= current_x;
        y0 <= current_y;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)            v0 <= 1'b0;
        else if (search_start) v0 <= 1'b0;
        else                   v0 <= window_valid;
    end

    // ------------------------------------------------------------------
    // S1: delta = round((sumW - sumT) / N)
    // ------------------------------------------------------------------
    logic [SUM_W-1:0] sumW_c;
    always_comb begin
        sumW_c = '0;
        for (int r = 0; r < WIN; r++) sumW_c = sumW_c + SUM_W'(rs0[r]);
    end

    localparam logic signed [SUM_W:0] HALF = N/2;
    logic signed [SUM_W:0] diff_c, biased_c, shifted_c;
    assign diff_c    = $signed({1'b0, sumW_c}) - $signed({1'b0, sumT});
    assign biased_c  = diff_c + HALF;
    assign shifted_c = biased_c >>> SH;

    logic signed [8:0]  d1 [WIN-1:0][WIN-1:0];
    logic signed [9:0]  delta1;
    logic v1;
    logic [XW-1:0] x1;
    logic [YW-1:0] y1;

    always_ff @(posedge clk) begin
        d1     <= d0;
        delta1 <= shifted_c[9:0];
        x1     <= x0;
        y1     <= y0;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)            v1 <= 1'b0;
        else if (search_start) v1 <= 1'b0;
        else                   v1 <= v0;
    end

    // ------------------------------------------------------------------
    // S2: per-row sum of |d - delta| ; local-search gate
    // ------------------------------------------------------------------
    logic [XW-1:0] last_x;
    logic [YW-1:0] last_y;
    logic          have_last;
    logic [7:0]    lost_cnt;
    wire restrict_search = (RADIUS > 0) && have_last && (lost_cnt < LOST_MAX);

    function automatic logic [XW-1:0] adx(input logic [XW-1:0] a, input logic [XW-1:0] b);
        return (a > b) ? (a - b) : (b - a);
    endfunction
    function automatic logic [YW-1:0] ady(input logic [YW-1:0] a, input logic [YW-1:0] b);
        return (a > b) ? (a - b) : (b - a);
    endfunction

    logic [RA_W-1:0] ra_c [WIN-1:0];
    logic signed [10:0] e;
    logic [9:0]  mag;
    always_comb begin
        for (int r = 0; r < WIN; r++) begin
            ra_c[r] = '0;
            for (int c = 0; c < WIN; c++) begin
                e   = $signed(d1[r][c]) - $signed(delta1);
                mag = e[10] ? (~e[9:0] + 10'd1) : e[9:0];
                ra_c[r] = ra_c[r] + RA_W'(mag);
            end
        end
    end

    logic [RA_W-1:0] ra2 [WIN-1:0];
    logic v2, in_range2;
    logic [XW-1:0] x2;
    logic [YW-1:0] y2;

    always_ff @(posedge clk) begin
        ra2 <= ra_c;
        x2  <= x1;
        y2  <= y1;
        in_range2 <= !restrict_search ||
                     ((int'(adx(x1, last_x)) <= RADIUS) && (int'(ady(y1, last_y)) <= RADIUS));
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)            v2 <= 1'b0;
        else if (search_start) v2 <= 1'b0;
        else                   v2 <= v1;
    end

    // ------------------------------------------------------------------
    // S3: ZSAD
    // ------------------------------------------------------------------
    logic [SAD_W-1:0] zsad_c, zsad3;
    always_comb begin
        zsad_c = '0;
        for (int r = 0; r < WIN; r++) zsad_c = zsad_c + SAD_W'(ra2[r]);
    end

    logic v3, in_range3;
    logic [XW-1:0] x3;
    logic [YW-1:0] y3;
    always_ff @(posedge clk) begin
        zsad3     <= zsad_c;
        x3        <= x2;
        y3        <= y2;
        in_range3 <= in_range2;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)            v3 <= 1'b0;
        else if (search_start) v3 <= 1'b0;
        else                   v3 <= v2;
    end

    // ------------------------------------------------------------------
    // S4: best-so-far, frame result, hold/lost logic
    // ------------------------------------------------------------------
    logic [SAD_W-1:0] min_sad;
    logic [XW-1:0]    best_x;
    logic [YW-1:0]    best_y;

    wire good = (min_sad <= SAD_W'(REJECT_SAD));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            min_sad   <= '1;
            best_x    <= '0;
            best_y    <= '0;
            last_x    <= '0;
            last_y    <= '0;
            have_last <= 1'b0;
            lost_cnt  <= 8'd0;
        end else if (search_start) begin
            if (good) begin
                last_x    <= best_x;
                last_y    <= best_y;
                have_last <= 1'b1;
                lost_cnt  <= 8'd0;
            end else if (lost_cnt != 8'hFF) begin
                lost_cnt  <= lost_cnt + 8'd1;
            end
            min_sad <= '1;
        end else if (v3 && in_range3 && (zsad3 < min_sad)) begin
            min_sad <= zsad3;
            best_x  <= x3;
            best_y  <= y3;
        end
    end

    // result for the frame that is ending; hold last good position if nothing matched
    assign temp_boundary_x = good      ? 10'(best_x) :
                             have_last ? 10'(last_x) : 10'd0;
    assign temp_boundary_y = good      ? 10'(best_y) :
                             have_last ? 10'(last_y) : 10'd0;

    // debug: {best ZSAD of current frame so far, latest ZSAD}, each saturated to 16 bits
    wire [15:0] dbg_min = (|min_sad[SAD_W-1:16]) ? 16'hFFFF : min_sad[15:0];
    wire [15:0] dbg_cur = (|zsad3[SAD_W-1:16])   ? 16'hFFFF : zsad3[15:0];
    assign debug_data = {dbg_min, dbg_cur};
endmodule
