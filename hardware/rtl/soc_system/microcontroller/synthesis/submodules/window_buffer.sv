// Replaces stream_buffer.sv.
// Builds a WIN x WIN sliding pixel window out of (WIN-1) BRAM line buffers
// plus a small WIN x WIN register array for the horizontal taps.
// This is the standard FPGA image-processing window-buffer structure and
// scales cleanly from WIN=3 up to WIN=32 (just change the parameter):
// only (WIN-1) BRAM blocks are used, none of the horizontal shifting is
// done across the whole 640-pixel line.
module window_buffer #(
    parameter int WIN    = 3,     // window / template size (WIN x WIN)
    parameter int IMG_W  = 640,   // active pixels per line
    parameter int IMG_H  = 480,   // active lines per frame
    parameter int DATA_W = 8
)(
    input  logic clk,
    input  logic rst_n,
    input  logic clock_enable,                          // = data_valid_in
    input  logic frame_done,                             // = process_top's v_sync-edge pulse; keeps
                                                           // this module's own position counters in
                                                           // lockstep with process_top's pixel_count/
                                                           // line_count, which anchor_x/anchor_y below
                                                           // are expressed in terms of.
    input  logic [DATA_W-1:0] data_in,
    output logic [DATA_W-1:0] window_out [WIN-1:0][WIN-1:0], // [row][col], row0 = newest line
    output logic              window_valid,                  // 1 once the window is fully populated
    output logic [$clog2(IMG_W)-1:0] anchor_x,               // image (x,y) of window_out's TOP-LEFT
    output logic [$clog2(IMG_H)-1:0] anchor_y                // corner (oldest row, oldest col), valid
                                                               // the SAME cycle as window_out/window_valid
);

    localparam int ADDR_W = $clog2(IMG_W);
    localparam int LINE_W = $clog2(IMG_H);

    // ------------------------------------------------------------
    // Column/line address for the line-buffer BRAMs. Previously this
    // was just a free-running col_addr with no line tracking and no
    // frame_done reset, since all it had to do was wrap every IMG_W
    // cycles for BRAM addressing. It now also tracks the current
    // line and resets in lockstep with process_top's pixel_count/
    // line_count (both driven by the same clock_enable/frame_done),
    // so that anchor_x/anchor_y below come out expressed in exactly
    // process_top's own (x,y) coordinate frame.
    // ------------------------------------------------------------
    logic [ADDR_W-1:0] col_addr;
    logic [LINE_W-1:0] line_addr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            col_addr  <= '0;
            line_addr <= '0;
        end else if (frame_done) begin
            col_addr  <= '0;
            line_addr <= '0;
        end else if (clock_enable) begin
            if (col_addr == IMG_W-1) begin
                col_addr <= '0;
                line_addr <= (line_addr == IMG_H-1) ? '0 : line_addr + 1'b1;
            end else begin
                col_addr <= col_addr + 1'b1;
            end
        end
    end

    // ------------------------------------------------------------
    // WIN-1 line buffers (BRAM). row_stream[0] = current line (newest),
    // row_stream[WIN-1] = WIN-1 lines above (oldest).
    // ------------------------------------------------------------
    logic [DATA_W-1:0] row_stream [WIN-1:0];
    assign row_stream[0] = data_in;

    genvar r;
    generate
        for (r = 1; r < WIN; r++) begin : g_line_bufs
            line_buffer #(
                .WIDTH(DATA_W),
                .IMG_W(IMG_W)
            ) u_line_buf (
                .clk   (clk),
                .wr_en (clock_enable),
                .addr  (col_addr),
                .din   (row_stream[r-1]),
                .dout  (row_stream[r])
            );
        end
    endgenerate

    // ------------------------------------------------------------
    // Per-row horizontal shift registers: WIN taps per row.
    // win_reg[row][0] = oldest (leftmost) pixel of that row's window,
    // win_reg[row][WIN-1] = newest (rightmost, = row_stream[row]).
    // This is only WIN registers deep per row, NOT the full 640.
    // ------------------------------------------------------------
    logic [DATA_W-1:0] win_reg [WIN-1:0][WIN-1:0];

    genvar rr;
    generate
        for (rr = 0; rr < WIN; rr++) begin : g_row
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    for (int c = 0; c < WIN; c++)
                        win_reg[rr][c] <= '0;
                end else if (clock_enable) begin
                    for (int c = 0; c < WIN-1; c++)
                        win_reg[rr][c] <= win_reg[rr][c+1];
                    win_reg[rr][WIN-1] <= row_stream[rr];
                end
            end
        end
    endgenerate

    always_comb begin
        for (int rr2 = 0; rr2 < WIN; rr2++)
            for (int cc2 = 0; cc2 < WIN; cc2++)
                window_out[rr2][cc2] = win_reg[rr2][cc2];
    end

    // ------------------------------------------------------------
    // window_valid: the window only contains real image data (not
    // reset zeros / previous-frame garbage) once WIN-1 full lines
    // plus WIN columns of the current line have been streamed in.
    // Re-arms every frame via rst_n from v_sync in process_top, or
    // you can add a frame_start pulse input if you want per-frame
    // re-validation without a full reset.
    // ------------------------------------------------------------
    localparam int unsigned FILL_TARGET = (IMG_W+1)*(WIN-1) + WIN;
    logic [$clog2(FILL_TARGET+1)-1:0] fill_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            fill_count <= '0;
        else if (clock_enable && fill_count < FILL_TARGET)
            fill_count <= fill_count + 1'b1;
    end

    assign window_valid = (fill_count >= FILL_TARGET);

    // ------------------------------------------------------------
    // anchor_x/anchor_y: the image position of window_out's oldest
    // row / oldest column (win_reg[WIN-1][0]), i.e. the window's
    // top-left corner, valid the same cycle as window_out itself.
    //
    // Nominally this position is just (WIN-1) columns left of, and
    // (WIN-1) lines above, the pixel currently being written in
    // (col_addr, line_addr) -- with wraparound at the frame edges.
    // Computed arithmetically here instead of with a physical delay
    // chain, since window_buffer already knows its own col_addr/
    // line_addr and doesn't need to re-derive them by delaying a
    // copy of process_top's pixel_count/line_count by a separate
    // ~(WIN-1)*IMG_W-deep pipeline (which is what process_top was
    // doing before, and which was wrong: it only delayed by WIN
    // cycles, not (WIN-1)*IMG_W -- see tb_process_top's original
    // FINDING for the details of that bug).
    // ------------------------------------------------------------
    logic col_borrow;
    logic [ADDR_W-1:0] anchor_col_raw;
    logic [LINE_W-1:0] line_after_borrow;

    assign col_borrow = (col_addr < (WIN-1));
    assign anchor_col_raw = col_borrow ? (ADDR_W'(IMG_W - (WIN-1)) + col_addr)
                                        : (col_addr - ADDR_W'(WIN-1));
    // Borrowing a column from the previous line also costs one line
    // off the line index before applying the (WIN-1)-line offset.
    assign line_after_borrow = col_borrow ? ((line_addr == '0) ? LINE_W'(IMG_H-1) : line_addr - 1'b1)
                                           : line_addr;

    assign anchor_x = anchor_col_raw;
    assign anchor_y = (line_after_borrow >= (WIN-1)) ? (line_after_borrow - LINE_W'(WIN-1))
                                                       : (LINE_W'(IMG_H - (WIN-1)) + line_after_borrow);

endmodule
