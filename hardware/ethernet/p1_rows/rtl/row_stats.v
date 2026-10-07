/*
 * row_stats: P1 Ethernet loopback for the DE2-115 tracking demo.
 *
 * Downlink (UDP to PORT), one packet per image row, little-endian:
 *   magic u16 = 0x5AA5, frame_id u32, row u16, width u16, height u16, then width pixels (u8)
 * Uplink (UDP back to the sender of the rows), one 40-byte packet per frame, little-endian:
 *   0 magic u16 = 0x3CC3   2 flags u16 (bit0 complete, bit1 closed by a newer frame_id)
 *   4 frame_id u32         8 rows_seen u16   10 rows_bad u16   12 height u16   14 width u16
 *  16 pix_checksum u32 (sum of the pixels of good rows, mod 2^32)
 *  20 t_rx_start u32 (first row header)   24 t_rx_end u32 (last good row end)
 *  28 t_result u32 (result generated)      all times: free-running 125 MHz cycle counter
 *  32 x i16, 34 y i16, 36 score u32 (tracker output; zero in P1)
 *
 * A frame closes when rows_seen == height (complete) or when a good row of another
 * frame_id arrives (incomplete; then flag bit1). A row is bad when the magic, the
 * UDP length, the MAC/IP error flag (tuser) or row < height do not check out.
 * Duplicate rows are not detected (no row bitmap).
 */

`resetall
`timescale 1ns / 1ps
`default_nettype none

module row_stats #
(
    parameter [15:0] PORT = 16'd1234
)
(
    input  wire        clk,
    input  wire        rst,

    // UDP RX (from udp_complete m_udp_*)
    input  wire        rx_hdr_valid,
    output wire        rx_hdr_ready,
    input  wire [31:0] rx_ip_source_ip,
    input  wire [15:0] rx_source_port,
    input  wire [15:0] rx_dest_port,
    input  wire [15:0] rx_length,
    input  wire [7:0]  rx_tdata,
    input  wire        rx_tvalid,
    output wire        rx_tready,
    input  wire        rx_tlast,
    input  wire        rx_tuser,

    // UDP TX (to udp_complete s_udp_*)
    output wire        tx_hdr_valid,
    input  wire        tx_hdr_ready,
    output wire [31:0] tx_ip_dest_ip,
    output wire [15:0] tx_source_port,
    output wire [15:0] tx_dest_port,
    output wire [15:0] tx_length,
    output wire [7:0]  tx_tdata,
    output wire        tx_tvalid,
    input  wire        tx_tready,
    output wire        tx_tlast,

    // status
    output wire [15:0] frames_done,
    output wire [15:0] rows_bad_total
);

localparam [15:0] MAGIC_DN = 16'h5AA5;
localparam [15:0] MAGIC_UP = 16'h3CC3;
localparam RES_BYTES = 40;

localparam [1:0] S_IDLE = 2'd0, S_PAY = 2'd1, S_DROP = 2'd2, S_COMMIT = 2'd3;

reg [1:0]  state = S_IDLE;
reg [31:0] cyc = 0;

// current packet
reg [15:0] p_len = 0;          // UDP length (header + payload)
reg [31:0] p_src_ip = 0;
reg [15:0] p_src_port = 0;
reg [10:0] p_idx = 0;          // payload byte index (saturates)
reg [15:0] p_magic = 0;
reg [31:0] p_fid = 0;
reg [15:0] p_row = 0, p_width = 0, p_height = 0;
reg [15:0] p_npix = 0;
reg [31:0] p_sum = 0;
reg        p_err = 0;
reg [31:0] p_t0 = 0;

// current frame
reg        f_active = 0;
reg [31:0] f_fid = 0;
reg [15:0] f_rows = 0, f_bad = 0, f_height = 0, f_width = 0;
reg [31:0] f_sum = 0, f_t0 = 0, f_t1 = 0;
reg [31:0] f_dst_ip = 0;
reg [15:0] f_dst_port = 0;

// result being sent
reg        r_pending = 0;
reg        r_hdr_done = 0;
reg [8*RES_BYTES-1:0] r_shift = 0;
reg [5:0]  r_cnt = 0;
reg [31:0] r_dst_ip = 0;
reg [15:0] r_dst_port = 0;

reg [15:0] frames_done_reg = 0, rows_bad_total_reg = 0;

wire row_good = !p_err && (p_magic == MAGIC_DN) && (p_len == 16'd20 + p_width)
                && (p_npix == p_width) && (p_row < p_height) && (p_height != 0);

assign rx_hdr_ready = (state == S_IDLE);
assign rx_tready    = (state == S_PAY) || (state == S_DROP);

assign tx_hdr_valid   = r_pending && !r_hdr_done;
assign tx_ip_dest_ip  = r_dst_ip;
assign tx_source_port = PORT;
assign tx_dest_port   = r_dst_port;
assign tx_length      = 16'd8 + RES_BYTES;
assign tx_tdata       = r_shift[7:0];
assign tx_tvalid      = r_pending && r_hdr_done;
assign tx_tlast       = (r_cnt == RES_BYTES - 1);

assign frames_done    = frames_done_reg;
assign rows_bad_total = rows_bad_total_reg;

// emit: load the result of the current frame into the TX shift register
task emit(input [15:0] flags, input [31:0] t_res);
begin
    r_shift <= {32'd0, 16'sd0, 16'sd0, t_res, f_t1, f_t0, f_sum,
                f_width, f_height, f_bad, f_rows, f_fid, flags, MAGIC_UP};
    r_dst_ip <= f_dst_ip;
    r_dst_port <= f_dst_port;
    r_pending <= 1'b1;
    r_hdr_done <= 1'b0;
    r_cnt <= 0;
    frames_done_reg <= frames_done_reg + 1;
end
endtask

always @(posedge clk) begin
    cyc <= cyc + 1;

    // TX side
    if (tx_hdr_valid && tx_hdr_ready) r_hdr_done <= 1'b1;
    if (tx_tvalid && tx_tready) begin
        r_shift <= r_shift >> 8;
        r_cnt <= r_cnt + 1;
        if (tx_tlast) r_pending <= 1'b0;
    end

    // RX side
    case (state)
    S_IDLE: begin
        if (rx_hdr_valid) begin
            p_len <= rx_length;
            p_src_ip <= rx_ip_source_ip;
            p_src_port <= rx_source_port;
            p_idx <= 0;
            p_npix <= 0;
            p_sum <= 0;
            p_err <= 0;
            p_t0 <= cyc;
            state <= (rx_dest_port == PORT) ? S_PAY : S_DROP;
        end
    end
    S_PAY: begin
        if (rx_tvalid) begin
            case (p_idx)
                11'd0:  p_magic[7:0]   <= rx_tdata;
                11'd1:  p_magic[15:8]  <= rx_tdata;
                11'd2:  p_fid[7:0]     <= rx_tdata;
                11'd3:  p_fid[15:8]    <= rx_tdata;
                11'd4:  p_fid[23:16]   <= rx_tdata;
                11'd5:  p_fid[31:24]   <= rx_tdata;
                11'd6:  p_row[7:0]     <= rx_tdata;
                11'd7:  p_row[15:8]    <= rx_tdata;
                11'd8:  p_width[7:0]   <= rx_tdata;
                11'd9:  p_width[15:8]  <= rx_tdata;
                11'd10: p_height[7:0]  <= rx_tdata;
                11'd11: p_height[15:8] <= rx_tdata;
                default: begin
                    p_sum <= p_sum + rx_tdata;
                    p_npix <= p_npix + 1;
                end
            endcase
            if (p_idx != 11'h7FF) p_idx <= p_idx + 1;
            if (rx_tlast) begin
                if (rx_tuser || p_idx < 11'd11) p_err <= 1'b1;
                state <= S_COMMIT;
            end
        end
    end
    S_DROP: begin
        if (rx_tvalid && rx_tlast) state <= S_IDLE;
    end
    S_COMMIT: begin
        if (!r_pending) begin
            if (!row_good) begin
                // bad row: count it against the open frame (if any) and drop it
                if (f_active) f_bad <= f_bad + 1;
                rows_bad_total_reg <= rows_bad_total_reg + 1;
                state <= S_IDLE;
            end else if (f_active && p_fid != f_fid) begin
                // a newer frame started: close the open frame as incomplete,
                // then handle this row again on the next cycle
                emit(16'h0002, cyc);
                f_active <= 1'b0;
            end else begin
                if (!f_active) begin
                    f_active <= 1'b1;
                    f_fid <= p_fid;
                    f_bad <= 0;
                    f_height <= p_height;
                    f_width <= p_width;
                    f_t0 <= p_t0;
                end
                f_dst_ip <= p_src_ip;
                f_dst_port <= p_src_port;
                f_t1 <= cyc;
                state <= S_IDLE;
                if ((f_active ? f_rows : 16'd0) + 1 == (f_active ? f_height : p_height)) begin
                    // last row: close as complete. emit() reads the f_* registers, so
                    // build the result directly from this row's updated values.
                    r_shift <= {32'd0, 16'sd0, 16'sd0, cyc, cyc,
                                (f_active ? f_t0 : p_t0),
                                (f_active ? f_sum : 32'd0) + p_sum,
                                (f_active ? f_width : p_width),
                                (f_active ? f_height : p_height),
                                (f_active ? f_bad : 16'd0),
                                (f_active ? f_rows : 16'd0) + 16'd1,
                                p_fid, 16'h0001, MAGIC_UP};
                    r_dst_ip <= p_src_ip;
                    r_dst_port <= p_src_port;
                    r_pending <= 1'b1;
                    r_hdr_done <= 1'b0;
                    r_cnt <= 0;
                    frames_done_reg <= frames_done_reg + 1;
                    f_active <= 1'b0;
                    f_rows <= 0;
                    f_sum <= 0;
                end else begin
                    f_rows <= (f_active ? f_rows : 16'd0) + 1;
                    f_sum <= (f_active ? f_sum : 32'd0) + p_sum;
                end
            end
        end
    end
    endcase

    if (rst) begin
        state <= S_IDLE;
        cyc <= 0;
        f_active <= 0;
        f_rows <= 0;
        f_sum <= 0;
        f_bad <= 0;
        r_pending <= 0;
        r_hdr_done <= 0;
        frames_done_reg <= 0;
        rows_bad_total_reg <= 0;
    end
end

endmodule

`resetall
