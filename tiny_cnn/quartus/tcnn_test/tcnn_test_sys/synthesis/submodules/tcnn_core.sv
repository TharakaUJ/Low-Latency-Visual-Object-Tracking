// tcnn_core.sv -- the whole layer-pipelined Tiny-CNN: an L0-input fmap, the
// 4 conv_layer stages with a fmap_pingpong between every pair (including
// after L3, feeding gap_head -- see gap_head.sv's header for why), and
// gap_head. Exposes the L0-input producer port and the result stream.
//
// All parameters (CIN/COUT/shapes/strides/CIN_PAR/NPASS and every requant
// constant) are literal values baked in by this file, generated to match
// gen/tcnn.json -- see gen_tcnn.py and docs/architecture.md. Regenerating
// with different --cin-par values means regenerating this file's constants
// too (not yet auto-generated as SV; done by hand from gen/tcnn.json for
// this pass -- see docs/progress_log.md).
//
// ROM file paths come from gen/tcnn_paths.svh's per-file `TCNN_* literal
// string macros (not from run-time concatenation of the GEN_DIR parameter
// below) -- Quartus Prime's synthesis elaborator rejects a concatenation
// expression ({GEN_DIR,"w_L0.hex"}) bound to a string parameter port
// ("has an aggregate value"), even though Verilator accepts it (found via
// Gate P2). GEN_DIR is kept as a parameter for interface compatibility with
// tcnn_avalon_slave.sv/tcnn_top_sim.sv, but is otherwise unused here.
`include "tcnn_paths.svh"
module tcnn_core #(
    parameter string GEN_DIR = "gen/",
    parameter int TILE_TAG_W = 16
) (
    input  logic clk,
    input  logic rst_n,

    // L0 input producer port (from tile_feeder)
    output logic                  l0in_wr_ready,
    input  logic                  l0in_wr_start,
    input  logic [TILE_TAG_W-1:0] l0in_wr_tag,
    input  logic                  l0in_wr_en,
    input  logic [$clog2(16*16)-1:0] l0in_wr_addr,
    input  logic [3*8-1:0]        l0in_wr_data,
    input  logic                  l0in_wr_done,

    // result stream (from gap_head)
    output logic                  res_valid,
    output logic [TILE_TAG_W-1:0] res_tag,
    output logic [7:0]            res_logit0,
    output logic [7:0]            res_logit1,

    // debug counters
    output logic [31:0]           dbg_tiles_committed
);
  localparam int GAP_MULT   = 1140694085;
  localparam int GAP_SHIFT  = 33;
  localparam int HEAD_MULT0 = 1151030682;
  localparam int HEAD_SHIFT0 = 33;
  localparam int HEAD_MULT1 = 1209549403;
  localparam int HEAD_SHIFT1 = 33;
  localparam int LOGIT_ZP   = 123;

  // ---- fmap L0in (tile_feeder -> L0) ----
  logic l0in_rd_ready, l0in_rd_start;
  logic [TILE_TAG_W-1:0] l0in_rd_tag;
  logic [$clog2(16*16)-1:0] l0in_rd_addr;
  logic [3*8-1:0] l0in_rd_data;
  logic l0in_rd_done;

  fmap_pingpong #(.WORD_W(3*8), .DEPTH(16*16), .TAG_W(TILE_TAG_W)) u_fmap_l0in (
      .clk(clk), .rst_n(rst_n),
      .wr_ready(l0in_wr_ready), .wr_start(l0in_wr_start), .wr_tag(l0in_wr_tag),
      .wr_en(l0in_wr_en), .wr_addr(l0in_wr_addr), .wr_data(l0in_wr_data), .wr_done(l0in_wr_done),
      .rd_ready(l0in_rd_ready), .rd_start(l0in_rd_start), .rd_tag(l0in_rd_tag),
      .rd_addr(l0in_rd_addr), .rd_data(l0in_rd_data), .rd_done(l0in_rd_done)
  );

  // ---- L0: 3->16, 16x16->8x8, stride 2, CIN_PAR=3, NPASS=1 ----
  logic l1in_wr_ready, l1in_wr_start;
  logic [TILE_TAG_W-1:0] l1in_wr_tag;
  logic l1in_wr_en;
  logic [$clog2(8*8)-1:0] l1in_wr_addr;
  logic [16*8-1:0] l1in_wr_data;
  logic l1in_wr_done;

  conv_layer #(
      .CIN(3), .COUT(16), .IN_HW(16), .OUT_HW(8), .STRIDE(2), .PAD(1),
      .CIN_PAR(3), .NPASS(1),
      .LAYER(0),
      .OUT_ZP(0), .TILE_TAG_W(TILE_TAG_W)
  ) u_l0 (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(l0in_rd_ready), .in_rd_start(l0in_rd_start), .in_rd_tag(l0in_rd_tag),
      .in_rd_addr(l0in_rd_addr), .in_rd_data(l0in_rd_data), .in_rd_done(l0in_rd_done),
      .out_wr_ready(l1in_wr_ready), .out_wr_start(l1in_wr_start), .out_wr_tag(l1in_wr_tag),
      .out_wr_en(l1in_wr_en), .out_wr_addr(l1in_wr_addr), .out_wr_data(l1in_wr_data), .out_wr_done(l1in_wr_done)
  );

  // ---- fmap L1in (L0 -> L1) ----
  logic l1in_rd_ready, l1in_rd_start;
  logic [TILE_TAG_W-1:0] l1in_rd_tag;
  logic [$clog2(8*8)-1:0] l1in_rd_addr;
  logic [16*8-1:0] l1in_rd_data;
  logic l1in_rd_done;

  fmap_pingpong #(.WORD_W(16*8), .DEPTH(8*8), .TAG_W(TILE_TAG_W)) u_fmap_l1in (
      .clk(clk), .rst_n(rst_n),
      .wr_ready(l1in_wr_ready), .wr_start(l1in_wr_start), .wr_tag(l1in_wr_tag),
      .wr_en(l1in_wr_en), .wr_addr(l1in_wr_addr), .wr_data(l1in_wr_data), .wr_done(l1in_wr_done),
      .rd_ready(l1in_rd_ready), .rd_start(l1in_rd_start), .rd_tag(l1in_rd_tag),
      .rd_addr(l1in_rd_addr), .rd_data(l1in_rd_data), .rd_done(l1in_rd_done)
  );

  // ---- L1: 16->16, 8x8->8x8, stride 1, CIN_PAR=16, NPASS=1 ----
  logic l2in_wr_ready, l2in_wr_start;
  logic [TILE_TAG_W-1:0] l2in_wr_tag;
  logic l2in_wr_en;
  logic [$clog2(8*8)-1:0] l2in_wr_addr;
  logic [16*8-1:0] l2in_wr_data;
  logic l2in_wr_done;

  conv_layer #(
      .CIN(16), .COUT(16), .IN_HW(8), .OUT_HW(8), .STRIDE(1), .PAD(1),
      .CIN_PAR(16), .NPASS(1),
      .LAYER(1),
      .OUT_ZP(0), .TILE_TAG_W(TILE_TAG_W)
  ) u_l1 (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(l1in_rd_ready), .in_rd_start(l1in_rd_start), .in_rd_tag(l1in_rd_tag),
      .in_rd_addr(l1in_rd_addr), .in_rd_data(l1in_rd_data), .in_rd_done(l1in_rd_done),
      .out_wr_ready(l2in_wr_ready), .out_wr_start(l2in_wr_start), .out_wr_tag(l2in_wr_tag),
      .out_wr_en(l2in_wr_en), .out_wr_addr(l2in_wr_addr), .out_wr_data(l2in_wr_data), .out_wr_done(l2in_wr_done)
  );

  // ---- fmap L2in (L1 -> L2) ----
  logic l2in_rd_ready, l2in_rd_start;
  logic [TILE_TAG_W-1:0] l2in_rd_tag;
  logic [$clog2(8*8)-1:0] l2in_rd_addr;
  logic [16*8-1:0] l2in_rd_data;
  logic l2in_rd_done;

  fmap_pingpong #(.WORD_W(16*8), .DEPTH(8*8), .TAG_W(TILE_TAG_W)) u_fmap_l2in (
      .clk(clk), .rst_n(rst_n),
      .wr_ready(l2in_wr_ready), .wr_start(l2in_wr_start), .wr_tag(l2in_wr_tag),
      .wr_en(l2in_wr_en), .wr_addr(l2in_wr_addr), .wr_data(l2in_wr_data), .wr_done(l2in_wr_done),
      .rd_ready(l2in_rd_ready), .rd_start(l2in_rd_start), .rd_tag(l2in_rd_tag),
      .rd_addr(l2in_rd_addr), .rd_data(l2in_rd_data), .rd_done(l2in_rd_done)
  );

  // ---- L2: 16->32, 8x8->4x4, stride 2, CIN_PAR=8, NPASS=2 ----
  logic l3in_wr_ready, l3in_wr_start;
  logic [TILE_TAG_W-1:0] l3in_wr_tag;
  logic l3in_wr_en;
  logic [$clog2(4*4)-1:0] l3in_wr_addr;
  logic [32*8-1:0] l3in_wr_data;
  logic l3in_wr_done;

  conv_layer #(
      .CIN(16), .COUT(32), .IN_HW(8), .OUT_HW(4), .STRIDE(2), .PAD(1),
      .CIN_PAR(8), .NPASS(2),
      .LAYER(2),
      .OUT_ZP(0), .TILE_TAG_W(TILE_TAG_W)
  ) u_l2 (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(l2in_rd_ready), .in_rd_start(l2in_rd_start), .in_rd_tag(l2in_rd_tag),
      .in_rd_addr(l2in_rd_addr), .in_rd_data(l2in_rd_data), .in_rd_done(l2in_rd_done),
      .out_wr_ready(l3in_wr_ready), .out_wr_start(l3in_wr_start), .out_wr_tag(l3in_wr_tag),
      .out_wr_en(l3in_wr_en), .out_wr_addr(l3in_wr_addr), .out_wr_data(l3in_wr_data), .out_wr_done(l3in_wr_done)
  );

  // ---- fmap L3in (L2 -> L3) ----
  logic l3in_rd_ready, l3in_rd_start;
  logic [TILE_TAG_W-1:0] l3in_rd_tag;
  logic [$clog2(4*4)-1:0] l3in_rd_addr;
  logic [32*8-1:0] l3in_rd_data;
  logic l3in_rd_done;

  fmap_pingpong #(.WORD_W(32*8), .DEPTH(4*4), .TAG_W(TILE_TAG_W)) u_fmap_l3in (
      .clk(clk), .rst_n(rst_n),
      .wr_ready(l3in_wr_ready), .wr_start(l3in_wr_start), .wr_tag(l3in_wr_tag),
      .wr_en(l3in_wr_en), .wr_addr(l3in_wr_addr), .wr_data(l3in_wr_data), .wr_done(l3in_wr_done),
      .rd_ready(l3in_rd_ready), .rd_start(l3in_rd_start), .rd_tag(l3in_rd_tag),
      .rd_addr(l3in_rd_addr), .rd_data(l3in_rd_data), .rd_done(l3in_rd_done)
  );

  // ---- L3: 32->32, 4x4->4x4, stride 1, CIN_PAR=16, NPASS=2 ----
  logic l3out_wr_ready, l3out_wr_start;
  logic [TILE_TAG_W-1:0] l3out_wr_tag;
  logic l3out_wr_en;
  logic [$clog2(4*4)-1:0] l3out_wr_addr;
  logic [32*8-1:0] l3out_wr_data;
  logic l3out_wr_done;

  conv_layer #(
      .CIN(32), .COUT(32), .IN_HW(4), .OUT_HW(4), .STRIDE(1), .PAD(1),
      .CIN_PAR(16), .NPASS(2),
      .LAYER(3),
      .OUT_ZP(0), .TILE_TAG_W(TILE_TAG_W)
  ) u_l3 (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(l3in_rd_ready), .in_rd_start(l3in_rd_start), .in_rd_tag(l3in_rd_tag),
      .in_rd_addr(l3in_rd_addr), .in_rd_data(l3in_rd_data), .in_rd_done(l3in_rd_done),
      .out_wr_ready(l3out_wr_ready), .out_wr_start(l3out_wr_start), .out_wr_tag(l3out_wr_tag),
      .out_wr_en(l3out_wr_en), .out_wr_addr(l3out_wr_addr), .out_wr_data(l3out_wr_data), .out_wr_done(l3out_wr_done)
  );

  // ---- fmap L3out (L3 -> gap_head) ----
  logic l3out_rd_ready, l3out_rd_start;
  logic [TILE_TAG_W-1:0] l3out_rd_tag;
  logic [$clog2(4*4)-1:0] l3out_rd_addr;
  logic [32*8-1:0] l3out_rd_data;
  logic l3out_rd_done;

  fmap_pingpong #(.WORD_W(32*8), .DEPTH(4*4), .TAG_W(TILE_TAG_W)) u_fmap_l3out (
      .clk(clk), .rst_n(rst_n),
      .wr_ready(l3out_wr_ready), .wr_start(l3out_wr_start), .wr_tag(l3out_wr_tag),
      .wr_en(l3out_wr_en), .wr_addr(l3out_wr_addr), .wr_data(l3out_wr_data), .wr_done(l3out_wr_done),
      .rd_ready(l3out_rd_ready), .rd_start(l3out_rd_start), .rd_tag(l3out_rd_tag),
      .rd_addr(l3out_rd_addr), .rd_data(l3out_rd_data), .rd_done(l3out_rd_done)
  );

  gap_head #(
      .COUT_IN(32), .N_SPATIAL(16), .HEAD_COUT(2),
      .GAP_MULT(GAP_MULT), .GAP_SHIFT(GAP_SHIFT), .GAP_OUT_ZP(0),
            .HEAD_MULT0(HEAD_MULT0), .HEAD_SHIFT0(HEAD_SHIFT0),
      .HEAD_MULT1(HEAD_MULT1), .HEAD_SHIFT1(HEAD_SHIFT1),
      .LOGIT_ZP(LOGIT_ZP), .TILE_TAG_W(TILE_TAG_W)
  ) u_gap_head (
      .clk(clk), .rst_n(rst_n),
      .in_rd_ready(l3out_rd_ready), .in_rd_start(l3out_rd_start), .in_rd_tag(l3out_rd_tag),
      .in_rd_addr(l3out_rd_addr), .in_rd_data(l3out_rd_data), .in_rd_done(l3out_rd_done),
      .res_valid(res_valid), .res_tag(res_tag), .res_logit0(res_logit0), .res_logit1(res_logit1)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) dbg_tiles_committed <= '0;
    else if (res_valid) dbg_tiles_committed <= dbg_tiles_committed + 1'b1;
  end
endmodule
