module avalon_slave_top #(
    parameter int DATA_WIDTH = 32,
    parameter int WIN        = 16,                    // template is WIN x WIN
    parameter int TMPL_CNT   = WIN*WIN,                // 256 registers
    parameter int IDX_WIDTH  = $clog2(TMPL_CNT),       // 8 bits for 256
    parameter int ADDR_WIDTH = $clog2(2 + TMPL_CNT)    // 2 bound regs + template regs
)(
    // Avalon clock/reset (clk_50 domain)
    input  wire                    clk,
    input  wire                    reset,        // active-high, synchronous

    // Avalon-MM slave interface
    input  wire [ADDR_WIDTH-1:0]   avs_address,
    input  wire                    avs_read,
    output reg  [DATA_WIDTH-1:0]   avs_readdata,
    input  wire                    avs_write,
    input  wire [DATA_WIDTH-1:0]   avs_writedata,
    output wire                    avs_waitrequest,

    // Boundary values, already synchronized into this (clk_50) domain
    // by cdc_bus_sync at the top level.
    input  wire [9:0]              bound_x,
    input  wire [9:0]              bound_y,

    // ---- CDC bridge to the template register file, which physically   ----
    // ---- lives in the processing (clk / 27MHz) clock domain inside    ----
    // ---- template_match. These signals are in THIS (clk_50) domain -  ----
    // ---- cdc_pulse_sync instances at the top level cross them over.   ----
    output reg                     tmpl_wr_req,    // 1-cycle pulse: "please write"
    output reg  [IDX_WIDTH-1:0]    tmpl_wr_index,  // row*WIN + col
    output reg  [7:0]              tmpl_wr_data,
    input  wire                    tmpl_wr_ack     // 1-cycle pulse: write applied
);

    localparam [ADDR_WIDTH-1:0] ADDR_BOUND_X  = 'd0;
    localparam [ADDR_WIDTH-1:0] ADDR_BOUND_Y  = 'd1;
    localparam [ADDR_WIDTH-1:0] ADDR_TMPL_BASE = 'd2;

    wire is_tmpl_addr = (avs_address >= ADDR_TMPL_BASE) &&
                         (avs_address < ADDR_TMPL_BASE + TMPL_CNT);
    wire [IDX_WIDTH-1:0] tmpl_index = avs_address - ADDR_TMPL_BASE;

    // Local mirror of the template contents, kept in THIS clock domain so
    // reads can be serviced immediately without waiting on the slow domain.
    // It is updated the moment a write is accepted, which is also the
    // instant we kick off the CDC handshake to apply it for real in
    // template_match - so the mirror and the real array are guaranteed to
    // converge, they're just not necessarily updated on the exact same
    // clk_50 cycle.
    reg [7:0] tmpl_mirror [TMPL_CNT-1:0];

    // Busy/waitrequest: while a template write is in flight to the slow
    // domain, stall further writes so we never overwrite tmpl_wr_index/data
    // before the previous request has been picked up by cdc_pulse_sync.
    reg busy;
    assign avs_waitrequest = busy;

    integer i;

    always_ff @(posedge clk) begin
        if (reset) begin
            busy          <= 1'b0;
            tmpl_wr_req   <= 1'b0;
            tmpl_wr_index <= '0;
            tmpl_wr_data  <= '0;
            avs_readdata  <= '0;
            for (i = 0; i < TMPL_CNT; i = i + 1)
                tmpl_mirror[i] <= 8'hFF;   // matches template_match's reset default
        end else begin
            tmpl_wr_req <= 1'b0; // default: pulse low unless asserted below

            // ---- writes ----
            if (!busy && avs_write && is_tmpl_addr) begin
                tmpl_wr_index      <= tmpl_index;
                tmpl_wr_data       <= avs_writedata[7:0];
                tmpl_mirror[tmpl_index] <= avs_writedata[7:0];
                tmpl_wr_req        <= 1'b1;
                busy               <= 1'b1;
            end else if (busy && tmpl_wr_ack) begin
                busy <= 1'b0;
            end
            // writes to ADDR_BOUND_X/Y or out-of-range addresses are ignored
            // (bound regs are outputs of the design, not configurable)

            // ---- reads ----
            if (avs_read) begin
                if (avs_address == ADDR_BOUND_X)
                    avs_readdata <= {{(DATA_WIDTH-10){1'b0}}, bound_x};
                else if (avs_address == ADDR_BOUND_Y)
                    avs_readdata <= {{(DATA_WIDTH-10){1'b0}}, bound_y};
                else if (is_tmpl_addr)
                    avs_readdata <= {{(DATA_WIDTH-8){1'b0}}, tmpl_mirror[tmpl_index]};
                else
                    avs_readdata <= {DATA_WIDTH{1'b0}};
            end
        end
    end

endmodule
