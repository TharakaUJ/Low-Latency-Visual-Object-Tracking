/*
 * row_stats (P2): the P1 row protocol plus a tracker path for the DE2-115 ZSAD demo.
 *
 * Downlink (UDP to PORT), little-endian:
 *   row:      magic u16 = 0x5AA5, frame_id u32, row u16, width u16, height u16, then width pixels (u8)
 *   template: magic u16 = 0x5AA6, then 256 template bytes (16x16, row-major)
 * Uplink, one 40-byte packet, little-endian:
 *   0 magic u16 (0x3CC3 frame result, 0x3CC4 template ack)   2 flags u16
 *   4 frame_id u32   8 rows_seen u16   10 rows_bad u16   12 height u16   14 width u16
 *  16 checksum u32 (frame: sum of good-row pixels; ack: sum of the 256 template bytes)
 *  20 t_rx_start u32   24 t_rx_end u32   28 t_result u32   (free-running 125 MHz counter)
 *  32 x u16   34 y u16   36 score u32   (tracker: best window top-left in the ROI, min ZSAD sat. 16 bit)
 * flags: bit0 complete, bit1 closed by a newer frame_id, bit2 good (score <= REJECT_SAD),
 *        bit3 tracked, bit4 tracker timeout.
 *
 * Frame rules are the P1 rules (see p1_rows/rtl/row_stats.v). New: a frame whose width and height
 * equal ROI is forwarded to the tracker: each row whose header checks out goes into the tracker
 * FIFO as one FIFO frame [ctrl word, ROI pixel words], marked bad (dropped by the FIFO) if the row
 * turns out bad at its end. A complete frame whose rows all arrived in order (row index = number
 * of good rows before it) is "trackable": its result waits for the tracker (matched by a 4-bit
 * frame tag), at most TRK_TIMEOUT cycles. Other frames are reported at once, untracked.
 * Tracker FIFO words: {tag[1:0], payload[13:0]}
 *   tag 0 pixel:     payload[7:0] = pixel
 *   tag 1 row ctrl:  payload[13] new_frame, [12:9] frame tag, [8:0] row index
 *   tag 2 template:  payload[7:0] = template byte (256 per FIFO frame, row-major)
 */

`resetall
`timescale 1ns / 1ps
`default_nettype none

module row_stats #
(
    parameter [15:0] PORT = 16'd1234,
    parameter ROI = 80,
    parameter REJECT_SAD = 8192,
    parameter TRK_TIMEOUT = 1250000          // 10 ms at 125 MHz
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

    // tracker FIFO input (AXI stream, this clock domain)
    output wire [15:0] trk_tdata,
    output wire        trk_tvalid,
    input  wire        trk_tready,
    output wire        trk_tlast,
    output wire        trk_tuser,

    // tracker result (from the tracker clock domain: toggle + data held stable between toggles)
    input  wire        res_toggle,
    input  wire [3:0]  res_ftag,
    input  wire [7:0]  res_x,
    input  wire [7:0]  res_y,
    input  wire [15:0] res_score,

    // status
    output wire [15:0] frames_done,
    output wire [15:0] rows_bad_total
);

localparam [15:0] MAGIC_ROW = 16'h5AA5, MAGIC_TMPL = 16'h5AA6;
localparam [15:0] MAGIC_RES = 16'h3CC3, MAGIC_ACK  = 16'h3CC4;
localparam RES_BYTES = 40;
localparam [15:0] TMPL_LEN = 16'd8 + 16'd2 + 16'd256;

localparam [2:0] S_IDLE = 3'd0, S_PAY = 3'd1, S_DROP = 3'd2, S_COMMIT = 3'd3, S_WAIT = 3'd4;

reg [2:0]  state = S_IDLE;
reg [31:0] cyc = 0;

// current packet
reg [15:0] p_len = 0;
reg [31:0] p_src_ip = 0;
reg [15:0] p_src_port = 0;
reg [10:0] p_idx = 0;
reg [15:0] p_magic = 0;
reg [31:0] p_fid = 0;
reg [15:0] p_row = 0, p_width = 0, p_height = 0;
reg [15:0] p_npix = 0;
reg [31:0] p_sum = 0;
reg [31:0] p_tsum = 0;          // sum of template bytes
reg        p_err = 0;
reg [31:0] p_t0 = 0;
reg        p_fwd = 0;           // this packet is being forwarded to the tracker FIFO
reg        p_tmpl = 0;          // this packet is a (forwarded) template packet
reg        p_roi = 0;           // header says width == height == ROI (registered at the header end)
reg        p_h1 = 0;            // header says height == 1

// current frame
reg        f_active = 0;
reg [31:0] f_fid = 0;
reg [15:0] f_rows = 0, f_bad = 0, f_height = 0, f_width = 0;
reg [31:0] f_sum = 0, f_t0 = 0, f_t1 = 0;
reg [31:0] f_dst_ip = 0;
reg [15:0] f_dst_port = 0;
reg        f_inorder = 0;
reg        f_next_last = 0;
reg        f_roi = 0;          // the open frame is ROI x ROI    // the next good row completes the open frame (precomputed)
reg [3:0]  f_tag = 0;           // frame tag of the open frame (sent in its ctrl words)
reg [3:0]  next_tag = 0;

// result being sent
reg        r_pending = 0;
reg        r_hdr_done = 0;
reg [8*RES_BYTES-1:0] r_shift = 0;
reg [5:0]  r_cnt = 0;
reg [31:0] r_dst_ip = 0;
reg [15:0] r_dst_port = 0;

// result staging: assembled here, copied into r_shift one cycle later (keeps the r_shift mux small)
reg        s_load = 0;
reg [8*RES_BYTES-1:0] s_res = 0;
reg [31:0] s_ip = 0;
reg [15:0] s_port = 0;
wire       tx_busy = r_pending || s_load;

// result waiting for the tracker
reg [8*RES_BYTES-1:0] w_res = 0;    // result with x/y/score/t_result still to fill in
reg [3:0]  w_tag = 0;
reg [31:0] w_t = 0;
reg        w_timeout = 0;      // registered (cyc - w_t >= TRK_TIMEOUT), keeps the compare off the s_res enable

reg [15:0] frames_done_reg = 0, rows_bad_total_reg = 0;

// tracker result toggle, synchronised
reg [2:0]  res_sync = 0;
wire       res_new = res_sync[2] ^ res_sync[1];

// --- header checks for forwarding (evaluated on the beat that completes the header) ---
wire [15:0] hdr_height = {rx_tdata, p_height[7:0]};          // at p_idx == 11
wire fwd_row_hdr = (p_magic == MAGIC_ROW) && (p_len == 16'd20 + p_width) &&
                   (p_width == ROI) && (hdr_height == ROI) && (p_row < hdr_height);
wire new_frame   = !f_active || (p_fid != f_fid);
wire [3:0] row_tag = new_frame ? next_tag : f_tag;
wire fwd_tmpl_hdr = ({rx_tdata, p_magic[7:0]} == MAGIC_TMPL) && (p_len == TMPL_LEN);   // at p_idx == 1

// beat classification in S_PAY
wire beat_ctrl  = (p_idx == 11'd11) && fwd_row_hdr;
wire beat_pix   = p_fwd && !p_tmpl && (p_idx >= 11'd12);
wire beat_tbyte = p_tmpl && (p_idx >= 11'd2);
wire beat_fwd   = (state == S_PAY) && rx_tvalid && (beat_ctrl || beat_pix || beat_tbyte);
// row/template bad at its end (pixel count or MAC/IP error); the FIFO drops the whole FIFO frame
wire fwd_bad_end = rx_tuser || (p_tmpl ? (p_idx != 11'd257) : (beat_ctrl || (p_npix + 16'd1 != p_width)));

assign trk_tdata  = beat_ctrl  ? {2'd1, new_frame, row_tag, p_row[8:0]} :
                    beat_tbyte ? {2'd2, 6'd0, rx_tdata} :
                                 {2'd0, 6'd0, rx_tdata};
assign trk_tvalid = beat_fwd;
assign trk_tlast  = rx_tlast;
assign trk_tuser  = rx_tlast && fwd_bad_end;

wire row_good = !p_err && (p_magic == MAGIC_ROW) && (p_len == 16'd20 + p_width)
                && (p_npix == p_width) && (p_row < p_height) && (p_height != 0);
wire tmpl_good = !p_err && p_tmpl;

assign rx_hdr_ready = (state == S_IDLE);
assign rx_tready    = (state == S_DROP) || ((state == S_PAY) && (!(beat_ctrl || beat_pix || beat_tbyte) || trk_tready));

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

// result word, LSB byte first
function [8*RES_BYTES-1:0] pack;
    input [15:0] magic, flags;
    input [31:0] fid;
    input [15:0] rows, bad, height, width;
    input [31:0] cks, t0, t1, tres;
    input [15:0] x, y;
    input [31:0] score;
    pack = {score, y, x, tres, t1, t0, cks, width, height, bad, rows, fid, flags, magic};
endfunction

task send(input [8*RES_BYTES-1:0] res, input [31:0] ip, input [15:0] port);
begin
    s_res <= res;
    s_ip <= ip;
    s_port <= port;
    s_load <= 1'b1;
end
endtask

always @(posedge clk) begin
    cyc <= cyc + 1;
    res_sync <= {res_sync[1:0], res_toggle};
    w_timeout <= (state == S_WAIT) && (cyc - w_t >= TRK_TIMEOUT);

    // TX side
    if (tx_hdr_valid && tx_hdr_ready) r_hdr_done <= 1'b1;
    if (tx_tvalid && tx_tready) begin
        r_shift <= r_shift >> 8;
        r_cnt <= r_cnt + 1;
        if (tx_tlast) r_pending <= 1'b0;
    end
    if (s_load) begin                       // never while r_pending (send() waits for !tx_busy)
        r_shift <= s_res;
        r_dst_ip <= s_ip;
        r_dst_port <= s_port;
        r_pending <= 1'b1;
        r_hdr_done <= 1'b0;
        r_cnt <= 0;
        s_load <= 1'b0;
    end

    case (state)
    S_IDLE: begin
        if (rx_hdr_valid) begin
            p_len <= rx_length;
            p_src_ip <= rx_ip_source_ip;
            p_src_port <= rx_source_port;
            p_idx <= 0;
            p_npix <= 0;
            p_sum <= 0;
            p_tsum <= 0;
            p_err <= 0;
            p_fwd <= 0;
            p_tmpl <= 0;
            p_roi <= 0;
            p_h1 <= 0;
            p_t0 <= cyc;
            state <= (rx_dest_port == PORT) ? S_PAY : S_DROP;
        end
    end
    S_PAY: begin
        if (rx_tvalid && rx_tready) begin
            case (p_idx)
                11'd0:  p_magic[7:0]   <= rx_tdata;
                11'd1:  begin
                            p_magic[15:8] <= rx_tdata;
                            if (fwd_tmpl_hdr) begin p_tmpl <= 1'b1; p_fwd <= 1'b1; end
                        end
                11'd2:  p_fid[7:0]     <= rx_tdata;
                11'd3:  p_fid[15:8]    <= rx_tdata;
                11'd4:  p_fid[23:16]   <= rx_tdata;
                11'd5:  p_fid[31:24]   <= rx_tdata;
                11'd6:  p_row[7:0]     <= rx_tdata;
                11'd7:  p_row[15:8]    <= rx_tdata;
                11'd8:  p_width[7:0]   <= rx_tdata;
                11'd9:  p_width[15:8]  <= rx_tdata;
                11'd10: p_height[7:0]  <= rx_tdata;
                11'd11: begin
                            p_height[15:8] <= rx_tdata;
                            if (fwd_row_hdr) p_fwd <= 1'b1;
                            p_roi <= (p_width == ROI) && (hdr_height == ROI);
                            p_h1  <= (hdr_height == 16'd1);
                        end
                default: begin
                    p_sum <= p_sum + rx_tdata;
                    p_npix <= p_npix + 1;
                end
            endcase
            if (beat_tbyte) p_tsum <= p_tsum + rx_tdata;
            if (p_idx != 11'h7FF) p_idx <= p_idx + 1;
            if (rx_tlast) begin
                if (rx_tuser || (p_tmpl ? (p_idx != 11'd257) : (p_idx < 11'd11))) p_err <= 1'b1;
                state <= S_COMMIT;
            end
        end
    end
    S_DROP: begin
        if (rx_tvalid && rx_tlast) state <= S_IDLE;
    end
    S_COMMIT: begin
        if (!tx_busy) begin
            if (p_tmpl) begin
                // template: ack it (the tracker applies it at its next frame start)
                if (tmpl_good)
                    send(pack(MAGIC_ACK, 16'd0, 32'd0, 16'd0, 16'd0, 16'd16, 16'd16, p_tsum,
                              p_t0, cyc, cyc, 16'd0, 16'd0, 32'd0), p_src_ip, p_src_port);
                else
                    rows_bad_total_reg <= rows_bad_total_reg + 1;
                state <= S_IDLE;
            end else if (!row_good) begin
                if (f_active) f_bad <= f_bad + 1;
                rows_bad_total_reg <= rows_bad_total_reg + 1;
                state <= S_IDLE;
            end else if (f_active && p_fid != f_fid) begin
                // a newer frame started: close the open frame as incomplete (never tracked),
                // then handle this row again on the next cycle
                send(pack(MAGIC_RES, 16'h0002, f_fid, f_rows, f_bad, f_height, f_width, f_sum,
                          f_t0, f_t1, cyc, 16'd0, 16'd0, 32'd0), f_dst_ip, f_dst_port);
                frames_done_reg <= frames_done_reg + 1;
                f_active <= 1'b0;
            end else begin : good_row
                reg [15:0] rows_n, bad_n, h_n, w_n;
                reg [31:0] sum_n, t0_n;
                reg        inorder_n;
                rows_n    = (f_active ? f_rows : 16'd0) + 16'd1;
                bad_n     =  f_active ? f_bad : 16'd0;
                h_n       =  f_active ? f_height : p_height;
                w_n       =  f_active ? f_width : p_width;
                sum_n     = (f_active ? f_sum : 32'd0) + p_sum;
                t0_n      =  f_active ? f_t0 : p_t0;
                inorder_n = f_active ? (f_inorder && (p_row == f_rows)) : (p_row == 16'd0);
                if (!f_active) begin
                    f_fid <= p_fid;
                    f_tag <= next_tag;          // the same tag went out in this row's ctrl word
                    f_roi <= p_roi;
                    next_tag <= next_tag + 1;
                end
                f_active <= 1'b1;
                f_rows <= rows_n;
                f_bad <= bad_n;
                f_height <= h_n;
                f_width <= w_n;
                f_sum <= sum_n;
                f_t0 <= t0_n;
                f_t1 <= cyc;
                f_inorder <= inorder_n;
                f_next_last <= (rows_n + 16'd1 == h_n);
                f_dst_ip <= p_src_ip;
                f_dst_port <= p_src_port;
                state <= S_IDLE;
                if (f_active ? f_next_last : p_h1) begin
                    // last row: frame complete
                    f_active <= 1'b0;
                    frames_done_reg <= frames_done_reg + 1;
                    if (inorder_n && (f_active ? f_roi : p_roi)) begin
                        w_res <= pack(MAGIC_RES, 16'h0001, f_active ? f_fid : p_fid, rows_n, bad_n,
                                      h_n, w_n, sum_n, t0_n, cyc, 32'd0, 16'd0, 16'd0, 32'd0);
                        w_tag <= f_active ? f_tag : next_tag;
                        w_t <= cyc;
                        state <= S_WAIT;
                    end else begin
                        send(pack(MAGIC_RES, 16'h0001, f_active ? f_fid : p_fid, rows_n, bad_n,
                                  h_n, w_n, sum_n, t0_n, cyc, cyc, 16'd0, 16'd0, 32'd0),
                             p_src_ip, p_src_port);
                    end
                end
            end
        end
    end
    S_WAIT: begin
        // wait for the tracker result of this frame (tag match), or time out
        if (res_new && res_ftag == w_tag) begin
            s_res <= w_res;
            s_res[31:16]   <= w_res[31:16] | ((res_score <= REJECT_SAD) ? 16'h000C : 16'h0008);
            s_res[255:224] <= cyc;
            s_res[271:256] <= {8'd0, res_x};
            s_res[287:272] <= {8'd0, res_y};
            s_res[319:288] <= {16'd0, res_score};
            s_ip <= f_dst_ip;
            s_port <= f_dst_port;
            s_load <= 1'b1;
            state <= S_IDLE;
        end else if (w_timeout) begin
            s_res <= w_res;
            s_res[31:16]   <= w_res[31:16] | 16'h0010;
            s_res[255:224] <= cyc;
            s_ip <= f_dst_ip;
            s_port <= f_dst_port;
            s_load <= 1'b1;
            state <= S_IDLE;
        end
    end
    default: state <= S_IDLE;
    endcase

    if (rst) begin
        state <= S_IDLE;
        cyc <= 0;
        f_active <= 0;
        f_rows <= 0;
        f_sum <= 0;
        f_bad <= 0;
        next_tag <= 0;
        r_pending <= 0;
        r_hdr_done <= 0;
        s_load <= 0;
        frames_done_reg <= 0;
        rows_bad_total_reg <= 0;
    end
end

endmodule

`resetall
