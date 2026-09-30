// conv_layer.sv -- one streaming, layer-pipelined 3x3 conv stage. Reads its
// tile from an upstream fmap_pingpong (consumer port), writes its result
// tile to a downstream fmap_pingpong (producer port). Runs concurrently with
// every other layer, each on its own tile, handshaking only through the
// fmap_pingpong ping-pong buffers between them.
//
// Per-tile schedule (see docs/implementation_plan.md):
//   - a ~7-cycle warmup gathers output-pixel (0,0)'s 3x3xCIN window
//   - then, for each output pixel, gather the NEXT pixel's window while the
//     ISSUER spends OPS_PER_PIX = (COUT/COUT_PAR)*NPASS cycles on the
//     CURRENT pixel. Each issue cycle feeds COUT_PAR output channels at once
//     (one CIN_PAR*9-lane MAC group per channel, all sharing the same
//     activation slice). Gather reads two taps per cycle through the
//     upstream buffer's two read ports: 5 address cycles + 1-cycle read
//     latency = 6 cycles, inside the smallest per-pixel issue budget (8).
//     The FSM does not stall for gather, so a simulation assertion below
//     checks that the window is complete whenever it is consumed.
//   - issue order per pixel is PASS-MAJOR, GROUP-MINOR (p=icnt/G,
//     g=icnt%G, G=COUT/COUT_PAR); sub-lane s handles channel co=s*G+g.
//     Consecutive ops for the same channel are G cycles apart, and the
//     per-channel accumulate (acc_mem[g] <= acc_mem[g] + sum) is a
//     single-cycle read-modify-write -- this is the fix for the old design's
//     B19 ("acc <= acc + mac_sum ... true sequential dependency").
//   - bias/mult/shift for the op in flight ride through the adder_tree's own
//     tag bus (rather than a hand-timed parallel delay chain), so they
//     arrive at the accumulate/requant stage automatically aligned with the
//     sum they belong to, however deep the adder tree's pipeline is.
//
// Timing rules honored: the only feedback loop is acc_mem's single add;
// every mux on a value that feeds a multiplier is registered first (win
// slice + ROM word are both captured into flops one cycle after being
// selected, *before* the multiply, matching the ROM's own 1-cycle latency);
// the adder tree itself registers every 2 combinational levels.
//
// ROM files are selected by the LAYER parameter (0..3) via a generate-if
// below, using gen/tcnn_paths.svh's per-file `TCNN_* literal string macros
// directly in each $readmemh call -- NOT via string parameters. Quartus
// Prime 25.1's synthesis elaborator unconditionally rejects ANY string
// parameter used as $readmemh's filename argument ("has an aggregate
// value", error 10686). Only a literal string token (or a macro that
// expands to one) works. Each sub-lane loads its own full copy of the
// weight ROM (same file) so every sub-lane has its own read port.
`include "tcnn_paths.svh"
module conv_layer #(
    parameter int CIN, COUT, IN_HW, OUT_HW, STRIDE, PAD = 1,
    parameter int CIN_PAR, NPASS,
    parameter int COUT_PAR = 1,  // output channels issued per cycle
    parameter int LAYER = 0,     // selects which gen/*_L<LAYER>.hex ROMs to load (0..3)
    parameter int OUT_ZP  = 0,
    parameter int TILE_TAG_W = 16,
    parameter int N_DSP_LANES = CIN_PAR * 9 * COUT_PAR  // lanes [0, N_DSP_LANES) use embedded multipliers, the rest LEs
) (
    input  logic clk,
    input  logic rst_n,

    // consumer port into the upstream fmap_pingpong
    input  logic                          in_rd_ready,
    output logic                          in_rd_start,
    input  logic [TILE_TAG_W-1:0]         in_rd_tag,
    output logic [$clog2(IN_HW*IN_HW)-1:0] in_rd_addr,
    input  logic [CIN*8-1:0]              in_rd_data,
    output logic [$clog2(IN_HW*IN_HW)-1:0] in_rd_addr2,
    input  logic [CIN*8-1:0]              in_rd_data2,
    output logic                          in_rd_done,

    // producer port into the downstream fmap_pingpong
    input  logic                          out_wr_ready,
    output logic                          out_wr_start,
    output logic [TILE_TAG_W-1:0]         out_wr_tag,
    output logic                          out_wr_en,
    output logic [$clog2(OUT_HW*OUT_HW)-1:0] out_wr_addr,
    output logic [COUT*8-1:0]             out_wr_data,
    output logic                          out_wr_done
);
  localparam int G           = COUT / COUT_PAR;
  localparam int OPS_PER_PIX = G * NPASS;
  localparam int NPIX        = OUT_HW * OUT_HW;
  localparam int IN_AW       = $clog2(IN_HW*IN_HW > 1 ? IN_HW*IN_HW : 2);
  localparam int OUT_AW      = $clog2(NPIX > 1 ? NPIX : 2);
  localparam int CO_W        = $clog2(COUT > 1 ? COUT : 2);
  localparam int G_W         = $clog2(G > 1 ? G : 2);
  localparam int ROM_WBITS   = CIN_PAR * 9 * 4;
  localparam int PROD_W      = 12;   // uint8 x int4: -2040..1785
  localparam int SUM_W       = PROD_W + $clog2(CIN_PAR * 9);
  localparam int GATHER_LAST = 5;    // phases 0..4 present 2 taps each, 1..5 capture

  // synthesis translate_off
  initial begin
    if (COUT % COUT_PAR != 0) $fatal(1, "COUT=%0d not divisible by COUT_PAR=%0d", COUT, COUT_PAR);
    if (OPS_PER_PIX < GATHER_LAST + 2)
      $fatal(1, "per-pixel issue budget %0d too short for a %0d-cycle gather", OPS_PER_PIX, GATHER_LAST + 1);
  end
  // synthesis translate_on

  // ================= gather (fills win_next one output-pixel ahead) ======
  logic [7:0] win_cur  [0:8][0:CIN-1];
  logic [7:0] win_next [0:8][0:CIN-1];

  logic        gathering;
  logic [3:0]  gphase;
  logic [OUT_AW-1:0] goy, gox;
  logic [OUT_AW-1:0] gidx;    // next pixel index to gather (NPIX == "nothing left")
  logic        gather_done_pulse;

  // input address of tap `tap` of output pixel (oy,ox); in_range=0 for
  // padding taps and for tap >= 9
  function automatic logic [IN_AW:0] tap_addr(input int tap,
                                               input logic [OUT_AW-1:0] oy, ox);
    automatic int ky = tap / 3;
    automatic int kx = tap % 3;
    automatic int iy = int'(oy) * STRIDE + ky - PAD;
    automatic int ix = int'(ox) * STRIDE + kx - PAD;
    automatic logic in_range = (tap < 9) && (iy >= 0) && (iy < IN_HW) && (ix >= 0) && (ix < IN_HW);
    return {in_range, in_range ? IN_AW'(iy * IN_HW + ix) : IN_AW'(0)};
  endfunction

  logic [IN_AW:0] ta0, ta1;
  assign ta0 = tap_addr(2*int'(gphase),     goy, gox);
  assign ta1 = tap_addr(2*int'(gphase) + 1, goy, gox);
  assign in_rd_addr  = ta0[IN_AW-1:0];
  assign in_rd_addr2 = ta1[IN_AW-1:0];

  // capture-side copy of what was presented last cycle, registered so the
  // tap/range arithmetic is not on the path into win_next (timing)
  logic       cap_in0_r, cap_in1_r;
  logic [3:0] cap_tap0_r;
  always_ff @(posedge clk) begin
    cap_in0_r  <= ta0[IN_AW];
    cap_in1_r  <= ta1[IN_AW];
    cap_tap0_r <= {gphase[2:0], 1'b0};
  end

  // ================= issue (drains win_cur, OPS_PER_PIX ops/pixel) ========
  typedef enum logic [1:0] {S_IDLE, S_WARMUP, S_WAIT_OUTBANK, S_ISSUE} state_e;
  state_e st;

  logic [OUT_AW-1:0] ioy, iox, iidx;
  logic [$clog2(OPS_PER_PIX>1?OPS_PER_PIX:2)-1:0] icnt;
  logic [TILE_TAG_W-1:0] tile_tag_r;

  localparam int PASS_W = $clog2(NPASS > 1 ? NPASS : 2);
  wire [G_W-1:0]    cur_g    = G_W'(icnt % G);
  wire [PASS_W-1:0] cur_pass = (NPASS==1) ? '0 : PASS_W'(icnt / G);
  wire              issuing  = (st == S_ISSUE);

  // ---- win-slice select for the operand feeding this cycle's MAC lanes ----
  localparam int NLANE = CIN_PAR * 9;
  logic [7:0] win_slice [0:NLANE-1]; // flattened [tap*CIN_PAR+ci_local]
  always_comb begin
    for (int tap = 0; tap < 9; tap++)
      for (int ci_local = 0; ci_local < CIN_PAR; ci_local++)
        win_slice[tap*CIN_PAR+ci_local] = win_cur[tap][cur_pass*CIN_PAR + ci_local];
  end

  // ---- issue-time register stage (shared by every sub-lane) --------------
  logic [NLANE-1:0][7:0] opA_r;   // registered operand bytes, lane j=tap*CIN_PAR+ci_local
  logic                  issue_v1, issue_v2;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      issue_v1 <= 1'b0;
      issue_v2 <= 1'b0;
    end else begin
      issue_v1 <= issuing;
      issue_v2 <= issue_v1;
      if (issuing)
        for (int lane = 0; lane < NLANE; lane++)
          opA_r[lane] <= win_slice[lane];
    end
  end

  // tag: {bias, mult, shift, g, pixaddr, first, last_pass}
  localparam int OPTAG_W = 32+32+32+G_W+OUT_AW+1+1;

  // per-sub-lane requant outputs, consumed by the output collector
  logic             req_valid_o [COUT_PAR];
  logic [7:0]       req_out_u8  [COUT_PAR];
  logic [OUT_AW-1:0] req_pixaddr [COUT_PAR];
  logic [G_W-1:0]   req_g       [COUT_PAR];

  genvar gs, gl;
  generate
    for (gs = 0; gs < COUT_PAR; gs++) begin : g_sub
      localparam int CO_BASE = gs * G;
      wire [CO_W-1:0] co = CO_W'(CO_BASE + int'(cur_g));

      // ---- weight / bias / mult / shift ROMs (M9K-inferrable sync read) --
      logic [ROM_WBITS-1:0] wrom [COUT*NPASS];
      logic [31:0]          brom [COUT];
      logic [31:0]          mrom [COUT];
      logic [31:0]          srom [COUT];
      if (LAYER == 0) begin : g_rom0
        initial begin
          $readmemh(`TCNN_W_L0, wrom); $readmemh(`TCNN_B_L0, brom);
          $readmemh(`TCNN_M_L0, mrom); $readmemh(`TCNN_S_L0, srom);
        end
      end else if (LAYER == 1) begin : g_rom1
        initial begin
          $readmemh(`TCNN_W_L1, wrom); $readmemh(`TCNN_B_L1, brom);
          $readmemh(`TCNN_M_L1, mrom); $readmemh(`TCNN_S_L1, srom);
        end
      end else if (LAYER == 2) begin : g_rom2
        initial begin
          $readmemh(`TCNN_W_L2, wrom); $readmemh(`TCNN_B_L2, brom);
          $readmemh(`TCNN_M_L2, mrom); $readmemh(`TCNN_S_L2, srom);
        end
      end else begin : g_rom3
        initial begin
          $readmemh(`TCNN_W_L3, wrom); $readmemh(`TCNN_B_L3, brom);
          $readmemh(`TCNN_M_L3, mrom); $readmemh(`TCNN_S_L3, srom);
        end
      end

      logic [OPTAG_W-1:0] optag_now, optag_r1, optag_r2;
      assign optag_now = {brom[co], mrom[co], srom[co], cur_g, iidx,
                          (cur_pass == 0), (cur_pass == PASS_W'(NPASS-1))};

      logic [ROM_WBITS-1:0] wrom_q;
      always_ff @(posedge clk) begin
        if (issuing) begin
          wrom_q   <= wrom[int'(co)*NPASS + int'(cur_pass)];
          optag_r1 <= optag_now;
        end
        if (issue_v1) optag_r2 <= optag_r1;
      end

      // ---- product stage: NLANE signed multiplies, registered ----------
      // Quartus reads multstyle off the multiply's destination, so each
      // lane gets its own register declared with the style it should use.
      logic signed [PROD_W-1:0] prod_r [NLANE];
      for (gl = 0; gl < NLANE; gl++) begin : g_lane
        wire signed [3:0] wnib = wrom_q[4*gl +: 4];
        wire signed [8:0] apos = {1'b0, opA_r[gl]};
        if (gs * NLANE + gl < N_DSP_LANES) begin : g_dsp
          (* multstyle = "dsp" *) logic signed [PROD_W-1:0] p;
          always_ff @(posedge clk) if (issue_v1) p <= PROD_W'(apos * wnib);
          assign prod_r[gl] = p;
        end else begin : g_lgc
          (* multstyle = "logic" *) logic signed [PROD_W-1:0] p;
          always_ff @(posedge clk) if (issue_v1) p <= PROD_W'(apos * wnib);
          assign prod_r[gl] = p;
        end
      end

      // ---- adder tree (internal 2-level pipeline register) --------------
      logic                    a_valid_o;
      logic signed [SUM_W-1:0] a_dout_o;
      logic [OPTAG_W-1:0]      a_tag_o;

      adder_tree #(.N(NLANE), .W(PROD_W), .W_OUT(SUM_W), .REG_EVERY(2), .TAG_W(OPTAG_W)) u_adder (
          .clk(clk), .rst_n(rst_n),
          .valid_i(issue_v2), .din_i(prod_r), .tag_i(optag_r2),
          .valid_o(a_valid_o), .dout_o(a_dout_o), .tag_o(a_tag_o)
      );

      // ---- per-channel accumulate + requant dispatch --------------------
      logic signed [31:0] acc_mem [G];
      logic [31:0] a_bias, a_mult, a_shift;
      logic [G_W-1:0] a_g;
      logic [OUT_AW-1:0] a_pixaddr;
      logic a_first, a_last_pass;
      assign {a_bias, a_mult, a_shift, a_g, a_pixaddr, a_first, a_last_pass} = a_tag_o;

      logic signed [31:0] new_acc;
      assign new_acc = a_first ? ($signed(a_bias) + a_dout_o) : (acc_mem[a_g] + a_dout_o);

      always_ff @(posedge clk) begin
        if (a_valid_o) acc_mem[a_g] <= new_acc;
      end

      logic [OUT_AW+G_W-1:0] rq_tag_o;
      requant_pipe #(.ACC_W(32), .TAG_W(OUT_AW+G_W)) u_requant (
          .clk(clk), .rst_n(rst_n),
          .valid_i(a_valid_o && a_last_pass), .acc_i(new_acc),
          .mult_i($signed(a_mult)), .shift_i(a_shift[5:0]), .out_zp_i(16'(OUT_ZP)),
          .tag_i({a_pixaddr, a_g}),
          .valid_o(req_valid_o[gs]), .out_u8_o(req_out_u8[gs]), .tag_o(rq_tag_o)
      );
      assign req_pixaddr[gs] = rq_tag_o[OUT_AW+G_W-1:G_W];
      assign req_g[gs]       = rq_tag_o[G_W-1:0];
    end
  endgenerate

  // ---- output collector: every sub-lane's requant result for a given
  // (pixel, group) arrives in the same cycle; the fmap word is written when
  // the last group's bytes arrive ------------------------------------------
  wire req_last_g = (req_g[0] == G_W'(G-1));

  logic [COUT*8-1:0] out_word_r;
  always_ff @(posedge clk) begin
    for (int s = 0; s < COUT_PAR; s++)
      if (req_valid_o[s] && !req_last_g)
        out_word_r[(s*G + int'(req_g[s]))*8 +: 8] <= req_out_u8[s];
  end

  assign out_wr_en   = req_valid_o[0] && req_last_g;
  assign out_wr_addr = req_pixaddr[0];
  always_comb begin
    out_wr_data = out_word_r;
    for (int s = 0; s < COUT_PAR; s++)
      out_wr_data[(s*G + G-1)*8 +: 8] = req_out_u8[s]; // fold in the just-arrived last bytes
  end

  // ================= tile-level control FSM ================================
  // Shares this always_ff with the gather capture logic (rather than two
  // separate blocks each writing `gathering`/`gphase`) because Quartus
  // Prime's synthesis elaborator can't statically prove those two writers
  // are mutually exclusive ("Can't resolve multiple constant drivers",
  // error 10028; found via Gate P2, Verilator never complained).
  logic wr_done_pending;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      gathering <= 1'b0;
      gphase    <= 4'd0;
      gather_done_pulse <= 1'b0;
      st <= S_IDLE;
      in_rd_start <= 1'b0; in_rd_done <= 1'b0;
      out_wr_start <= 1'b0; out_wr_done <= 1'b0;
      goy <= '0; gox <= '0; gidx <= '0;
      ioy <= '0; iox <= '0; iidx <= '0; icnt <= '0;
      wr_done_pending <= 1'b0;
    end else begin
      gather_done_pulse <= 1'b0;
      if (gathering) begin
        // capture stage: the two taps presented last cycle (gphase-1) are
        // valid on in_rd_data / in_rd_data2 THIS cycle (1-cycle read latency)
        if (gphase >= 1) begin
          for (int ci = 0; ci < CIN; ci++) begin
            win_next[cap_tap0_r][ci] <= cap_in0_r ? in_rd_data[ci*8 +: 8] : 8'd0;
            if (cap_tap0_r != 4'd8)
              win_next[cap_tap0_r + 4'd1][ci] <= cap_in1_r ? in_rd_data2[ci*8 +: 8] : 8'd0;
          end
        end
        if (gphase == 4'(GATHER_LAST)) begin
          gathering <= 1'b0;
          gather_done_pulse <= 1'b1;
        end else begin
          gphase <= gphase + 4'd1;
        end
      end

      in_rd_start  <= 1'b0;
      in_rd_done   <= 1'b0;
      out_wr_start <= 1'b0;
      out_wr_done  <= 1'b0;

      unique case (st)
        S_IDLE: begin
          if (in_rd_ready) begin
            in_rd_start <= 1'b1;
            tile_tag_r  <= in_rd_tag;
            goy <= '0; gox <= '0; gidx <= 1;
            gathering <= 1'b1; gphase <= 4'd0;
            st <= S_WARMUP;
          end
        end

        S_WARMUP: begin
          if (gather_done_pulse) begin
            win_cur <= win_next;
            ioy <= '0; iox <= '0; iidx <= '0; icnt <= '0;
            // kick off gathering pixel 1 (if it exists) while we wait for
            // the output bank / start issuing pixel 0
            if (gidx < NPIX) begin
              goy <= (gidx / OUT_HW); gox <= (gidx % OUT_HW);
              gathering <= 1'b1; gphase <= 4'd0;
              gidx <= gidx + 1'b1;
            end
            if (out_wr_ready) begin
              out_wr_start <= 1'b1;
              out_wr_tag_r <= tile_tag_r;
              st <= S_ISSUE;
            end else begin
              st <= S_WAIT_OUTBANK;
            end
          end
        end

        S_WAIT_OUTBANK: begin
          if (out_wr_ready) begin
            out_wr_start <= 1'b1;
            out_wr_tag_r <= tile_tag_r;
            st <= S_ISSUE;
          end
        end

        S_ISSUE: begin
          // kick off gathering the pixel after next, once per pixel-issue
          // period, right as we start issuing the current pixel
          if (icnt == 0 && gidx < NPIX && !gathering) begin
            goy <= (gidx / OUT_HW); gox <= (gidx % OUT_HW);
            gathering <= 1'b1; gphase <= 4'd0;
            gidx <= gidx + 1'b1;
          end

          if (icnt == OPS_PER_PIX-1) begin
            icnt <= '0;
            if (iidx == NPIX-1) begin
              // last op of the last pixel has been ISSUED; its result is
              // still draining through the pipeline -- wr_done follows once
              // the output collector actually writes it (see below)
              wr_done_pending <= 1'b1;
              in_rd_done <= 1'b1;   // release the input bank now (already fully gathered)
              st <= S_IDLE;
            end else begin
              iidx <= iidx + 1'b1;
              ioy  <= ((iidx+1) / OUT_HW);
              iox  <= ((iidx+1) % OUT_HW);
              win_cur <= win_next;
            end
          end else begin
            icnt <= icnt + 1'b1;
          end
        end
      endcase

      // fires exactly when the very last output byte of the tile is written
      if (wr_done_pending && out_wr_en && (out_wr_addr == NPIX-1)) begin
        out_wr_done <= 1'b1;
        wr_done_pending <= 1'b0;
      end
    end
  end

  // synthesis translate_off
  always_ff @(posedge clk)
    if (rst_n && st == S_ISSUE && icnt == OPS_PER_PIX-1 && iidx != NPIX-1 && gathering)
      $error("conv_layer L%0d: next pixel's window consumed before its gather finished", LAYER);
  // synthesis translate_on

  logic [TILE_TAG_W-1:0] out_wr_tag_r;
  assign out_wr_tag = out_wr_tag_r;

endmodule
