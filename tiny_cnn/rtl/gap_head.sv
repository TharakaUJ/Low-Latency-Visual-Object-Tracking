// gap_head.sv -- global-average-pool (as an integer sum + folded-in-average
// requant) + the final 32->2 FC head. Consumes L3's output tile from a
// normal fmap_pingpong consumer port (one deviation from the original plan,
// which sketched tapping L3's raw per-channel stream directly to skip one
// small fmap buffer -- adding that one buffer is negligible in area/latency
// and made this module far simpler to get right under time pressure, with
// no change to the measured throughput: this module's whole per-tile job
// takes well under 1024 cycles, so L0-L3 (not this module) remain the
// pipeline's bottleneck).
//
// This module has enormous slack against the ~1024-cycle/tile budget (its
// whole job is a handful of adds/MACs over just 32 channels), so it is
// implemented as a plain sequential FSM sharing ONE requant_pipe instance
// across all 32 GAP channels and both head outputs -- no per-op pipelining
// needed here, unlike the conv_layer stages.
//
// hw/hb ROMs are loaded from gen/tcnn_paths.svh's `TCNN_HW/`TCNN_HB literal
// string macros directly (there is only one gap_head instance, so no
// per-layer selection is needed, unlike conv_layer.sv) -- NOT via string
// parameters. See conv_layer.sv's header comment: Quartus Prime 25.1's
// synthesis elaborator unconditionally rejects a string parameter used as
// $readmemh's filename argument (error 10686), confirmed with an isolated
// repro; only a literal string token (or a macro expanding to one) works.
`include "tcnn_paths.svh"
module gap_head #(
    parameter int COUT_IN    = 32,   // L3's output channel count
    parameter int N_SPATIAL  = 16,   // L3's OH*OW (4x4)
    parameter int HEAD_COUT  = 2,
    parameter int GAP_MULT, GAP_SHIFT, GAP_OUT_ZP,
    parameter int HEAD_MULT0, HEAD_SHIFT0,
    parameter int HEAD_MULT1, HEAD_SHIFT1,
    parameter int LOGIT_ZP   = 123,
    parameter int TILE_TAG_W = 16
) (
    input  logic clk,
    input  logic rst_n,

    input  logic                          in_rd_ready,
    output logic                          in_rd_start,
    input  logic [TILE_TAG_W-1:0]         in_rd_tag,
    output logic [$clog2(N_SPATIAL)-1:0]  in_rd_addr,
    input  logic [COUT_IN*8-1:0]          in_rd_data,
    output logic                          in_rd_done,

    output logic                    res_valid,
    output logic [TILE_TAG_W-1:0]   res_tag,
    output logic [7:0]              res_logit0,
    output logic [7:0]              res_logit1
);
  logic signed [3:0] hw [HEAD_COUT*COUT_IN];
  logic [31:0]        hb [HEAD_COUT];
  initial begin
    $readmemh(`TCNN_HW, hw);
    $readmemh(`TCNN_HB, hb);
  end

  localparam int SUM_W = 24;
  logic signed [SUM_W-1:0] ssum [COUT_IN];
  logic [7:0]              view [COUT_IN];
  logic signed [7:0]       logit_r [HEAD_COUT];

  logic [$clog2(N_SPATIAL)-1:0] addr_r;
  logic                          addr_v1;

  typedef enum logic [3:0] {
    G_IDLE, G_SUM, G_SUM_DRAIN,
    G_GAP, G_GAP_WAIT,
    G_HEAD_MAC, G_HEAD_REQ, G_HEAD_WAIT,
    G_DONE
  } gstate_e;
  gstate_e st;

  logic [$clog2(COUT_IN>1?COUT_IN:2):0] ch_idx;   // shared loop index (channel for GAP, output for head)
  logic [$clog2(COUT_IN>1?COUT_IN:2):0] mac_idx;  // inner loop index for head MAC
  logic signed [31:0] head_acc;
  logic [TILE_TAG_W-1:0] tile_tag_r;

  // shared requant_pipe: used sequentially for 32 GAP channels then 2 head outputs
  logic                req_v_i;
  logic signed [31:0]  req_acc_i;
  logic signed [31:0]  req_mult_i;
  logic [5:0]          req_shift_i;
  logic signed [15:0]  req_zp_i;
  logic                req_v_o;
  logic [7:0]          req_out_o;

  requant_pipe #(.ACC_W(32), .TAG_W(1)) u_req (
      .clk(clk), .rst_n(rst_n),
      .valid_i(req_v_i), .acc_i(req_acc_i), .mult_i(req_mult_i),
      .shift_i(req_shift_i), .out_zp_i(req_zp_i), .tag_i(1'b0),
      .valid_o(req_v_o), .out_u8_o(req_out_o), .tag_o()
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st <= G_IDLE;
      in_rd_start <= 1'b0; in_rd_done <= 1'b0;
      res_valid <= 1'b0;
      addr_v1 <= 1'b0;
      req_v_i <= 1'b0;
    end else begin
      in_rd_start <= 1'b0;
      in_rd_done  <= 1'b0;
      res_valid   <= 1'b0;
      req_v_i     <= 1'b0;

      unique case (st)
        G_IDLE: begin
          if (in_rd_ready) begin
            in_rd_start <= 1'b1;
            tile_tag_r  <= in_rd_tag;
            in_rd_addr  <= '0;
            for (int c = 0; c < COUT_IN; c++) ssum[c] <= '0;
            addr_v1 <= 1'b0;
            st <= G_SUM;
          end
        end

        // present addresses 0..N_SPATIAL-1 one per cycle, accumulate the
        // (1-cycle-delayed) data for the PREVIOUS address each cycle
        G_SUM: begin
          if (addr_v1) begin
            for (int c = 0; c < COUT_IN; c++)
              ssum[c] <= ssum[c] + $signed({16'b0, in_rd_data[c*8 +: 8]});
          end
          addr_v1 <= 1'b1;
          if (in_rd_addr == N_SPATIAL-1) begin
            st <= G_SUM_DRAIN;
          end else begin
            in_rd_addr <= in_rd_addr + 1'b1;
          end
        end
        G_SUM_DRAIN: begin
          // one more cycle to accumulate the last address's data
          for (int c = 0; c < COUT_IN; c++)
            ssum[c] <= ssum[c] + $signed({16'b0, in_rd_data[c*8 +: 8]});
          in_rd_done <= 1'b1;   // release the L3 output bank now
          ch_idx <= '0;
          st <= G_GAP;
        end

        G_GAP: begin
          req_v_i     <= 1'b1;
          req_acc_i   <= ssum[ch_idx];
          req_mult_i  <= GAP_MULT;
          req_shift_i <= GAP_SHIFT[5:0];
          req_zp_i    <= 16'(GAP_OUT_ZP);
          st <= G_GAP_WAIT;
        end
        G_GAP_WAIT: begin
          if (req_v_o) begin
            view[ch_idx] <= req_out_o;
            if (ch_idx == COUT_IN-1) begin
              ch_idx <= '0;
              head_acc <= $signed(hb[0]);
              mac_idx <= '0;
              st <= G_HEAD_MAC;
            end else begin
              ch_idx <= ch_idx + 1'b1;
              st <= G_GAP;
            end
          end
        end

        // serial MAC over 32 channels for the current head output (ch_idx)
        G_HEAD_MAC: begin
          head_acc <= head_acc + $signed({16'b0, view[mac_idx]}) * $signed(hw[ch_idx*COUT_IN + mac_idx]);
          if (mac_idx == COUT_IN-1) st <= G_HEAD_REQ;
          else mac_idx <= mac_idx + 1'b1;
        end
        G_HEAD_REQ: begin
          req_v_i     <= 1'b1;
          req_acc_i   <= head_acc;
          req_mult_i  <= (ch_idx == 0) ? HEAD_MULT0  : HEAD_MULT1;
          req_shift_i <= (ch_idx == 0) ? HEAD_SHIFT0[5:0] : HEAD_SHIFT1[5:0];
          req_zp_i    <= 16'(LOGIT_ZP);
          st <= G_HEAD_WAIT;
        end
        G_HEAD_WAIT: begin
          if (req_v_o) begin
            logit_r[ch_idx] <= req_out_o;
            if (ch_idx == HEAD_COUT-1) begin
              st <= G_DONE;
            end else begin
              ch_idx   <= ch_idx + 1'b1;
              head_acc <= $signed(hb[ch_idx+1]);
              mac_idx  <= '0;
              st <= G_HEAD_MAC;
            end
          end
        end

        G_DONE: begin
          res_valid  <= 1'b1;
          res_tag    <= tile_tag_r;
          res_logit0 <= logit_r[0];
          res_logit1 <= logit_r[1];
          st <= G_IDLE;
        end
      endcase
    end
  end
endmodule
