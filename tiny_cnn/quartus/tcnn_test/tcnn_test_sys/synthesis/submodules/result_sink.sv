// result_sink.sv -- consumes tcnn_core's result stream. Frame 0's results
// are stored into a result RAM at a FIXED pitch (band*PITCH+tcol, PITCH =
// MAX_W/16, independent of the runtime frame width) so the address never
// depends on a runtime value. Every later frame's results are compared
// against frame 0's stored values; any difference increments RES_MISMATCH
// -- this is what would catch corruption from a timing violation on real
// hardware (bit-exact in simulation says nothing about setup/hold margin).
//
// Also tracks: TILES_DONE, CYCLES (from `run_start` to the last result of
// the last frame), MIN_GAP/MAX_GAP (cycles between consecutive results,
// after the first 8 are discarded to let the pipeline reach steady state),
// FEED_STALL (informational, driven externally by tile_feeder/frame_player
// backpressure -- wired at the top level, not computed here).
module result_sink #(
    parameter int MAX_W = 640,
    parameter int TILE_TAG_W = 16
) (
    input  logic clk,
    input  logic rst_n,

    input  logic                  res_valid,
    input  logic [TILE_TAG_W-1:0] res_tag,     // {band, tcol}
    input  logic [7:0]            res_logit0,
    input  logic [7:0]            res_logit1,

    input  logic         run_start,     // pulse: reset counters, arm frame-0 capture
    input  logic [15:0]  tiles_per_frame,
    input  logic [15:0]  nframes,

    output logic [31:0]  cycles,
    output logic [31:0]  tiles_done,
    output logic [31:0]  res_mismatch,
    output logic [31:0]  min_gap,
    output logic [31:0]  max_gap,
    output logic          run_done,

    // read-back port (Avalon side)
    input  logic [15:0]  res_rd_addr,
    output logic [15:0]  res_rd_data    // {logit1, logit0}
);
  localparam int PITCH = MAX_W/16;
  localparam int RAM_DEPTH = 2048;

  logic [15:0] result_ram [RAM_DEPTH];

  logic [31:0] tiles_in_frame_ctr;
  logic [31:0] frame_ctr;
  logic [31:0] cyc_ctr;
  logic first8_skip;
  logic [3:0]  warm_ctr;
  logic [31:0] last_res_cyc;

  // Both reads are synchronous so the RAM maps to M9K (two copies, one per
  // read port). With asynchronous reads Quartus built a second 2048x16 copy
  // out of ~33k registers plus a 2048:1 read mux (~24k ALUTs). The
  // read-back port therefore has 1 cycle of latency, and the frame>0
  // compare is resolved one cycle after the result arrives.
  logic [$clog2(RAM_DEPTH)-1:0] wr_addr;
  logic [15:0] wr_word;
  logic        wr_en, cmp_v, cmp_v_r;
  logic [15:0] cmp_word_r, cmp_q;

  always_comb begin
    automatic logic [15:0] band = res_tag[TILE_TAG_W-1:$clog2(PITCH)];
    automatic logic [15:0] tcol = {{(16-$clog2(PITCH)){1'b0}}, res_tag[$clog2(PITCH)-1:0]};
    wr_addr = $clog2(RAM_DEPTH)'(band*PITCH + tcol);
    wr_word = {res_logit1, res_logit0};
    wr_en   = res_valid && (frame_ctr == 0);
    cmp_v   = res_valid && (frame_ctr != 0);
  end

  always_ff @(posedge clk) begin
    if (wr_en) result_ram[wr_addr] <= wr_word;
    cmp_q       <= result_ram[wr_addr];
    res_rd_data <= result_ram[res_rd_addr[$clog2(RAM_DEPTH)-1:0]];
    cmp_word_r  <= wr_word;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cycles <= '0; tiles_done <= '0; res_mismatch <= '0;
      min_gap <= 32'hFFFFFFFF; max_gap <= '0;
      run_done <= 1'b0;
      tiles_in_frame_ctr <= '0; frame_ctr <= '0; cyc_ctr <= '0;
      warm_ctr <= '0;
      cmp_v_r <= 1'b0;
    end else begin
      run_done <= 1'b0;
      cyc_ctr <= cyc_ctr + 1'b1;

      cmp_v_r <= cmp_v;
      if (cmp_v_r && cmp_q !== cmp_word_r) res_mismatch <= res_mismatch + 1'b1;

      if (run_start) begin
        cycles <= '0; tiles_done <= '0; res_mismatch <= '0;
        min_gap <= 32'hFFFFFFFF; max_gap <= '0;
        tiles_in_frame_ctr <= '0; frame_ctr <= '0; cyc_ctr <= '0;
        warm_ctr <= '0;
        cmp_v_r <= 1'b0;
      end

      if (res_valid) begin
        tiles_done <= tiles_done + 1'b1;
        cycles     <= cyc_ctr;

        if (warm_ctr < 8) warm_ctr <= warm_ctr + 4'd1;
        else begin
          automatic logic [31:0] gap = cyc_ctr - last_res_cyc;
          if (gap < min_gap) min_gap <= gap;
          if (gap > max_gap) max_gap <= gap;
        end
        last_res_cyc <= cyc_ctr;

        if (tiles_in_frame_ctr == tiles_per_frame-1) begin
          tiles_in_frame_ctr <= '0;
          if (frame_ctr == nframes-1) begin
            run_done <= 1'b1;
          end else begin
            frame_ctr <= frame_ctr + 1'b1;
          end
        end else begin
          tiles_in_frame_ctr <= tiles_in_frame_ctr + 1'b1;
        end
      end
    end
  end
endmodule
