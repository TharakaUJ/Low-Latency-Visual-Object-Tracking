// conv_layer.sv -- one streaming, layer-pipelined 3x3 conv stage. Reads its
// tile from an upstream fmap_pingpong (consumer port), writes its result
// tile to a downstream fmap_pingpong (producer port). Runs concurrently with
// every other layer, each on its own tile, handshaking only through the
// fmap_pingpong ping-pong buffers between them.
//
// Per-tile schedule (see docs/implementation_plan.md):
//   - a ~11-cycle warmup gathers output-pixel (0,0)'s 3x3xCIN window
//   - then, for each output pixel, gather the NEXT pixel's window while the
//     ISSUER spends CIN_PAR*9-lane MAC ops feeding the CURRENT pixel's
//     COUT*NPASS accumulations -- gather always finishes (9 taps + 1-cycle
//     read latency = 10 cycles) well inside the smallest per-pixel issue
//     budget (COUT*NPASS >= 16 cycles for every layer in this network), so
//     it never stalls the issuer.
//   - issue order per pixel is PASS-MAJOR, CHANNEL-MINOR (p=icnt/COUT,
//     co=icnt%COUT): consecutive ops for the SAME co are COUT cycles apart,
//     which is longer than the MAC pipeline's latency, so the per-channel
//     accumulate (acc_mem[co] <= acc_mem[co] + sum) never reads a value
//     that's still in flight -- this is the fix for the old design's B19
//     ("acc <= acc + mac_sum ... true sequential dependency").
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
// ROM files are selected by the LAYER parameter (0..3) via a generate-case
// below, using gen/tcnn_paths.svh's per-file `TCNN_* literal string macros
// directly in each $readmemh call -- NOT via string parameters (there used
// to be ROM_FILE/BIAS_FILE/MULT_FILE/SHIFT_FILE `parameter string`s here).
// Quartus Prime 25.1's synthesis elaborator unconditionally rejects ANY
// string parameter used as $readmemh's filename argument ("has an
// aggregate value", error 10686) -- confirmed with a minimal isolated
// repro outside this project; true regardless of whether the parameter has
// a default, what that default is, or how it's declared. Only a literal
// string token (or a macro that expands to one) works. Found via Gate P2 --
// the simulator accepted the old parameterized form without complaint.
`include "tcnn_paths.svh"
module conv_layer #(
    parameter int CIN, COUT, IN_HW, OUT_HW, STRIDE, PAD = 1,
    parameter int CIN_PAR, NPASS,
    parameter int LAYER = 0,   // selects which gen/*_L<LAYER>.hex ROMs to load (0..3)
    parameter int OUT_ZP  = 0,
    parameter int TILE_TAG_W = 16
) (
    input  logic clk,
    input  logic rst_n,

    // consumer port into the upstream fmap_pingpong
    input  logic                          in_rd_ready,
    output logic                          in_rd_start,
    input  logic [TILE_TAG_W-1:0]         in_rd_tag,
    output logic [$clog2(IN_HW*IN_HW)-1:0] in_rd_addr,
    input  logic [CIN*8-1:0]              in_rd_data,
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
  localparam int OPS_PER_PIX = COUT * NPASS;
  localparam int NPIX        = OUT_HW * OUT_HW;
  localparam int IN_AW       = $clog2(IN_HW*IN_HW > 1 ? IN_HW*IN_HW : 2);
  localparam int OUT_AW      = $clog2(NPIX > 1 ? NPIX : 2);
  localparam int CO_W        = $clog2(COUT > 1 ? COUT : 2);
  localparam int ROM_WBITS   = CIN_PAR * 9 * 4;
  localparam int PROD_W      = 24;   // wide enough for the largest lane sum (see comments below)

  // ---- weight / bias / mult / shift ROMs (M9K-inferrable sync read) ----
  logic [ROM_WBITS-1:0] wrom [COUT*NPASS];
  logic [31:0]          brom [COUT];
  logic [31:0]          mrom [COUT];
  logic [31:0]          srom [COUT];
  generate
    case (LAYER)
      0: initial begin
        $readmemh(`TCNN_W_L0, wrom); $readmemh(`TCNN_B_L0, brom);
        $readmemh(`TCNN_M_L0, mrom); $readmemh(`TCNN_S_L0, srom);
      end
      1: initial begin
        $readmemh(`TCNN_W_L1, wrom); $readmemh(`TCNN_B_L1, brom);
        $readmemh(`TCNN_M_L1, mrom); $readmemh(`TCNN_S_L1, srom);
      end
      2: initial begin
        $readmemh(`TCNN_W_L2, wrom); $readmemh(`TCNN_B_L2, brom);
        $readmemh(`TCNN_M_L2, mrom); $readmemh(`TCNN_S_L2, srom);
      end
      3: initial begin
        $readmemh(`TCNN_W_L3, wrom); $readmemh(`TCNN_B_L3, brom);
        $readmemh(`TCNN_M_L3, mrom); $readmemh(`TCNN_S_L3, srom);
      end
    endcase
  endgenerate

  // ================= gather (fills win_next one output-pixel ahead) ======
  logic [7:0] win_cur  [0:8][0:CIN-1];
  logic [7:0] win_next [0:8][0:CIN-1];

  logic        gathering;
  logic [3:0]  gphase;        // 0..8 present address, 1..9 capture (10 phases)
  logic [OUT_AW-1:0] goy, gox;
  logic [OUT_AW-1:0] gidx;    // next pixel index to gather (NPIX == "nothing left")
  logic        gather_done_pulse;

  logic [3:0]  gtap_addr;     // tap index whose address is presented this cycle
  logic signed [$clog2(IN_HW)+1:0] g_iy, g_ix;

  assign gtap_addr = gphase[3:0];

  always_comb begin
    // tap -> (ky,kx); output pixel (goy,gox) -> input coords for that tap
    automatic int ky = gtap_addr / 3;
    automatic int kx = gtap_addr % 3;
    g_iy = $signed({1'b0, goy}) * STRIDE + ky - PAD;
    g_ix = $signed({1'b0, gox}) * STRIDE + kx - PAD;
  end

  always_comb begin
    logic in_range;
    logic [IN_AW-1:0] addr;
    in_range = (g_iy >= 0) && (g_iy < IN_HW) && (g_ix >= 0) && (g_ix < IN_HW);
    addr = in_range ? (g_iy[$clog2(IN_HW)-1:0] * IN_HW + g_ix[$clog2(IN_HW)-1:0]) : '0;
    in_rd_addr = addr;
  end

  // (the gather capture logic below and the tile-control FSM further down
  // both need to write `gathering`/`gphase` -- merged into ONE always_ff,
  // see the tile-level control FSM's header comment for why.)

  // ================= issue (drains win_cur, COUT*NPASS ops/pixel) ========
  typedef enum logic [1:0] {S_IDLE, S_WARMUP, S_WAIT_OUTBANK, S_ISSUE} state_e;
  state_e st;

  logic [OUT_AW-1:0] ioy, iox, iidx;
  logic [$clog2(OPS_PER_PIX>1?OPS_PER_PIX:2)-1:0] icnt;
  logic [TILE_TAG_W-1:0] tile_tag_r;

  localparam int PASS_W = $clog2(NPASS > 1 ? NPASS : 2);
  wire [CO_W-1:0]   cur_co   = icnt % COUT;
  wire [PASS_W-1:0] cur_pass = (NPASS==1) ? '0 : (icnt / COUT);
  wire              issuing  = (st == S_ISSUE);

  // ---- win-slice select for the operand feeding this cycle's MAC lanes ----
  // exactly NLANE elements (no unused gaps -- an earlier version strided
  // this array by 32 regardless of CIN_PAR, which left most entries
  // unassigned in this always_comb and caused stale/aliased reads).
  localparam int NLANE0 = CIN_PAR * 9;
  logic [7:0] win_slice [0:NLANE0-1]; // flattened [tap*CIN_PAR+ci_local]
  always_comb begin
    for (int tap = 0; tap < 9; tap++)
      for (int ci_local = 0; ci_local < CIN_PAR; ci_local++)
        win_slice[tap*CIN_PAR+ci_local] = win_cur[tap][cur_pass*CIN_PAR + ci_local];
  end

  // pack this op's tag: {bias, mult, shift, co, pixaddr, first, last_pass}
  localparam int OPTAG_W = 32+32+32+CO_W+OUT_AW+1+1;
  logic [OPTAG_W-1:0] optag_now;
  assign optag_now = {brom[cur_co], mrom[cur_co], srom[cur_co], cur_co, iidx,
                      (cur_pass == 0), (cur_pass == (NPASS-1))};

  // ---- issue-time register stage: win slice + weight ROM word + tag -----
  logic [CIN_PAR*9-1:0][7:0] opA_r;   // registered operand bytes, lane j=tap*CIN_PAR+ci_local
  logic [ROM_WBITS-1:0]      wrom_q;
  logic [OPTAG_W-1:0]        optag_r1;
  logic                      issue_v1;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) issue_v1 <= 1'b0;
    else begin
      issue_v1 <= issuing;
      if (issuing) begin
        for (int lane = 0; lane < NLANE0; lane++)
          opA_r[lane] <= win_slice[lane];
        wrom_q   <= wrom[cur_co*NPASS + cur_pass];
        optag_r1 <= optag_now;
      end
    end
  end

  // ---- product stage: CIN_PAR*9 signed multiplies, registered ----------
  localparam int NLANE = CIN_PAR * 9;
  logic signed [PROD_W-1:0] prod_r [NLANE];
  logic [OPTAG_W-1:0]       optag_r2;
  logic                     issue_v2;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) issue_v2 <= 1'b0;
    else begin
      issue_v2 <= issue_v1;
      if (issue_v1) begin
        for (int lane = 0; lane < NLANE; lane++) begin
          automatic logic signed [3:0] wnib = wrom_q[4*lane +: 4];
          automatic logic signed [8:0] apos = {1'b0, opA_r[lane]};
          prod_r[lane] <= PROD_W'($signed(apos) * $signed(wnib));
        end
        optag_r2 <= optag_r1;
      end
    end
  end

  // ---- adder tree (internal 2-level pipeline register) ------------------
  logic                a_valid_o;
  logic signed [PROD_W-1:0] a_dout_o;
  logic [OPTAG_W-1:0]  a_tag_o;

  adder_tree #(.N(NLANE), .W(PROD_W), .REG_EVERY(2), .TAG_W(OPTAG_W)) u_adder (
      .clk(clk), .rst_n(rst_n),
      .valid_i(issue_v2), .din_i(prod_r), .tag_i(optag_r2),
      .valid_o(a_valid_o), .dout_o(a_dout_o), .tag_o(a_tag_o)
  );

  // ---- per-channel accumulate + requant dispatch -------------------------
  logic signed [31:0] acc_mem [COUT];
  logic signed [31:0] bias_f, mult_f_unused;
  logic [31:0] a_bias, a_mult, a_shift;
  logic [CO_W-1:0] a_co;
  logic [OUT_AW-1:0] a_pixaddr;
  logic a_first, a_last_pass;
  assign {a_bias, a_mult, a_shift, a_co, a_pixaddr, a_first, a_last_pass} = a_tag_o;

  logic signed [31:0] new_acc;
  assign new_acc = a_first ? ($signed(a_bias) + a_dout_o) : (acc_mem[a_co] + a_dout_o);

  always_ff @(posedge clk) begin
    if (a_valid_o) acc_mem[a_co] <= new_acc;
  end

  logic req_valid_i;
  logic [OUT_AW+CO_W-1:0] req_tag_i; // {pixaddr, co}
  assign req_valid_i = a_valid_o && a_last_pass;
  assign req_tag_i   = {a_pixaddr, a_co};

  logic req_valid_o;
  logic [7:0] req_out_u8;
  logic [OUT_AW+CO_W-1:0] req_tag_o;

  requant_pipe #(.ACC_W(32), .TAG_W(OUT_AW+CO_W)) u_requant (
      .clk(clk), .rst_n(rst_n),
      .valid_i(req_valid_i), .acc_i(new_acc),
      .mult_i($signed(a_mult)), .shift_i(a_shift[5:0]), .out_zp_i(16'(OUT_ZP)),
      .tag_i(req_tag_i),
      .valid_o(req_valid_o), .out_u8_o(req_out_u8), .tag_o(req_tag_o)
  );

  wire [OUT_AW-1:0] req_pixaddr = req_tag_o[OUT_AW+CO_W-1:CO_W];
  wire [CO_W-1:0]   req_co      = req_tag_o[CO_W-1:0];
  wire              req_last_co = (req_co == COUT-1);

  // ---- output collector: assemble COUT bytes, write the fmap word on the
  // last channel's arrival for a given output pixel ------------------------
  logic [COUT*8-1:0] out_word_r;
  always_ff @(posedge clk) begin
    if (req_valid_o && !req_last_co)
      out_word_r[req_co*8 +: 8] <= req_out_u8;
  end

  assign out_wr_en   = req_valid_o && req_last_co;
  assign out_wr_addr = req_pixaddr;
  always_comb begin
    out_wr_data = out_word_r;
    out_wr_data[(COUT-1)*8 +: 8] = req_out_u8; // fold in the just-arrived last byte
  end

  // ================= tile-level control FSM ================================
  // Shares this always_ff with the gather capture logic (rather than two
  // separate blocks each writing `gathering`/`gphase` -- one to advance the
  // gather phase and clear `gathering` when done, the other to kick a new
  // gather off) because Quartus Prime's synthesis elaborator can't
  // statically prove those two writers are always mutually exclusive (they
  // are, by construction: the FSM only sets gathering<=1 while it's
  // currently 0, and the gather logic only clears it -- but the tool still
  // rejects the two-process form with "Can't resolve multiple constant
  // drivers", error 10028; found via Gate P2, Verilator never complained).
  // Merging changes no timing or behavior; every statement is unchanged.
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
        // capture stage: gphase-1 was presented last cycle, its data is
        // valid on in_rd_data THIS cycle (1-cycle sync-RAM read latency)
        if (gphase >= 1) begin
          automatic int cap_tap = gphase - 1;
          // recompute in-range for the tap that was addressed last cycle
          automatic int cap_ky = cap_tap / 3;
          automatic int cap_kx = cap_tap % 3;
          automatic logic signed [$clog2(IN_HW)+1:0] cy, cx;
          cy = $signed({1'b0, goy}) * STRIDE + cap_ky - PAD;
          cx = $signed({1'b0, gox}) * STRIDE + cap_kx - PAD;
          for (int ci = 0; ci < CIN; ci++) begin
            if (cy >= 0 && cy < IN_HW && cx >= 0 && cx < IN_HW)
              win_next[cap_tap][ci] <= in_rd_data[ci*8 +: 8];
            else
              win_next[cap_tap][ci] <= 8'd0;
          end
        end
        if (gphase == 9) begin
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
      if (wr_done_pending && req_valid_o && req_last_co && (req_pixaddr == NPIX-1)) begin
        out_wr_done <= 1'b1;
        wr_done_pending <= 1'b0;
      end
    end
  end

  logic [TILE_TAG_W-1:0] out_wr_tag_r;
  assign out_wr_tag = out_wr_tag_r;

endmodule
