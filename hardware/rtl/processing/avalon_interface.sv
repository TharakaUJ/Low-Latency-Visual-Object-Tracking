module avalon_slave_bounds #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 2      // enough for 2 registers, expand later
)(
    // Avalon clock/reset
    input  wire                    clk,
    input  wire                    reset,        // active-high, synchronous

    // Avalon-MM slave interface
    input  wire [ADDR_WIDTH-1:0]   avs_address,
    input  wire                    avs_read,
    output reg  [DATA_WIDTH-1:0]   avs_readdata,
    input  wire                    avs_write,    // unused for now, wired in for future
    input  wire [DATA_WIDTH-1:0]   avs_writedata,
    output wire                    avs_waitrequest,

    // Values coming from the rest of your design
    input  wire [DATA_WIDTH-1:0]   bound_x,
    input  wire [DATA_WIDTH-1:0]   bound_y
);

    // Register address map
    localparam ADDR_BOUND_X = 2'd0;
    localparam ADDR_BOUND_Y = 2'd1;

    // No wait states needed for simple read-only regs
    assign avs_waitrequest = 1'b0;

    always @(posedge clk) begin
        if (reset) begin
            avs_readdata <= {DATA_WIDTH{1'b0}};
        end else if (avs_read) begin
            case (avs_address)
                ADDR_BOUND_X: avs_readdata <= bound_x;
                ADDR_BOUND_Y: avs_readdata <= bound_y;
                default:      avs_readdata <= {DATA_WIDTH{1'b0}};
            endcase
        end
    end

endmodule