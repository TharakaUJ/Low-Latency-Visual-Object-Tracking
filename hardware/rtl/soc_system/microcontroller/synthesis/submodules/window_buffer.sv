// WIN x WIN sliding window built from (WIN-1) BRAM line buffers.
//
// Changes vs. the previous version (all of them affected boundary_x/y):
//  1. window_out[0] is now the OLDEST (top) line, window_out[WIN-1] the newest,
//     so the window has the same orientation as the image and as a template
//     cut from it (row 0 = top, col 0 = left). Before, rows were bottom-up,
//     i.e. the template was being matched vertically flipped.
//  2. window_valid is a ONE-CYCLE STROBE that fires only for windows that lie
//     completely inside the current frame: column >= WIN-1 (no line wrap-around,
//     the old version also "matched" windows made of the end of one line glued to
//     the start of the next) and line >= WIN-1 (no rows left over from the
//     previous frame; fill_count was never re-armed per frame).
//  3. anchor_x/anchor_y are exact top-left coordinates (old anchor_x was
//     +1 too large because it was derived from the already-incremented column).
//  4. Line buffer read address runs one sample ahead -> no dependency on
//     TV_DVAL having idle clocks between samples.
module window_buffer #(
    parameter int WIN    = 3,
    parameter int IMG_W  = 640,
    parameter int IMG_H  = 480,
    parameter int DATA_W = 8
)(
    input  logic clk,
    input  logic rst_n,
    input  logic clock_enable,      // = data_valid_in
    input  logic frame_done,        // v_sync rising-edge pulse
    input  logic [DATA_W-1:0] data_in,
    output logic [DATA_W-1:0] window_out [WIN-1:0][WIN-1:0], // [row][col], row0 = top/oldest
    output logic              window_valid,   // 1-cycle strobe: window_out/anchor hold a NEW full window
    output logic [$clog2(IMG_W)-1:0] anchor_x, // top-left of window_out, valid with window_valid
    output logic [$clog2(IMG_H)-1:0] anchor_y
);
    localparam int ADDR_W = $clog2(IMG_W);
    localparam int LINE_W = $clog2(IMG_H);

    logic [ADDR_W-1:0] col_addr;    // column of the sample currently on data_in
    logic [LINE_W-1:0] line_addr;
    logic [ADDR_W-1:0] col_next;    // column of the NEXT sample = line-buffer read address

    always_comb begin
        if (frame_done)         col_next = '0;
        else if (clock_enable)  col_next = (col_addr == ADDR_W'(IMG_W-1)) ? '0 : col_addr + 1'b1;
        else                    col_next = col_addr;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            col_addr  <= '0;
            line_addr <= '0;
        end else if (frame_done) begin
            col_addr  <= '0;
            line_addr <= '0;
        end else if (clock_enable) begin
            col_addr <= col_next;
            if (col_addr == ADDR_W'(IMG_W-1))
                line_addr <= (line_addr == LINE_W'(IMG_H-1)) ? '0 : line_addr + 1'b1;
        end
    end

    // row_stream[0] = current line, row_stream[r] = r lines above
    logic [DATA_W-1:0] row_stream [WIN-1:0];
    assign row_stream[0] = data_in;

    genvar r;
    generate
        for (r = 1; r < WIN; r++) begin : g_line_bufs
            line_buffer #(.WIDTH(DATA_W), .IMG_W(IMG_W)) u_line_buf (
                .clk    (clk),
                .wr_en  (clock_enable),
                .wr_addr(col_addr),
                .rd_addr(col_next),
                .din    (row_stream[r-1]),
                .dout   (row_stream[r])
            );
        end
    endgenerate

    // horizontal taps: win_reg[row][0] = oldest/left, [WIN-1] = newest/right
    logic [DATA_W-1:0] win_reg [WIN-1:0][WIN-1:0];
    genvar rr;
    generate
        for (rr = 0; rr < WIN; rr++) begin : g_row
            always_ff @(posedge clk) begin
                if (clock_enable) begin
                    for (int c = 0; c < WIN-1; c++)
                        win_reg[rr][c] <= win_reg[rr][c+1];
                    win_reg[rr][WIN-1] <= row_stream[rr];
                end
            end
        end
    endgenerate

    // flip vertically: window_out[0] = oldest (top) line
    always_comb begin
        for (int a = 0; a < WIN; a++)
            for (int b = 0; b < WIN; b++)
                window_out[a][b] = win_reg[WIN-1-a][b];
    end

    // strobe + exact top-left, registered so they line up with the win_reg update
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            window_valid <= 1'b0;
            anchor_x     <= '0;
            anchor_y     <= '0;
        end else begin
            window_valid <= clock_enable && !frame_done &&
                            (col_addr  >= ADDR_W'(WIN-1)) &&
                            (line_addr >= LINE_W'(WIN-1));
            anchor_x     <= col_addr  - ADDR_W'(WIN-1);
            anchor_y     <= line_addr - LINE_W'(WIN-1);
        end
    end
endmodule
