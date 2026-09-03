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
    parameter int DATA_W = 8
)(
    input  logic clk,
    input  logic rst_n,
    input  logic clock_enable,                          // = data_valid_in
    input  logic [DATA_W-1:0] data_in,
    output logic [DATA_W-1:0] window_out [WIN-1:0][WIN-1:0], // [row][col], row0 = newest line
    output logic              window_valid                   // 1 once the window is fully populated
);

    localparam int ADDR_W = $clog2(IMG_W);

    // ------------------------------------------------------------
    // Column address for the line-buffer BRAMs. This is the buffer's
    // own local counter; it does NOT need to match process_top's
    // pixel_count value-for-value, it just needs to wrap every IMG_W
    // enabled cycles, which it does the same way pixel_count does.
    // ------------------------------------------------------------
    logic [ADDR_W-1:0] col_addr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            col_addr <= '0;
        else if (clock_enable)
            col_addr <= (col_addr == IMG_W-1) ? '0 : col_addr + 1'b1;
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
    localparam int unsigned FILL_TARGET = IMG_W*(WIN-1) + WIN;
    logic [$clog2(FILL_TARGET+1)-1:0] fill_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            fill_count <= '0;
        else if (clock_enable && fill_count < FILL_TARGET)
            fill_count <= fill_count + 1'b1;
    end

    assign window_valid = (fill_count >= FILL_TARGET);

endmodule
