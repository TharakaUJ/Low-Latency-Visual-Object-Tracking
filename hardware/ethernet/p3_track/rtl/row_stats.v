/*
 * row_stats (P3): UDP row protocol, ROI crop in the RTL, FPGA-held target position, one pending
 * tracker result (the receiver keeps running while the tracker works). Tracker-independent: the
 * tracker core (zsad_core or s3x8_core) sits behind the tracker FIFO.
 *
 * Downlink (UDP to PORT), little-endian:
 *   row:       magic 0x5AA5, frame_id u32, row u16, width u16, height u16, then width pixels (u8)
 *   template:  magic 0x5AA6, offset u16, then n template bytes (offset + n <= TMPL_BYTES)
 *   position:  magic 0x5AA7, tx u16, ty u16  (target window top-left in frame pixels)
 * Uplink, one 44-byte packet, little-endian:
 *   0 magic u16 (0x3CC3 frame, 0x3CC4 template ack, 0x3CC5 position ack)   2 flags u16
 *   4 frame_id u32 (ack: offset / 0)   8 rows_seen u16 (ack: n)   10 rows_bad u16
 *  12 height u16  14 width u16  16 checksum u32 (frame: good-row pixel sum; template ack: byte sum)
 *  20 t_rx_start u32  24 t_rx_end u32  28 t_result u32   (125 MHz counter)
 *  32 x u16  34 y u16   target position (window top-left, frame pixels) after this frame
 *  36 score u32 (tracker score)   40 roi_x u16  42 roi_y u16  (ROI origin used for this frame)
 * flags: bit0 complete, bit1 closed by a newer frame_id, bit2 good, bit3 tracked, bit4 tracker
 *        timeout, bit5 ROI cropped in the RTL (frame larger than ROI x ROI).
 *
 * Frame rules: as P1/P2. A frame is trackable when its first row says width >= ROI and
 * height >= ROI, it completes, and all rows arrived in order (row index = number of good rows
 * before it). ROI origin for a frame (fixed at its first row): clamp(t - (ROI-16)/2, 0, size - ROI)
 * from the current position t. A frame of exactly ROI x ROI has origin (0, 0) (server-side crop).
 * After a good result: t = origin + best + MARGIN.
 * Tracker FIFO words {tag[1:0], payload[13:0]}: tag 0 pixel [7:0]; tag 1 row ctrl [13] new_frame,
 * [12:9] frame tag, [8:0] row in the ROI; tag 2 template byte [7:0]; tag 3 template offset [13:0].
 * One FIFO frame per ROI row ([ctrl, ROI pixels]) or per template chunk ([offset, bytes]).
 * The receiver stalls only (a) at the first row of a frame larger than the ROI while a tracker
 * result is still outstanding (its origin depends on that result), and (b) when a trackable frame
 * completes while the previous one is still outstanding (one pending slot).
 */

`resetall
`timescale 1ns / 1ps
`default_nettype none

module row_stats #
(
    parameter [15:0] PORT = 16'd1234,
    parameter ROI = 80,
    parameter MARGIN = 0,                    // tracker: best (0,0) = window top-left at ROI (MARGIN, MARGIN)
    parameter TMPL_BYTES = 256,
    parameter [23:0] GOOD_MAX = 24'd8192,    // result is good when score <= GOOD_MAX
    parameter TRK_TIMEOUT = 1250000          // 10 ms at 125 MHz
)
(
    input  wire        clk,
    input  wire        rst,

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

    output wire [15:0] trk_tdata,
    output wire        trk_tvalid,
    input  wire        trk_tready,
    output wire        trk_tlast,
    output wire        trk_tuser,

    input  wire        res_toggle,          // tracker clock domain: toggle + data held between toggles
    input  wire [3:0]  res_ftag,
    input  wire [7:0]  res_x,
    input  wire [7:0]  res_y,
    input  wire [23:0] res_score,

    output wire [15:0] frames_done,
    output wire [15:0] rows_bad_total
);

localparam [15:0] MAGIC_ROW = 16'h5AA5, MAGIC_TMPL = 16'h5AA6, MAGIC_POS = 16'h5AA7;
localparam [15:0] MAGIC_RES = 16'h3CC3, MAGIC_TACK = 16'h3CC4, MAGIC_PACK = 16'h3CC5;
localparam RES_BYTES = 44;
localparam RB = 8 * RES_BYTES;
localparam [15:0] OFF = (ROI - 16) / 2;

localparam [3:0] S_IDLE = 4'd0, S_PAY = 4'd1, S_DROP = 4'd2, S_COMMIT = 4'd3,
                 S_HDR_A = 4'd4, S_HDR_B = 4'd5, S_CTRL = 4'd6, S_TMPL_HDR = 4'd7, S_TOFF = 4'd8, S_SLOT = 4'd9,
                 S_HDR_A2 = 4'd10;

reg [3:0]  state = S_IDLE;
reg [31:0] cyc = 0;

// ---------------- current packet ----------------
reg [15:0] p_len = 0;
reg [31:0] p_src_ip = 0;
reg [15:0] p_src_port = 0;
reg [10:0] p_idx = 0;
reg [15:0] p_magic = 0;
reg [31:0] p_fid = 0;
reg [15:0] p_row = 0, p_width = 0, p_height = 0;   // template: p_fid[15:0] = offset; position: p_row = tx, p_width = ty
reg [15:0] p_npix = 0;
reg [31:0] p_sum = 0, p_tsum = 0;
reg        p_err = 0;
reg [31:0] p_t0 = 0;
reg        p_rowhdr = 0;     // header of a row packet checked out (magic, length, height != 0)
reg        p_tmpl = 0;       // template chunk being forwarded
reg        p_roi = 0;        // frame (per this row's header) is at least ROI x ROI
reg        p_crop = 0;       // ... and larger than ROI x ROI (crop in the RTL)
reg        p_h1 = 0;
reg        p_new = 0;        // this row would start a new frame
reg [15:0] p_ox = 0, p_oy = 0, p_xend = 0;
reg        p_inwin = 0;      // this row is forwarded to the tracker
reg        p_fwd_open = 0;   // tracker FIFO frame open for this packet
reg [10:0] p_col = 0;
reg [15:0] p_n = 0;         // template chunk: number of bytes (UDP length - 12), from the UDP header
reg [10:0] p_lastidx = 0;   // template chunk: payload index of its last byte (UDP length - 9)
reg        p_len14 = 0;     // UDP length 14 (position command)
reg signed [17:0] a_x = 0, a_y = 0, hi_x = 0, hi_y = 0;   // origin computation, stage 1

// ---------------- current frame ----------------
reg        f_active = 0;
reg [31:0] f_fid = 0;
reg [15:0] f_rows = 0, f_bad = 0, f_height = 0, f_width = 0;
reg [31:0] f_sum = 0, f_t0 = 0, f_t1 = 0;
reg [31:0] f_dst_ip = 0;
reg [15:0] f_dst_port = 0;
reg        f_inorder = 0, f_next_last = 0, f_roi = 0, f_crop = 0;
reg        f_trk_started = 0;   // a forwarded row of this frame reached the tracker
reg [3:0]  f_tag = 0, next_tag = 0;
reg [15:0] f_ox = 0, f_oy = 0;

// target position (window top-left, frame pixels)
reg [15:0] pos_x = 0, pos_y = 0;

// ---------------- pending tracker result (one slot) ----------------
reg        q_valid = 0, q_ready = 0;
reg [RB-1:0] q_res = 0;          // frame fields; tracker fields filled in when ready
reg [3:0]  q_tag = 0;
reg [31:0] q_t = 0;
reg [15:0] q_ox = 0, q_oy = 0;
reg        q_timeout = 0;
reg [31:0] q_dst_ip = 0;
reg [15:0] q_dst_port = 0;
reg        q_tmo_hit = 0;        // registered timeout compare
// next pending entry, held here until the slot is free (S_SLOT)
reg [RB-1:0] n_res = 0;
reg [3:0]  n_tag = 0;
reg [15:0] n_ox = 0, n_oy = 0;
reg [31:0] n_dst_ip = 0;
reg [15:0] n_dst_port = 0;

// ---------------- TX ----------------
reg        r_pending = 0, r_hdr_done = 0;
reg [RB-1:0] r_shift = 0;
reg [5:0]  r_cnt = 0;
reg [31:0] r_dst_ip = 0;
reg [15:0] r_dst_port = 0;
reg        s_load = 0;
reg [RB-1:0] s_res = 0;
reg [31:0] s_ip = 0;
reg [15:0] s_port = 0;
wire       tx_busy = r_pending || s_load;

reg [15:0] frames_done_reg = 0, rows_bad_total_reg = 0;
reg [2:0]  res_sync = 0;
wire       res_new = res_sync[2] ^ res_sync[1];

// ---------------- tracker FIFO output ----------------
reg [15:0] t_data_r;
reg        t_valid_r, t_last_r, t_user_r;
// pixel beat of a forwarded row
wire [10:0] col_now  = p_col;
wire pix_in_win  = p_fwd_open && !p_tmpl && (col_now >= p_ox[10:0]);
wire pix_win_end = (col_now == p_xend[10:0]);
wire beat_pix    = (state == S_PAY) && rx_tvalid && p_fwd_open && !p_tmpl && (pix_in_win || rx_tlast) && (p_idx >= 11'd12);
wire beat_tbyte  = (state == S_PAY) && rx_tvalid && p_fwd_open && p_tmpl && (p_idx >= 11'd4);
wire ctrl_push   = (state == S_CTRL);
wire toff_push   = (state == S_TOFF);

assign trk_tdata  = ctrl_push  ? {2'd1, (p_new || !f_trk_started), (p_new ? next_tag : f_tag), (p_row[8:0] - p_oy[8:0])} :
                    toff_push  ? {2'd3, p_fid[13:0]} :
                    beat_tbyte ? {2'd2, 6'd0, rx_tdata} :
                                 {2'd0, 6'd0, rx_tdata};
assign trk_tvalid = ctrl_push || toff_push || beat_pix || beat_tbyte;
assign trk_tlast  = beat_tbyte ? rx_tlast : (beat_pix && (pix_win_end || rx_tlast));
assign trk_tuser  = beat_tbyte ? (rx_tlast && (rx_tuser || p_idx != p_lastidx)) :
                    (beat_pix && rx_tlast && (!pix_win_end || rx_tuser || !pix_in_win));

assign rx_hdr_ready = (state == S_IDLE) && !(q_ready && !tx_busy);
assign rx_tready    = (state == S_DROP) ||
                      ((state == S_PAY) && (!(beat_pix || beat_tbyte) || trk_tready));

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

wire row_good  = !p_err && p_rowhdr && (p_npix == p_width) && (p_row < p_height);
wire tmpl_good = !p_err && p_tmpl;
wire pos_good  = !p_err && (p_magic == MAGIC_POS) && p_len14;

function [RB-1:0] pack;
    input [15:0] magic, flags;
    input [31:0] fid;
    input [15:0] rows, bad, height, width;
    input [31:0] cks, t0, t1, tres;
    input [15:0] x, y;
    input [31:0] score;
    input [15:0] rx, ry;
    pack = {ry, rx, score, y, x, tres, t1, t0, cks, width, height, bad, rows, fid, flags, magic};
endfunction

task send(input [RB-1:0] res, input [31:0] ip, input [15:0] port);
begin
    s_res <= res;
    s_ip <= ip;
    s_port <= port;
    s_load <= 1'b1;
end
endtask


// emission of the pending result: allowed in the states where the FSM itself does not send
wire q_emit = q_ready && !tx_busy && (state == S_IDLE || state == S_HDR_A || state == S_SLOT);

always @(posedge clk) begin
    cyc <= cyc + 1;
    res_sync <= {res_sync[1:0], res_toggle};
    q_tmo_hit <= q_valid && !q_ready && (cyc - q_t >= TRK_TIMEOUT);

    // ---------------- TX ----------------
    if (tx_hdr_valid && tx_hdr_ready) r_hdr_done <= 1'b1;
    if (tx_tvalid && tx_tready) begin
        r_shift <= r_shift >> 8;
        r_cnt <= r_cnt + 1;
        if (tx_tlast) r_pending <= 1'b0;
    end
    if (s_load) begin
        r_shift <= s_res;
        r_dst_ip <= s_ip;
        r_dst_port <= s_port;
        r_pending <= 1'b1;
        r_hdr_done <= 1'b0;
        r_cnt <= 0;
        s_load <= 1'b0;
    end

    // ---------------- tracker result for the pending frame ----------------
    if (q_valid && !q_ready) begin
        if (res_new && res_ftag == q_tag) begin : got_res
            reg        good;
            reg [15:0] nx, ny;
            good = (res_score <= GOOD_MAX);
            nx = q_ox + {8'd0, res_x} + MARGIN;
            ny = q_oy + {8'd0, res_y} + MARGIN;
            if (good) begin
                pos_x <= nx;
                pos_y <= ny;
            end
            q_res[31:16]  <= q_res[31:16] | (good ? 16'h000C : 16'h0008);
            q_res[255:224] <= cyc;
            q_res[271:256] <= good ? nx : pos_x;
            q_res[287:272] <= good ? ny : pos_y;
            q_res[319:288] <= {8'd0, res_score};
            q_ready <= 1'b1;
        end else if (q_tmo_hit) begin
            q_res[31:16]  <= q_res[31:16] | 16'h0010;
            q_res[255:224] <= cyc;
            q_res[271:256] <= pos_x;
            q_res[287:272] <= pos_y;
            q_ready <= 1'b1;
        end
    end
    if (q_emit) begin
        send(q_res, q_dst_ip, q_dst_port);
        q_valid <= 1'b0;
        q_ready <= 1'b0;
    end

    // ---------------- RX ----------------
    case (state)
    S_IDLE: begin
        if (rx_hdr_valid && rx_hdr_ready) begin
            p_len <= rx_length;
            p_src_ip <= rx_ip_source_ip;
            p_src_port <= rx_source_port;
            p_idx <= 0;
            p_npix <= 0;
            p_sum <= 0;
            p_tsum <= 0;
            p_err <= 0;
            p_rowhdr <= 0;
            p_tmpl <= 0;
            p_inwin <= 0;
            p_fwd_open <= 0;
            p_col <= 0;
            p_t0 <= cyc;
            p_n <= rx_length - 16'd12;
            p_lastidx <= rx_length[10:0] - 11'd9;
            p_len14 <= (rx_length == 16'd14);
            state <= (rx_dest_port == PORT) ? S_PAY : S_DROP;
        end
    end
    S_PAY: begin
        if (rx_tvalid && rx_tready) begin
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
                default: ;
            endcase
            if (p_idx >= 11'd12) begin
                p_sum <= p_sum + rx_tdata;
                p_npix <= p_npix + 1;
                p_col <= p_col + 1;
            end
            if (beat_tbyte) p_tsum <= p_tsum + rx_tdata;
            if (beat_pix && (pix_win_end || rx_tlast)) p_fwd_open <= 1'b0;
            if (p_idx != 11'h7FF) p_idx <= p_idx + 1;
            if (rx_tlast) begin
                // short row packets never reach S_HDR_A, so p_rowhdr stays 0 and they count as bad rows
                if (rx_tuser || (p_tmpl && (p_idx != p_lastidx))) p_err <= 1'b1;
                state <= S_COMMIT;
            end else if (p_idx == 11'd11 && p_magic == MAGIC_ROW) begin
                state <= S_HDR_A;               // stall: work out the crop window for this row
            end else if (p_idx == 11'd3 && p_magic == MAGIC_TMPL) begin
                state <= S_TMPL_HDR;            // stall: check the chunk, push the offset word
            end
        end
    end
    S_HDR_A: begin
        // header registered: row checks, frame size class, ROI origin (new frame: from the position)
        p_rowhdr <= (p_len == 16'd20 + p_width) && (p_height != 0);
        p_roi  <= (p_width >= ROI) && (p_height >= ROI);
        p_crop <= (p_width >= ROI) && (p_height >= ROI) && ((p_width != ROI) || (p_height != ROI));
        p_h1   <= (p_height == 16'd1);
        p_new  <= !f_active || (p_fid != f_fid);
        a_x  <= $signed({2'b00, pos_x}) - $signed({2'b00, OFF});
        a_y  <= $signed({2'b00, pos_y}) - $signed({2'b00, OFF});
        hi_x <= $signed({2'b00, p_width}) - ROI;
        hi_y <= $signed({2'b00, p_height}) - ROI;
        // a cropped new frame needs the outstanding result first (its origin depends on it)
        if (!((!f_active || (p_fid != f_fid)) && (p_width != ROI || p_height != ROI) && q_valid && !q_ready))
            state <= S_HDR_A2;
    end
    S_HDR_A2: begin
        // ROI origin: new frame -> clamp(t - OFF, 0, size - ROI); continuing frame -> the frame's origin
        if (p_new) begin
            p_ox <= (a_x < 0) ? 16'd0 : (a_x > hi_x) ? hi_x[15:0] : a_x[15:0];
            p_oy <= (a_y < 0) ? 16'd0 : (a_y > hi_y) ? hi_y[15:0] : a_y[15:0];
        end else begin
            p_ox <= f_ox;
            p_oy <= f_oy;
        end
        state <= S_HDR_B;
    end
    S_HDR_B: begin
        // forwarding decision from the registered values of S_HDR_A
        if (p_rowhdr && (p_new ? p_roi : f_roi) && (p_row >= p_oy) && (p_row < p_oy + ROI)) begin
            p_inwin <= 1'b1;
            p_xend <= p_ox + ROI - 1;
            state <= S_CTRL;
        end else begin
            state <= S_PAY;
        end
    end
    S_CTRL: begin
        // ctrl word on the tracker FIFO (ctrl_push), then the pixels
        if (trk_tready) begin
            p_fwd_open <= 1'b1;
            state <= S_PAY;
        end
    end
    S_TMPL_HDR: begin
        if ((p_n != 16'd0) && !p_n[15] && ({5'd0, p_fid[15:0]} + {5'd0, p_n} <= TMPL_BYTES)) begin
            p_tmpl <= 1'b1;
            state <= S_TOFF;
        end else begin
            state <= S_PAY;                 // not forwarded: counted bad at commit
        end
    end
    S_TOFF: begin
        // template offset word on the tracker FIFO (toff_push), then the bytes
        if (trk_tready) begin
            p_fwd_open <= 1'b1;
            state <= S_PAY;
        end
    end
    S_DROP: begin
        if (rx_tvalid && rx_tlast) state <= S_IDLE;
    end
    S_COMMIT: begin
        if (!tx_busy && !q_emit) begin
            if (p_magic == MAGIC_TMPL) begin
                if (tmpl_good)
                    send(pack(MAGIC_TACK, 16'd0, {16'd0, p_fid[15:0]}, p_n, 16'd0, 16'd0, 16'd0,
                              p_tsum, p_t0, cyc, cyc, 16'd0, 16'd0, 32'd0, 16'd0, 16'd0), p_src_ip, p_src_port);
                else
                    rows_bad_total_reg <= rows_bad_total_reg + 1;
                state <= S_IDLE;
            end else if (p_magic == MAGIC_POS) begin
                if (pos_good) begin
                    pos_x <= p_fid[15:0];
                    pos_y <= p_fid[31:16];
                    send(pack(MAGIC_PACK, 16'd0, 32'd0, 16'd0, 16'd0, 16'd0, 16'd0, 32'd0,
                              p_t0, cyc, cyc, p_fid[15:0], p_fid[31:16], 32'd0, 16'd0, 16'd0), p_src_ip, p_src_port);
                end else
                    rows_bad_total_reg <= rows_bad_total_reg + 1;
                state <= S_IDLE;
            end else if (!row_good) begin
                if (f_active) f_bad <= f_bad + 1;
                rows_bad_total_reg <= rows_bad_total_reg + 1;
                state <= S_IDLE;
            end else if (f_active && p_fid != f_fid) begin
                // a newer frame started: close the open frame as incomplete, then redo this row
                send(pack(MAGIC_RES, {10'd0, f_crop, 5'h02}, f_fid, f_rows, f_bad, f_height, f_width, f_sum,
                          f_t0, f_t1, cyc, 16'd0, 16'd0, 32'd0, f_ox, f_oy), f_dst_ip, f_dst_port);
                frames_done_reg <= frames_done_reg + 1;
                f_active <= 1'b0;
                p_new <= 1'b1;
            end else begin : good_row
                reg [15:0] rows_n, bad_n, h_n, w_n, ox_n, oy_n;
                reg [31:0] sum_n, t0_n;
                reg        inorder_n, roi_n, crop_n, started_n;
                rows_n    = (f_active ? f_rows : 16'd0) + 16'd1;
                bad_n     =  f_active ? f_bad : 16'd0;
                h_n       =  f_active ? f_height : p_height;
                w_n       =  f_active ? f_width : p_width;
                sum_n     = (f_active ? f_sum : 32'd0) + p_sum;
                t0_n      =  f_active ? f_t0 : p_t0;
                inorder_n =  f_active ? (f_inorder && (p_row == f_rows)) : (p_row == 16'd0);
                roi_n     =  f_active ? f_roi : p_roi;
                crop_n    =  f_active ? f_crop : p_crop;
                ox_n      =  f_active ? f_ox : p_ox;
                oy_n      =  f_active ? f_oy : p_oy;
                started_n = (f_active && f_trk_started) || p_inwin;
                if (!f_active) begin
                    f_fid <= p_fid;
                    f_tag <= next_tag;
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
                f_roi <= roi_n;
                f_crop <= crop_n;
                f_ox <= ox_n;
                f_oy <= oy_n;
                f_trk_started <= started_n;
                f_dst_ip <= p_src_ip;
                f_dst_port <= p_src_port;
                state <= S_IDLE;
                if (f_active ? f_next_last : p_h1) begin
                    f_active <= 1'b0;
                    frames_done_reg <= frames_done_reg + 1;
                    if (inorder_n && roi_n) begin
                        // trackable: becomes the pending result (wait for the slot if it is taken)
                        n_res <= pack(MAGIC_RES, {10'd0, crop_n, 5'h01}, f_active ? f_fid : p_fid, rows_n, bad_n,
                                      h_n, w_n, sum_n, t0_n, cyc, 32'd0, 16'd0, 16'd0, 32'd0, ox_n, oy_n);
                        n_tag <= f_active ? f_tag : next_tag;
                        n_ox <= ox_n;
                        n_oy <= oy_n;
                        n_dst_ip <= p_src_ip;
                        n_dst_port <= p_src_port;
                        state <= S_SLOT;
                    end else begin
                        send(pack(MAGIC_RES, {10'd0, crop_n, 5'h01}, f_active ? f_fid : p_fid, rows_n, bad_n,
                                  h_n, w_n, sum_n, t0_n, cyc, cyc, 16'd0, 16'd0, 32'd0, ox_n, oy_n),
                             p_src_ip, p_src_port);
                    end
                end
            end
        end
    end
    S_SLOT: begin
        // claim the pending slot once it is free (the old result is emitted in this state)
        if (!q_valid) begin
            q_res <= n_res;
            q_tag <= n_tag;
            q_ox <= n_ox;
            q_oy <= n_oy;
            q_dst_ip <= n_dst_ip;
            q_dst_port <= n_dst_port;
            q_valid <= 1'b1;
            q_ready <= 1'b0;
            q_t <= cyc;
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
        f_trk_started <= 0;
        next_tag <= 0;
        pos_x <= 0;
        pos_y <= 0;
        q_valid <= 0;
        q_ready <= 0;
        r_pending <= 0;
        r_hdr_done <= 0;
        s_load <= 0;
        frames_done_reg <= 0;
        rows_bad_total_reg <= 0;
    end
end


endmodule

`resetall
