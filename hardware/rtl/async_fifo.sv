`timescale 1ns / 1ps

module async_fifo #(
    parameter integer DATA_WIDTH = 24,
    parameter integer ADDR_WIDTH = 9
)(
    input  wire                   wr_clk,
    input  wire                   wr_rst_n,
    input  wire                   wr_en,
    input  wire [DATA_WIDTH-1:0]  wr_data,
    output wire                   full,

    input  wire                   rd_clk,
    input  wire                   rd_rst_n,
    input  wire                   rd_en,
    output wire [DATA_WIDTH-1:0]  rd_data,
    output wire                   empty
);

    localparam integer PTR_WIDTH = ADDR_WIDTH + 1;
    localparam integer DEPTH     = (1 << ADDR_WIDTH);

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    reg [PTR_WIDTH-1:0] wr_bin;
    reg [PTR_WIDTH-1:0] wr_gray;
    reg [PTR_WIDTH-1:0] rd_bin;
    reg [PTR_WIDTH-1:0] rd_gray;

    reg [PTR_WIDTH-1:0] rd_gray_sync_1;
    reg [PTR_WIDTH-1:0] rd_gray_sync_2;
    reg [PTR_WIDTH-1:0] wr_gray_sync_1;
    reg [PTR_WIDTH-1:0] wr_gray_sync_2;

    wire [PTR_WIDTH-1:0] wr_bin_next;
    wire [PTR_WIDTH-1:0] wr_gray_next;
    wire [PTR_WIDTH-1:0] rd_bin_next;
    wire [PTR_WIDTH-1:0] rd_gray_next;
    wire [PTR_WIDTH-1:0] wr_bin_plus_one;
    wire [PTR_WIDTH-1:0] wr_gray_plus_one;
    wire                  wr_fire;
    wire                  rd_fire;

    assign wr_fire = wr_en && !full;
    assign rd_fire = rd_en && !empty;

    assign wr_bin_next  = wr_bin + wr_fire;
    assign wr_gray_next = (wr_bin_next >> 1) ^ wr_bin_next;

    assign rd_bin_next  = rd_bin + rd_fire;
    assign rd_gray_next = (rd_bin_next >> 1) ^ rd_bin_next;

    assign wr_bin_plus_one  = wr_bin + 1'b1;
    assign wr_gray_plus_one  = (wr_bin_plus_one >> 1) ^ wr_bin_plus_one;

    assign rd_data = mem[rd_bin[ADDR_WIDTH-1:0]];

    assign full = (wr_gray_plus_one == {~rd_gray_sync_2[PTR_WIDTH-1:PTR_WIDTH-2], rd_gray_sync_2[PTR_WIDTH-3:0]});
    assign empty = (rd_gray == wr_gray_sync_2);

    always @(posedge wr_clk or negedge wr_rst_n) begin
        if (!wr_rst_n) begin
            wr_bin <= {PTR_WIDTH{1'b0}};
            wr_gray <= {PTR_WIDTH{1'b0}};
            rd_gray_sync_1 <= {PTR_WIDTH{1'b0}};
            rd_gray_sync_2 <= {PTR_WIDTH{1'b0}};
        end else begin
            rd_gray_sync_1 <= rd_gray;
            rd_gray_sync_2 <= rd_gray_sync_1;

            if (wr_fire)
                mem[wr_bin[ADDR_WIDTH-1:0]] <= wr_data;

            wr_bin <= wr_bin_next;
            wr_gray <= wr_gray_next;
        end
    end

    always @(posedge rd_clk or negedge rd_rst_n) begin
        if (!rd_rst_n) begin
            rd_bin <= {PTR_WIDTH{1'b0}};
            rd_gray <= {PTR_WIDTH{1'b0}};
            wr_gray_sync_1 <= {PTR_WIDTH{1'b0}};
            wr_gray_sync_2 <= {PTR_WIDTH{1'b0}};
        end else begin
            wr_gray_sync_1 <= wr_gray;
            wr_gray_sync_2 <= wr_gray_sync_1;

            rd_bin <= rd_bin_next;
            rd_gray <= rd_gray_next;
        end
    end

endmodule