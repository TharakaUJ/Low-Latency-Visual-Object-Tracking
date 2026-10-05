// zsad_core: tracker-clock side of the P2 Ethernet demo.
//
// Reads the tracker FIFO written by row_stats.v (words {tag[1:0], payload[13:0]}; one FIFO frame
// per ROI row or per template, bad ones already dropped by the FIFO) and runs the user's existing
// window_buffer + template_match (ZSAD, RADIUS = 0: the ROI is the search area) over each frame.
//   tag 1 row ctrl  : [13] new_frame, [12:9] frame tag, [8:0] row index   (first word of a row)
//   tag 0 pixel     : [7:0]
//   tag 2 template  : [7:0], 256 per FIFO frame, row-major
// A new template is kept in a shadow copy and written into template_match at the next new_frame,
// so a frame is never matched against a half-written template. At every new_frame the matcher is
// restarted (search_start + frame_done). When the ROI-th row of a frame ends and all rows came in
// order (0, 1, 2, ...), the pipeline is drained, the result is latched and res_toggle flips.
// res_x/res_y = best window top-left in the ROI, res_score = min ZSAD saturated to 16 bits
// (template_match debug_data[31:16]). Results hold until the next toggle.
module zsad_core #(
    parameter int ROI        = 80,
    parameter int WIN        = 16,
    parameter int REJECT_SAD = 8192,
    parameter int DRAIN      = 16      // clocks from the last pixel to search_start (pipeline is ~6)
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
    output logic [15:0] res_score,
    output logic [15:0] frames_tracked
);
    localparam int IDX_W = $clog2(WIN*WIN);
    localparam int XW    = $clog2(ROI);

    wire rst_n = !rst;

    // ST_GAP: one stalled clock after a new_frame word, so the registered frame_done/search_start
    // pulse reaches window_buffer before the first pixel (frame_done has priority over clock_enable
    // there; a pixel in the same clock would not advance the column counter).
    typedef enum logic [1:0] {ST_RUN, ST_COPY, ST_DRAIN, ST_GAP} state_t;
    state_t state;

    wire [1:0]  tag     = s_tdata[15:14];
    wire        acc     = s_tvalid && s_tready;

    // shadow template
    logic [7:0]       shadow [0:WIN*WIN-1];
    logic [IDX_W-1:0] sh_idx;
    logic             sh_pending;
    logic [IDX_W:0]   cp_idx;

    // frame state
    logic [3:0]  ftag;
    logic [8:0]  rows_cnt;
    logic        inorder;
    logic [5:0]  drain_cnt;

    // matcher control
    logic        frame_done_p, search_start_p;
    logic        tmpl_wr_pulse;
    logic [IDX_W-1:0] tmpl_wr_index;
    logic [7:0]  tmpl_wr_data;

    wire pix_en = acc && (tag == 2'd0) && (state == ST_RUN);

    assign s_tready = (state == ST_RUN);

    // ---------------- matcher ----------------
    logic [7:0] window [WIN-1:0][WIN-1:0];
    logic       window_valid;
    logic [XW-1:0] anchor_x, anchor_y;
    logic [9:0] tb_x, tb_y;
    logic [31:0] dbg;

    window_buffer #(.WIN(WIN), .IMG_W(ROI), .IMG_H(ROI)) u_win (
        .clk(clk), .rst_n(rst_n),
        .clock_enable(pix_en), .frame_done(frame_done_p),
        .data_in(s_tdata[7:0]),
        .window_out(window), .window_valid(window_valid),
        .anchor_x(anchor_x), .anchor_y(anchor_y)
    );

    template_match #(.WIN(WIN), .IMG_W(ROI), .IMG_H(ROI), .RADIUS(0),
                     .REJECT_SAD(REJECT_SAD)) u_match (
        .clk(clk), .rst_n(rst_n),
        .search_start(search_start_p), .window_valid(window_valid),
        .data_in(window), .current_x(anchor_x), .current_y(anchor_y),
        .temp_boundary_x(tb_x), .temp_boundary_y(tb_y), .debug_data(dbg),
        .tmpl_wr_pulse(tmpl_wr_pulse), .tmpl_wr_index(tmpl_wr_index), .tmpl_wr_data(tmpl_wr_data)
    );

    // shadow template write port (separate block so it can map to RAM)
    always_ff @(posedge clk)
        if (acc && tag == 2'd2) shadow[sh_idx] <= s_tdata[7:0];

    // template copy read (registered read, one write per clock into template_match)
    logic [7:0] sh_rd;
    always_ff @(posedge clk) sh_rd <= shadow[cp_idx[IDX_W-1:0]];

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state          <= ST_RUN;
            sh_idx         <= '0;
            sh_pending     <= 1'b0;
            cp_idx         <= '0;
            ftag           <= '0;
            rows_cnt       <= '0;
            inorder        <= 1'b0;
            drain_cnt      <= '0;
            frame_done_p   <= 1'b0;
            search_start_p <= 1'b0;
            tmpl_wr_pulse  <= 1'b0;
            tmpl_wr_index  <= '0;
            tmpl_wr_data   <= '0;
            res_toggle     <= 1'b0;
            res_ftag       <= '0;
            res_x          <= '0;
            res_y          <= '0;
            res_score      <= '0;
            frames_tracked <= '0;
        end else begin
            frame_done_p   <= 1'b0;
            search_start_p <= 1'b0;
            tmpl_wr_pulse  <= 1'b0;

            case (state)
            ST_RUN: if (acc) begin
                case (tag)
                2'd2: begin                                     // template byte -> shadow
                    sh_idx <= s_tlast ? '0 : sh_idx + 1'b1;
                    if (s_tlast) sh_pending <= 1'b1;
                end
                2'd1: begin                                     // row ctrl
                    if (s_tdata[13]) begin                      // new frame: restart the matcher
                        frame_done_p   <= 1'b1;
                        search_start_p <= 1'b1;
                        ftag           <= s_tdata[12:9];
                        rows_cnt       <= '0;
                        inorder        <= (s_tdata[8:0] == 9'd0);
                        if (sh_pending) begin
                            sh_pending <= 1'b0;
                            cp_idx     <= '0;
                            state      <= ST_COPY;
                        end else begin
                            state      <= ST_GAP;
                        end
                    end else begin
                        inorder <= inorder && (s_tdata[8:0] == rows_cnt);
                    end
                end
                2'd0: begin                                     // pixel
                    if (s_tlast) begin                          // end of a row
                        rows_cnt <= rows_cnt + 1'b1;
                        if (inorder && rows_cnt == ROI - 1) begin
                            drain_cnt <= '0;
                            state     <= ST_DRAIN;
                        end
                    end
                end
                default: ;
                endcase
            end
            ST_COPY: begin
                // cp_idx runs one ahead of the write (registered shadow read)
                cp_idx <= cp_idx + 1'b1;
                if (cp_idx != 0) begin
                    tmpl_wr_pulse <= 1'b1;
                    tmpl_wr_index <= cp_idx[IDX_W-1:0] - 1'b1;
                    tmpl_wr_data  <= sh_rd;
                end
                if (cp_idx == WIN*WIN) state <= ST_RUN;
            end
            ST_GAP: state <= ST_RUN;
            ST_DRAIN: begin
                drain_cnt <= drain_cnt + 1'b1;
                if (drain_cnt == DRAIN) begin
                    // template_match outputs are valid up to (and in) the search_start cycle
                    search_start_p <= 1'b1;
                    frame_done_p   <= 1'b1;
                    res_x          <= tb_x[7:0];
                    res_y          <= tb_y[7:0];
                    res_score      <= dbg[31:16];
                    res_ftag       <= ftag;
                    res_toggle     <= !res_toggle;
                    frames_tracked <= frames_tracked + 1'b1;
                    inorder        <= 1'b0;
                    state          <= ST_RUN;
                end
            end
            default: state <= ST_RUN;
            endcase
        end
    end
endmodule
