// s3x8_core (P3): S-3x8 tracker core behind the common tracker-FIFO interface (see row_stats.v).
//
// Wraps the E48 generated RTL s3x8_top.v (unchanged: 3 conv layers x 8 channels, int8, integer
// requant, L1 matcher over 49 x 49 candidates, first minimum in raster order) for a 72 x 72 ROI.
//   tag 1 row ctrl        : [13] new_frame, [12:9] frame tag, [8:0] row index   (first word of a row)
//   tag 0 pixel           : [7:0]
//   tag 3 template offset : [13:0]  (first word of a template chunk)
//   tag 2 template byte   : [7:0]
// Template = int8 features 8 x 16 x 16, 2048 bytes, as 16 rows of 128 bytes; byte k*8 + c of row r is
// feature (channel c, row r, column k) - exactly the t_data word layout of s3x8_top (byte b at
// bits 8b+7..8b). It is complete when byte 2047 is written, kept in a shadow RAM and copied into
// s3x8_top (16 t_we writes) at the next new frame.
// E48 needs >= 788 clocks per ROI line: rows are paced to LINE_CLKS clocks (start to start).
// At a new frame: drain (if a frame was cut short), copy a pending template, pulse sof, stream rows.
// When the ROI-th row of a frame arrived in order, wait for done and report best/best_x/best_y.
// res_x/res_y = best candidate (0..48): window top-left at ROI (res_x + 4, res_y + 4) (MARGIN 4).
module s3x8_core #(
    parameter int ROI        = 72,
    parameter int TMPL_BYTES = 2048,
    parameter int LINE_CLKS  = 800,
    parameter int DRAIN_CLKS = 256
)(
    input  logic        clk,
    input  logic        rst,

    input  logic [15:0] s_tdata,
    input  logic        s_tvalid,
    output logic        s_tready,
    input  logic        s_tlast,

    output logic        res_toggle,
    output logic [3:0]  res_ftag,
    output logic [7:0]  res_x,
    output logic [7:0]  res_y,
    output logic [23:0] res_score,
    output logic [15:0] frames_tracked,
    output logic        overrun_seen
);
    localparam int AW = $clog2(TMPL_BYTES);

    // ST_GAP: one stalled clock after sof, so the registered sof pulse reaches s3x8_top before the
    // first pixel (a pixel in the sof clock is lost and every later pixel lands one column early).
    typedef enum logic [2:0] {ST_RUN, ST_DRAIN, ST_COPY, ST_SOF, ST_DONE, ST_GAP} state_t;
    state_t state;

    wire [1:0] tag = s_tdata[15:14];

    // ---------------- E48 core ----------------
    logic          sof, i_valid;
    logic [7:0]    i_pix;
    logic          t_we;
    logic [3:0]    t_addr;
    logic [1023:0] t_data;
    logic [23:0]   best;
    logic [5:0]    best_x, best_y;
    logic          done, overrun;

    s3x8_top u_s3x8 (
        .clk(clk), .rst(rst), .sof(sof), .i_valid(i_valid), .i_pix(i_pix),
        .t_we(t_we), .t_addr(t_addr), .t_data(t_data),
        .best(best), .best_x(best_x), .best_y(best_y), .done(done), .overrun(overrun)
    );

    // ---------------- shadow template ----------------
    logic [7:0]    shadow [0:TMPL_BYTES-1];
    logic [AW-1:0] sh_idx;
    logic          sh_pending;
    logic [AW:0]   cp;                  // copy counter: byte cp-1 is on sh_rd
    logic [7:0]    sh_rd;
    logic [1015:0] word;                // bytes 0..126 of the row being assembled

    // ---------------- frame / line state ----------------
    logic [3:0]  ftag;
    logic [8:0]  rows_cnt;
    logic        inorder, frame_on;
    logic [15:0] line_t;                // clocks since the current row started
    logic [15:0] wait_t;
    logic        new_row_ok;

    // the next row (ctrl word) may start only LINE_CLKS after the previous one
    assign new_row_ok = !frame_on || (line_t >= LINE_CLKS);
    assign s_tready   = (state == ST_RUN) && !(s_tvalid && tag == 2'd1 && !s_tdata[13] && !new_row_ok);

    wire acc = s_tvalid && s_tready;

    always_ff @(posedge clk)
        if (acc && tag == 2'd2) shadow[sh_idx] <= s_tdata[7:0];
    always_ff @(posedge clk)
        sh_rd <= shadow[cp[AW-1:0]];

    assign i_valid = acc && (tag == 2'd0) && frame_on;
    assign i_pix   = s_tdata[7:0];

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= ST_RUN;
            sh_idx <= '0;
            sh_pending <= 1'b0;
            cp <= '0;
            word <= '0;
            t_we <= 1'b0;
            t_addr <= '0;
            t_data <= '0;
            sof <= 1'b0;
            ftag <= '0;
            rows_cnt <= '0;
            inorder <= 1'b0;
            frame_on <= 1'b0;
            line_t <= '0;
            wait_t <= '0;
            res_toggle <= 1'b0;
            res_ftag <= '0;
            res_x <= '0;
            res_y <= '0;
            res_score <= '0;
            frames_tracked <= '0;
            overrun_seen <= 1'b0;
        end else begin
            sof  <= 1'b0;
            t_we <= 1'b0;
            if (line_t != 16'hFFFF) line_t <= line_t + 1'b1;
            if (overrun) overrun_seen <= 1'b1;

            case (state)
            ST_RUN: if (acc) begin
                case (tag)
                2'd3: sh_idx <= s_tdata[AW-1:0];
                2'd2: begin
                    sh_idx <= sh_idx + 1'b1;
                    if (sh_idx == TMPL_BYTES - 1) sh_pending <= 1'b1;
                end
                2'd1: begin
                    if (s_tdata[13]) begin                  // new frame
                        ftag     <= s_tdata[12:9];
                        rows_cnt <= '0;
                        inorder  <= (s_tdata[8:0] == 9'd0);
                        wait_t   <= '0;
                        // always drain first: s3x8_top needs idle clocks between done and the
                        // next sof (a sof right after done shifted that frame by 5 columns)
                        state    <= ST_DRAIN;
                        frame_on <= 1'b0;
                        cp       <= '0;
                    end else begin
                        inorder <= inorder && (s_tdata[8:0] == rows_cnt);
                        line_t  <= '0;
                    end
                end
                2'd0: begin
                    if (s_tlast && frame_on) begin
                        rows_cnt <= rows_cnt + 1'b1;
                        if (inorder && rows_cnt == ROI - 1) state <= ST_DONE;
                    end
                end
                default: ;
                endcase
            end
            ST_DRAIN: begin                                 // let the pipelines empty (frame done or cut short)
                wait_t <= wait_t + 1'b1;
                if (wait_t == DRAIN_CLKS) state <= sh_pending ? ST_COPY : ST_SOF;
            end
            ST_COPY: begin
                cp <= cp + 1'b1;
                if (cp != 0) begin
                    if (((cp - 1) & 127) == 127) begin
                        t_data <= {sh_rd, word};
                        t_addr <= ((cp - 1) >> 7);
                        t_we   <= 1'b1;
                    end else begin
                        word[(((cp - 1) & 127) * 8) +: 8] <= sh_rd;
                    end
                end
                if (cp == TMPL_BYTES) begin
                    sh_pending <= 1'b0;
                    state <= ST_SOF;
                end
            end
            ST_SOF: begin                                   // restart the E48 core for the new frame
                sof <= 1'b1;
                frame_on <= 1'b1;
                line_t <= '0;
                state <= ST_GAP;
            end
            ST_GAP: state <= ST_RUN;
            ST_DONE: begin                                  // all ROI rows in: wait for the last candidates
                if (done) begin
                    res_x <= {2'd0, best_x};
                    res_y <= {2'd0, best_y};
                    res_score <= best;
                    res_ftag <= ftag;
                    res_toggle <= !res_toggle;
                    frames_tracked <= frames_tracked + 1'b1;
                    frame_on <= 1'b0;
                    state <= ST_RUN;
                end
            end
            default: state <= ST_RUN;
            endcase
        end
    end
endmodule
