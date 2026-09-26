// frame_player.sv -- replays an uploaded strip (STRIP_H x FRAME_W RGB, held
// in on-chip RAM written over Avalon) as NFRAMES full FRAME_W x FRAME_H
// frames: row r of frame f is strip row (r % STRIP_H). Streams one pixel
// per cycle whenever the downstream (tile_feeder) is ready. This is what
// lets the board-side throughput measurement bypass the slow JTAG UART
// link -- the frame data only has to be uploaded once.
module frame_player #(
    parameter int MAX_W = 640,
    parameter int MAX_STRIP_H = 48
) (
    input  logic clk,
    input  logic rst_n,

    // Avalon-side strip upload (word-at-a-time, address auto-increments by
    // the caller between writes)
    input  logic                 strip_wr_en,
    input  logic [$clog2(MAX_W*MAX_STRIP_H)-1:0] strip_wr_addr,
    input  logic [23:0]          strip_wr_data,

    // run control
    input  logic         start,       // pulse: begin playback
    input  logic [15:0]  frame_w,
    input  logic [15:0]  frame_h,
    input  logic [15:0]  strip_h,
    input  logic [15:0]  nframes,
    output logic         busy,
    output logic         done,        // pulses once, after the last pixel of the last frame

    // raster pixel stream out
    output logic          px_valid,
    output logic [23:0]   px_data,
    input  logic          px_ready,
    output logic          frame_first  // pulses with the first pixel of each frame
);
  logic [23:0] strip_mem [MAX_W*MAX_STRIP_H];

  always_ff @(posedge clk) begin
    if (strip_wr_en) strip_mem[strip_wr_addr] <= strip_wr_data;
  end

  logic [15:0] cur_w, cur_sh;
  logic [15:0] row, col;
  logic [15:0] frame_idx;
  logic [15:0] strip_row;   // row % strip_h, maintained incrementally

  typedef enum logic [1:0] {P_IDLE, P_RUN, P_DONE} pstate_e;
  pstate_e st;

  // ---- output skid register: strip_mem is read into px_data_q with a
  // real 1-cycle synchronous read (`px_data_q <= strip_mem[addr]`) instead
  // of the address-generator registers feeding a combinational
  // `assign px_data = strip_mem[...]`. Quartus Prime's RAM inference
  // requires a genuine registered read to map this (640*48-deep) array to
  // M9K; the combinational form left it uninferred, falling back to
  // hundreds of thousands of flip-flops and blowing the design's register
  // budget ("Cannot convert all sets of registers into RAM megafunctions",
  // error 276003 -- found via Gate P2). A new pixel is only fetched into
  // the skid register when it's empty or the consumer is draining it this
  // cycle (`can_advance`), which preserves the same valid/ready contract
  // under backpressure that the old combinational version had "for free".
  logic [23:0] px_data_q;
  logic        px_valid_q;
  logic        frame_first_q;
  logic        is_last_q;   // this skid-buffered pixel is the last of the whole run

  assign busy        = (st == P_RUN) || px_valid_q;
  assign px_valid     = px_valid_q;
  assign px_data       = px_data_q;
  assign frame_first  = frame_first_q;

  wire can_advance = !px_valid_q || px_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st <= P_IDLE; done <= 1'b0;
      row <= '0; col <= '0; strip_row <= '0; frame_idx <= '0;
      px_valid_q <= 1'b0; px_data_q <= '0; frame_first_q <= 1'b0; is_last_q <= 1'b0;
    end else begin
      done <= 1'b0;
      unique case (st)
        P_IDLE: begin
          if (start) begin
            cur_w <= frame_w; cur_sh <= strip_h;
            row <= '0; col <= '0; strip_row <= '0; frame_idx <= '0;
            st <= P_RUN;
          end
        end
        P_RUN: begin
          if (can_advance) begin
            // fetch the pixel at the CURRENT (row,col,strip_row) into the
            // skid register, then advance the address generator to the
            // next one -- exactly the same sequencing the old
            // combinational version had, just with the read moved behind
            // a register.
            px_data_q     <= strip_mem[strip_row*MAX_W + col];
            px_valid_q    <= 1'b1;
            frame_first_q <= (row == 0) && (col == 0);
            is_last_q     <= (col == cur_w-1) && (row == frame_h-1) && (frame_idx == nframes-1);
            if (col == cur_w-1) begin
              col <= '0;
              if (row == frame_h-1) begin
                row <= '0; strip_row <= '0;
                if (frame_idx == nframes-1) begin
                  st <= P_DONE;
                end else begin
                  frame_idx <= frame_idx + 1'b1;
                end
              end else begin
                row <= row + 1'b1;
                strip_row <= (strip_row == cur_sh-1) ? 16'd0 : strip_row + 1'b1;
              end
            end else begin
              col <= col + 1'b1;
            end
          end
        end
        P_DONE: begin
          // let the final skid-buffered pixel actually drain to the
          // consumer before signaling done -- not the cycle it was merely
          // fetched into the skid register (which may still be waiting on
          // px_ready).
          if (px_valid_q && px_ready) begin
            px_valid_q <= 1'b0;
            if (is_last_q) done <= 1'b1;
          end
          // A `start` pulse here must begin the NEXT run directly (same as
          // P_IDLE's handling), not just leave P_DONE for P_IDLE -- `start`
          // is only asserted for a single cycle by tcnn_avalon_slave, so
          // routing through P_IDLE first would consume that one pulse on
          // the state transition alone and then sit in P_IDLE forever,
          // never actually starting. Found via board bring-up: every other
          // `R` command silently produced zero pixels and the firmware's
          // STATUS.done poll spun to its limit before replying. Also drop
          // any still-draining last pixel -- by the time a new `start`
          // arrives the previous run's `done` has already been polled by
          // the host, so it is always fully drained already.
          if (start) begin
            cur_w <= frame_w; cur_sh <= strip_h;
            row <= '0; col <= '0; strip_row <= '0; frame_idx <= '0;
            px_valid_q <= 1'b0;
            st <= P_RUN;
          end
        end
      endcase
    end
  end
endmodule
