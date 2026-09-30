// tcnn_top_sim.sv -- wires frame_player -> tile_feeder -> tcnn_core ->
// result_sink for simulation (Gate F1) and as the reference for
// tcnn_avalon_slave's internal wiring. Not the Avalon-facing top (that's
// tcnn_avalon_slave.sv); this is the pure datapath.
module tcnn_top_sim #(
    parameter int MAX_W = 640,
    parameter int MAX_STRIP_H = 48,
    parameter string GEN_DIR = "gen/",
    parameter int TILE_TAG_W = 16
) (
    input  logic clk,
    input  logic rst_n,

    input  logic                 strip_wr_en,
    input  logic [$clog2(MAX_W*MAX_STRIP_H)-1:0] strip_wr_addr,
    input  logic [23:0]          strip_wr_data,

    input  logic         start,
    input  logic [15:0]  frame_w,
    input  logic [15:0]  frame_h,
    input  logic [15:0]  strip_h,
    input  logic [15:0]  nframes,

    output logic [31:0]  cycles,
    output logic [31:0]  tiles_done,
    output logic [31:0]  res_mismatch,
    output logic [31:0]  min_gap,
    output logic [31:0]  max_gap,
    output logic         run_done,

    input  logic [15:0]  res_rd_addr,
    output logic [15:0]  res_rd_data
);
  logic player_busy, player_done;
  logic px_valid, px_ready, frame_first;
  logic [23:0] px_data;

  frame_player #(.MAX_W(MAX_W), .MAX_STRIP_H(MAX_STRIP_H)) u_player (
      .clk(clk), .rst_n(rst_n),
      .strip_wr_en(strip_wr_en), .strip_wr_addr(strip_wr_addr), .strip_wr_data(strip_wr_data),
      .start(start), .frame_w(frame_w), .frame_h(frame_h), .strip_h(strip_h), .nframes(nframes),
      .busy(player_busy), .done(player_done),
      .px_valid(px_valid), .px_data(px_data), .px_ready(px_ready), .frame_first(frame_first)
  );

  logic l0in_wr_ready, l0in_wr_start;
  logic [TILE_TAG_W-1:0] l0in_wr_tag;
  logic l0in_wr_en;
  logic [$clog2(16*16)-1:0] l0in_wr_addr;
  logic [3*8-1:0] l0in_wr_data;
  logic l0in_wr_done;

  tile_feeder #(.MAX_W(MAX_W), .TILE_TAG_W(TILE_TAG_W)) u_feeder (
      .clk(clk), .rst_n(rst_n),
      .px_ready(px_ready), .px_valid(px_valid), .px_data(px_data),
      .frame_w(frame_w), .frame_h(frame_h), .frame_first(frame_first), .frame_last_row_tile(1'b0),
      .l0in_wr_ready(l0in_wr_ready), .l0in_wr_start(l0in_wr_start), .l0in_wr_tag(l0in_wr_tag),
      .l0in_wr_en(l0in_wr_en), .l0in_wr_addr(l0in_wr_addr), .l0in_wr_data(l0in_wr_data), .l0in_wr_done(l0in_wr_done)
  );

  logic res_valid;
  logic [TILE_TAG_W-1:0] res_tag;
  logic [7:0] res_logit0, res_logit1;
  logic [31:0] dbg_tiles_committed;

  tcnn_core #(.GEN_DIR(GEN_DIR), .TILE_TAG_W(TILE_TAG_W)) u_core (
      .clk(clk), .rst_n(rst_n),
      .l0in_wr_ready(l0in_wr_ready), .l0in_wr_start(l0in_wr_start), .l0in_wr_tag(l0in_wr_tag),
      .l0in_wr_en(l0in_wr_en), .l0in_wr_addr(l0in_wr_addr), .l0in_wr_data(l0in_wr_data), .l0in_wr_done(l0in_wr_done),
      .res_valid(res_valid), .res_tag(res_tag), .res_logit0(res_logit0), .res_logit1(res_logit1),
      .dbg_tiles_committed(dbg_tiles_committed)
  );

  logic [15:0] tiles_per_frame;
  assign tiles_per_frame = (frame_w/16) * (frame_h/16);

  result_sink #(.MAX_W(MAX_W), .TILE_TAG_W(TILE_TAG_W)) u_sink (
      .clk(clk), .rst_n(rst_n),
      .res_valid(res_valid), .res_tag(res_tag), .res_logit0(res_logit0), .res_logit1(res_logit1),
      .run_start(start), .tiles_per_frame(tiles_per_frame), .nframes(nframes),
      .cycles(cycles), .tiles_done(tiles_done), .res_mismatch(res_mismatch),
      .min_gap(min_gap), .max_gap(max_gap), .run_done(run_done),
      .res_rd_addr(res_rd_addr), .res_rd_data(res_rd_data)
  );
endmodule
