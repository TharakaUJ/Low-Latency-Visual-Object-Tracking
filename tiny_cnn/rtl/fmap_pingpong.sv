// fmap_pingpong.sv -- double-buffered feature-map storage between two
// pipeline stages that run concurrently on different tiles. Two banks of
// simple-dual-port RAM (1-cycle read latency, M9K-inferrable); the producer
// fills one bank while the consumer drains the other.
//
// Interface is a simple start/done handshake rather than an explicit bank
// index: internally each bank tracks its own state (FREE -> WRITING -> FULL
// -> READING -> FREE) and a small tag register, and a round-robin pointer on
// each side always picks "the other" bank next, which keeps producer and
// consumer order automatically aligned (2 banks => strict alternation).
//
// Producer:  wait for wr_ready, pulse wr_start (latches wr_tag), then any
//            number of (wr_en, wr_addr, wr_data) cycles, then pulse wr_done
//            to commit (bank becomes FULL, readable).
// Consumer:  wait for rd_ready, pulse rd_start (bank becomes READING, tag
//            is presented on rd_tag), then set rd_addr (1-cycle read
//            latency to rd_data), then pulse rd_done to release (bank
//            becomes FREE again, so the producer can reuse it).
//
// wr_ready/rd_ready only ever look at the FREE/FULL bank that would be
// acquired next (not "any bank"), so producer and consumer always agree on
// tile order -- there is no way to skip ahead into the wrong bank.
module fmap_pingpong #(
    parameter int WORD_W = 32,
    parameter int DEPTH  = 256,
    parameter int TAG_W  = 16
) (
    input  logic                  clk,
    input  logic                  rst_n,

    // producer (write) side
    output logic                  wr_ready,
    input  logic                  wr_start,
    input  logic [TAG_W-1:0]      wr_tag,
    input  logic                  wr_en,
    input  logic [$clog2(DEPTH)-1:0] wr_addr,
    input  logic [WORD_W-1:0]     wr_data,
    input  logic                  wr_done,

    // consumer (read) side
    output logic                  rd_ready,
    input  logic                  rd_start,
    output logic [TAG_W-1:0]      rd_tag,
    input  logic [$clog2(DEPTH)-1:0] rd_addr,
    output logic [WORD_W-1:0]     rd_data,
    input  logic                  rd_done
);
  localparam int AW = $clog2(DEPTH);
  typedef enum logic [1:0] {FREE, WRITING, FULL, READING} state_e;

  state_e           st       [2];
  logic [TAG_W-1:0] tag_r    [2];
  logic             wr_ptr;   // which bank the producer is/will target
  logic             rd_ptr;   // which bank the consumer is/will target

  // two independent simple-dual-port memories (one write port, one read port)
  logic [WORD_W-1:0] mem0 [DEPTH];
  logic [WORD_W-1:0] mem1 [DEPTH];

  assign wr_ready = (st[wr_ptr] == FREE);
  assign rd_ready = (st[rd_ptr] == FULL);
  assign rd_tag   = tag_r[rd_ptr];

  // write port (bank selected by wr_ptr)
  always_ff @(posedge clk) begin
    if (wr_en) begin
      if (wr_ptr == 1'b0) mem0[wr_addr] <= wr_data;
      else                 mem1[wr_addr] <= wr_data;
    end
  end

  // read port (bank selected by rd_ptr), 1-cycle latency. Each bank is read
  // into its OWN register first, and the bank select is applied AFTER that
  // (combinationally, on two already-registered values) -- not a single
  // register fed by "mem0[addr] : mem1[addr]" selected before the clock
  // edge. Quartus Prime's RAM inference does not recognize that combined
  // form as a synchronous read (it reported both mem0/mem1 "uninferred due
  // to asynchronous read logic" and register-ized a 640x48-deep instance of
  // this pattern elsewhere in the design, blowing the LE/register budget --
  // found via Gate P2); this per-bank-then-mux form is the standard
  // tool-friendly idiom for a 2-bank simple-dual-port memory.
  logic [WORD_W-1:0] mem0_q, mem1_q;
  always_ff @(posedge clk) mem0_q <= mem0[rd_addr];
  always_ff @(posedge clk) mem1_q <= mem1[rd_addr];
  assign rd_data = (rd_ptr == 1'b0) ? mem0_q : mem1_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st[0] <= FREE; st[1] <= FREE;
      wr_ptr <= 1'b0; rd_ptr <= 1'b0;
      tag_r[0] <= '0; tag_r[1] <= '0;
    end else begin
      // producer side
      if (wr_start && st[wr_ptr] == FREE) begin
        st[wr_ptr]    <= WRITING;
        tag_r[wr_ptr] <= wr_tag;
      end
      if (wr_done && st[wr_ptr] == WRITING) begin
        st[wr_ptr] <= FULL;
        wr_ptr     <= ~wr_ptr;
      end
      // consumer side
      if (rd_start && st[rd_ptr] == FULL) begin
        st[rd_ptr] <= READING;
      end
      if (rd_done && st[rd_ptr] == READING) begin
        st[rd_ptr] <= FREE;
        rd_ptr     <= ~rd_ptr;
      end
    end
  end
endmodule
