// tcnn_avalon_slave.sv -- Avalon-MM front end for the layer-pipelined
// tiny-cnn accelerator. Wires frame_player -> tile_feeder -> tcnn_core ->
// result_sink directly (rather than reusing tcnn_top_sim) so this module can
// also expose player/feeder handshake signals for STATUS.busy and
// FEED_STALL, which tcnn_top_sim does not surface.
//
// All accesses are single-cycle (avs_waitrequest tied low); reads are
// combinational off the register file / result RAM, matching
// fpga_cnn_pipeline/rtl/cnn_avalon_slave.sv's convention.
module tcnn_avalon_slave #(
    parameter int MAX_W = 640,
    parameter int MAX_STRIP_H = 48,
    parameter string GEN_DIR = "gen/",
    parameter int TILE_TAG_W = 16
) (
    input  logic        clk,
    input  logic        rst_n,

    // Avalon-MM slave, 32-bit data, word-addressed (19 registers -> 5-bit address)
    input  logic [4:0]  avs_address,
    input  logic        avs_read,
    output logic [31:0] avs_readdata,
    input  logic        avs_write,
    input  logic [31:0] avs_writedata,
    output logic        avs_waitrequest
);
  assign avs_waitrequest = 1'b0;

  localparam logic [31:0] ID_VAL      = 32'h5443_4E31;  // "TCN1"
  localparam logic [31:0] VERSION_VAL = 32'h0000_000A;  // [7:0]: tile interval code, 1024 -> 0x0A

  // ---- register file ----
  logic [31:0] scratch_reg;
  logic [15:0] frame_w_reg, frame_h_reg, strip_h_reg, nframes_reg;
  logic [$clog2(MAX_W*MAX_STRIP_H)-1:0] strip_addr_reg;
  logic [15:0] res_addr_reg;
  logic start_pulse, soft_reset_pulse;
  logic strip_wr_en;
  logic [23:0] strip_wr_data;
  logic [$clog2(MAX_W*MAX_STRIP_H)-1:0] strip_wr_addr_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      scratch_reg <= '0;
      frame_w_reg <= 16'd640; frame_h_reg <= 16'd480;
      strip_h_reg <= 16'd48;  nframes_reg <= 16'd1;
      strip_addr_reg <= '0; res_addr_reg <= '0;
      start_pulse <= 1'b0; soft_reset_pulse <= 1'b0;
      strip_wr_en <= 1'b0; strip_wr_data <= '0; strip_wr_addr_r <= '0;
    end else begin
      start_pulse <= 1'b0;
      soft_reset_pulse <= 1'b0;
      strip_wr_en <= 1'b0;
      if (avs_write) begin
        unique case (avs_address)
          5'd2:  scratch_reg <= avs_writedata;
          5'd3: begin
            start_pulse      <= avs_writedata[0];
            soft_reset_pulse <= avs_writedata[1];
          end
          5'd5:  frame_w_reg <= avs_writedata[15:0];
          5'd6:  frame_h_reg <= avs_writedata[15:0];
          5'd7:  strip_h_reg <= avs_writedata[15:0];
          5'd8:  nframes_reg <= avs_writedata[15:0];
          5'd9:  strip_addr_reg <= avs_writedata[$clog2(MAX_W*MAX_STRIP_H)-1:0];
          5'd10: begin
            strip_wr_en     <= 1'b1;
            strip_wr_data   <= avs_writedata[23:0];
            // capture the address BEFORE it auto-increments: strip_wr_en
            // (and hence the actual RAM write) only takes effect one cycle
            // from now, so feeding frame_player the (already-incremented)
            // strip_addr_reg directly would write every word one slot past
            // where it belongs. Found via Gate S1 (every uploaded word
            // landed shifted, corrupting the whole run self-consistently
            // since both replayed frames used the same shifted data).
            strip_wr_addr_r <= strip_addr_reg;
            strip_addr_reg  <= strip_addr_reg + 1'b1;   // auto-increment
          end
          5'd11: res_addr_reg <= avs_writedata[15:0];
          default: ;
        endcase
      end
    end
  end

  // ---- datapath: frame_player -> tile_feeder -> tcnn_core -> result_sink ----
  logic player_busy, player_done;
  logic px_valid, px_ready, frame_first;
  logic [23:0] px_data;

  frame_player #(.MAX_W(MAX_W), .MAX_STRIP_H(MAX_STRIP_H)) u_player (
      .clk(clk), .rst_n(rst_n),
      .strip_wr_en(strip_wr_en), .strip_wr_addr(strip_wr_addr_r), .strip_wr_data(strip_wr_data),
      .start(start_pulse), .frame_w(frame_w_reg), .frame_h(frame_h_reg),
      .strip_h(strip_h_reg), .nframes(nframes_reg),
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
      .frame_w(frame_w_reg), .frame_h(frame_h_reg), .frame_first(frame_first), .frame_last_row_tile(1'b0),
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
  assign tiles_per_frame = (frame_w_reg/16) * (frame_h_reg/16);

  logic [31:0] cycles, tiles_done, res_mismatch, min_gap, max_gap;
  logic run_done;
  logic [15:0] res_rd_data;

  result_sink #(.MAX_W(MAX_W), .TILE_TAG_W(TILE_TAG_W)) u_sink (
      .clk(clk), .rst_n(rst_n),
      .res_valid(res_valid), .res_tag(res_tag), .res_logit0(res_logit0), .res_logit1(res_logit1),
      .run_start(start_pulse), .tiles_per_frame(tiles_per_frame), .nframes(nframes_reg),
      .cycles(cycles), .tiles_done(tiles_done), .res_mismatch(res_mismatch),
      .min_gap(min_gap), .max_gap(max_gap), .run_done(run_done),
      .res_rd_addr(res_addr_reg), .res_rd_data(res_rd_data)
  );

  // ---- FEED_STALL: cycles the player had a pixel ready but the feeder
  // wasn't ready for it (informational -- see the plan's register map) ----
  logic [31:0] feed_stall_ctr;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) feed_stall_ctr <= '0;
    else if (start_pulse) feed_stall_ctr <= '0;
    else if (px_valid && !px_ready) feed_stall_ctr <= feed_stall_ctr + 1'b1;
  end

  // busy/done latched across the run (player_busy alone drops as soon as the
  // last pixel is fed, well before the pipeline has drained and result_sink
  // has actually asserted run_done)
  logic run_done_seen_since_start;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) run_done_seen_since_start <= 1'b0;
    else if (start_pulse) run_done_seen_since_start <= 1'b0;
    else if (run_done) run_done_seen_since_start <= 1'b1;
  end

  // ---- STATUS ----
  logic [31:0] status_word;
  always_comb begin
    status_word     = 32'h0;
    status_word[0]   = player_busy || !run_done_seen_since_start;
    status_word[1]   = run_done_seen_since_start;
  end

  // ---- reads ----
  always_comb begin
    avs_readdata = 32'h0;
    unique case (avs_address)
      5'd0:  avs_readdata = ID_VAL;
      5'd1:  avs_readdata = VERSION_VAL;
      5'd2:  avs_readdata = scratch_reg;
      5'd4:  avs_readdata = status_word;
      5'd5:  avs_readdata = {16'h0, frame_w_reg};
      5'd6:  avs_readdata = {16'h0, frame_h_reg};
      5'd7:  avs_readdata = {16'h0, strip_h_reg};
      5'd8:  avs_readdata = {16'h0, nframes_reg};
      5'd12: avs_readdata = {16'h0, res_rd_data};
      5'd13: avs_readdata = cycles;
      5'd14: avs_readdata = tiles_done;
      5'd15: avs_readdata = res_mismatch;
      5'd16: avs_readdata = min_gap;
      5'd17: avs_readdata = max_gap;
      5'd18: avs_readdata = feed_stall_ctr;
      default: avs_readdata = 32'h0;
    endcase
  end
endmodule
