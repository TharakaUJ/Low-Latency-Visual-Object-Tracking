// tile_feeder.sv -- turns a raster RGB pixel stream (valid/ready, one pixel
// per cycle) into non-overlapping 16x16 tiles (stride 16) pushed into the
// L0-input fmap_pingpong. Two 16-line "band" buffers: fill one in raster
// order while the previous band's tiles are still being drained out to the
// L0in buffer; a band becomes available for tile extraction once its 16th
// row has been written.
//
// FRAME_W/FRAME_H must be multiples of 16 (checked by the caller / firmware,
// not enforced here). MAX_W bounds the band buffer's row stride.
module tile_feeder #(
    parameter int MAX_W = 640,
    parameter int TILE_TAG_W = 16
) (
    input  logic clk,
    input  logic rst_n,

    // raster pixel stream in
    output logic          px_ready,
    input  logic          px_valid,
    input  logic [23:0]   px_data,     // {B,G,R}, R at [7:0]
    input  logic [15:0]   frame_w,     // multiple of 16
    input  logic [15:0]   frame_h,     // multiple of 16
    input  logic          frame_first, // pulses with the first pixel of a frame
    input  logic          frame_last_row_tile, // unused placeholder (kept for future stride use)

    // L0in fmap_pingpong producer port
    input  logic                  l0in_wr_ready,
    output logic                  l0in_wr_start,
    output logic [TILE_TAG_W-1:0] l0in_wr_tag,   // {band[9:0], tcol[5:0]}
    output logic                  l0in_wr_en,
    output logic [$clog2(16*16)-1:0] l0in_wr_addr,
    output logic [3*8-1:0]        l0in_wr_data,
    output logic                  l0in_wr_done
);
  // ---- band buffers: 2 x (16 rows x MAX_W pixels), simple dual port ----
  logic [23:0] band0 [16*MAX_W];
  logic [23:0] band1 [16*MAX_W];

  typedef enum logic [1:0] {BFREE, BFILLING, BFULL, BDRAINING} bstate_e;
  bstate_e bst [2];
  logic [15:0] band_w [2];     // frame_w captured when this band started filling
  logic [15:0] band_first_row [2]; // absolute row of this band's row0 (for tag/last-tile bookkeeping, informational)
  logic        band_last [2];  // this band is the last band of the frame (may be a partial band -- not handled, MAX_H assumed a multiple of 16)

  logic fill_ptr;      // which band is currently being filled
  logic drain_ptr;     // which band tile extraction is currently draining

  logic [$clog2(MAX_W)-1:0] fill_col;
  logic [3:0]                fill_row;   // 0..15 within the band

  assign px_ready = (bst[fill_ptr] == BFREE) || (bst[fill_ptr] == BFILLING);

  // ---- tile extraction state (drain side) ----
  logic [$clog2(MAX_W/16>1?MAX_W/16:2)-1:0] tcol;
  logic [3:0] ex_row;
  logic [3:0] ex_col;
  logic [$clog2(16*16)-1:0] ex_addr;
  logic [15:0] band_tag_ctr;   // running band index, used as the tag's upper bits

  typedef enum logic [2:0] {D_IDLE, D_START, D_COPY, D_FLUSH, D_DONE} dstate_e;
  dstate_e dst;

  assign ex_addr = ex_row*16 + ex_col;

  // ---- band read pipeline: each bank gets its OWN synchronous read (a
  // plain "reg <= array[addr]", updated every cycle regardless of state),
  // muxed AFTER registering -- not a single register fed by
  // "band0[addr] : band1[addr]" selected before the clock edge. Quartus
  // Prime's RAM inference does not recognize that combined form as a
  // synchronous read for these large (16*MAX_W-deep) arrays, so it fell
  // back to registers for both banks and blew the design's register
  // budget ("Cannot convert all sets of registers into RAM megafunctions",
  // error 276003 -- found via Gate P2). This adds one pipeline cycle
  // between reading a source pixel and writing it to l0in, so the
  // l0in_wr_en/addr/data write and the D_DONE handshake are delayed to
  // match (one extra D_FLUSH state lets the last pixel's delayed write
  // land before l0in_wr_done fires).
  wire [$clog2(16*MAX_W)-1:0] src_addr = ex_row*MAX_W + (tcol*16 + ex_col);
  logic [23:0] band0_q, band1_q;
  logic [$clog2(16*16)-1:0] ex_addr_d;
  logic                     copy_valid_d;
  logic                     drain_ptr_d;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      copy_valid_d <= 1'b0;
    end else begin
      band0_q      <= band0[src_addr];
      band1_q      <= band1[src_addr];
      ex_addr_d    <= ex_addr;
      copy_valid_d <= (dst == D_COPY);
      drain_ptr_d  <= drain_ptr;
    end
  end

  // Fill-side and drain-side logic share ONE always_ff (rather than two
  // separate blocks each indexing into `bst` with a runtime pointer --
  // fill_ptr on one side, drain_ptr on the other) because Quartus Prime's
  // synthesis elaborator cannot statically prove the two variable-indexed
  // writes never target the same array element in the same cycle, and
  // rejects the design with "Can't resolve multiple constant drivers for
  // net bst[...]" (error 10028) even though the two pointers are always
  // kept apart by construction (found via Gate P2; Verilator, which just
  // schedules both processes and lets last-write-wins per element, never
  // flagged this). Merging into one process gives `bst` a single driver
  // without changing any timing or behavior -- every statement below is
  // byte-for-byte the same as the two original blocks.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fill_ptr <= 1'b0; fill_col <= '0; fill_row <= '0;
      bst[0] <= BFREE; bst[1] <= BFREE;
      drain_ptr <= 1'b0;
      dst <= D_IDLE;
      tcol <= '0; ex_row <= '0; ex_col <= '0;
      l0in_wr_start <= 1'b0; l0in_wr_en <= 1'b0; l0in_wr_done <= 1'b0;
      band_tag_ctr <= '0;
    end else begin
      if (frame_first) begin
        fill_col <= '0; fill_row <= '0;
      end
      if (px_valid && px_ready) begin
        if (fill_ptr == 1'b0) band0[fill_row*MAX_W + fill_col] <= px_data;
        else                   band1[fill_row*MAX_W + fill_col] <= px_data;
        if (bst[fill_ptr] == BFREE) begin
          bst[fill_ptr] <= BFILLING;
          band_w[fill_ptr] <= frame_w;
        end
        if (fill_col == frame_w-1) begin
          fill_col <= '0;
          if (fill_row == 15) begin
            fill_row <= '0;
            bst[fill_ptr] <= BFULL;
            fill_ptr <= ~fill_ptr;
          end else begin
            fill_row <= fill_row + 4'd1;
          end
        end else begin
          fill_col <= fill_col + 1'b1;
        end
      end

      l0in_wr_start <= 1'b0;
      l0in_wr_done  <= 1'b0;

      // the write-side handshake trails the address generator below by
      // exactly one cycle (matching band0_q/band1_q's read latency) --
      // driven every cycle, independent of `dst`, so the final pixel's
      // write still lands correctly even after `dst` has already moved on
      // to D_FLUSH.
      l0in_wr_en   <= copy_valid_d;
      l0in_wr_addr <= ex_addr_d;
      l0in_wr_data <= (drain_ptr_d == 1'b0) ? band0_q : band1_q;

      unique case (dst)
        D_IDLE: begin
          if (bst[drain_ptr] == BFULL) begin
            tcol <= '0; ex_row <= '0; ex_col <= '0;
            dst <= D_START;
          end
        end
        D_START: begin
          if (l0in_wr_ready) begin
            l0in_wr_start <= 1'b1;
            l0in_wr_tag   <= {band_tag_ctr[TILE_TAG_W-$clog2(MAX_W/16)-1:0], tcol};
            ex_row <= '0; ex_col <= '0;
            dst <= D_COPY;
          end
        end
        D_COPY: begin
          if (ex_col == 15) begin
            ex_col <= '0;
            if (ex_row == 15) begin
              dst <= D_FLUSH;
            end else begin
              ex_row <= ex_row + 4'd1;
            end
          end else begin
            ex_col <= ex_col + 4'd1;
          end
        end
        D_FLUSH: begin
          // one cycle for the last pixel's delayed write (queued by the
          // pipeline above while `dst` was still D_COPY) to land before
          // D_DONE's handshake fires.
          dst <= D_DONE;
        end
        D_DONE: begin
          l0in_wr_done <= 1'b1;
          if (tcol == (band_w[drain_ptr]/16 - 1)) begin
            // last tile column of this band: release it, advance band
            bst[drain_ptr] <= BFREE;
            drain_ptr <= ~drain_ptr;
            // wrap the band index every frame_h/16 bands, so a tag's band
            // field always identifies a position WITHIN the frame -- a
            // free-running counter would keep climbing across frames and
            // make every later frame's tiles land on the wrong result_ram
            // address (found via Gate F1: every tile mismatched past frame 0).
            if (band_tag_ctr == (frame_h/16 - 1)) band_tag_ctr <= '0;
            else band_tag_ctr <= band_tag_ctr + 1'b1;
            dst <= D_IDLE;
          end else begin
            tcol <= tcol + 1'b1;
            dst <= D_START;
          end
        end
      endcase
    end
  end
endmodule
