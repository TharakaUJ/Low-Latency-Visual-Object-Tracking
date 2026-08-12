`timescale 1ns / 1ps

module top (
    input  wire       CLOCK_50,
    input  wire [0:0] KEY,          // Reset button (KEY0)
    
    // DE2-115 VGA Port Connections
    output wire [7:0] VGA_R,
    output wire [7:0] VGA_G,
    output wire [7:0] VGA_B,
    output wire       VGA_CLK,
    output wire       VGA_HS,
    output wire       VGA_VS,
    output wire       VGA_BLANK_N,
    output wire       VGA_SYNC_N,

    output wire       I2C_SCLK,
    inout  wire       I2C_SDAT,

    // TV Decoder Hardware Pins (From ADV7181B chip)
    input  wire       TD_CLK27,
    input  wire [7:0] TD_DATA,
    input  wire       TD_HS,
    input  wire       TD_VS,
    output wire       TD_RESET_N,

    output wire [7:0] LEDR,
    output wire [7:0] LEDG,
    input wire [7:0] SW
);

    // Instantiate Video Input Decoder
    wire [7:0] video_in_R, video_in_G, video_in_B;
    wire       video_valid, v_sync, h_sync;

    localparam integer PIXEL_STREAM_WIDTH = 26;
    localparam integer PIXEL_FIFO_ADDR_WIDTH = 9;

    wire [PIXEL_STREAM_WIDTH-1:0] pixel_fifo_wr_data;
    wire [PIXEL_STREAM_WIDTH-1:0] pixel_fifo_rd_data;
    wire                          pixel_fifo_full;
    wire                          pixel_fifo_empty;
    wire                          pixel_fifo_wr_en;
    wire                          pixel_fifo_rd_en;

    assign pixel_fifo_wr_data = {v_sync, h_sync, video_in_R, video_in_G, video_in_B};
    assign pixel_fifo_wr_en   = video_valid && !pixel_fifo_full;

    wire [7:0] vga_fifo_R = pixel_fifo_rd_data[23:16];
    wire [7:0] vga_fifo_G = pixel_fifo_rd_data[15:8];
    wire [7:0] vga_fifo_B = pixel_fifo_rd_data[7:0];
    wire       vga_fifo_H = pixel_fifo_rd_data[24];
    wire       vga_fifo_V = pixel_fifo_rd_data[25];


    wire ack, trn_end, ack_enable;

    assign LEDR[0] = ack;
    assign LEDR[1] = trn_end;
    assign LEDR[2] = ack_enable;
    assign LEDR[3] = video_valid;
    assign LEDR[4] = pixel_fifo_full;
    assign LEDR[5] = pixel_fifo_empty;
    assign LEDR[6] = pixel_fifo_rd_en;
    assign LEDR[7] = pixel_fifo_wr_en;

    video_in video_in_decoder (
        .iCLK_50(CLOCK_50),
        .iRST_N(KEY[0]),
        .TD_CLK27(TD_CLK27),
        .TD_DATA(TD_DATA),
        .TD_HS(TD_HS),
        .TD_VS(TD_VS),
        .TD_RESET_N(TD_RESET_N),
        .oVideo_R(video_in_R),
        .oVideo_G(video_in_G),
        .oVideo_B(video_in_B),
        .oVideo_Valid(video_valid),
        .oV_Sync(v_sync),
        .oH_Sync(h_sync),
        .debug_led(LEDG[7:0])
    );

    async_fifo #(
        .DATA_WIDTH(PIXEL_STREAM_WIDTH),
        .ADDR_WIDTH(PIXEL_FIFO_ADDR_WIDTH)
    ) pixel_stream_fifo (
        .wr_clk(TD_CLK27),
        .wr_rst_n(KEY[0]),
        .wr_en(pixel_fifo_wr_en),
        .wr_data(pixel_fifo_wr_data),
        .full(pixel_fifo_full),
        .rd_clk(CLOCK_50),
        .rd_rst_n(KEY[0] & SW[0]),
        .rd_en(pixel_fifo_rd_en),
        .rd_data(pixel_fifo_rd_data),
        .empty(pixel_fifo_empty)
    );

    vga_out vga_output (
        .CLOCK_50(CLOCK_50),
        .rst_n(KEY[0] & SW[0]),
        .iVideo_R(vga_fifo_R),
        .iVideo_G(vga_fifo_G),
        .iVideo_B(vga_fifo_B),
        .iVideo_Valid(!pixel_fifo_empty),
        .iV_Sync(vga_fifo_V),
        .iH_Sync(vga_fifo_H),
        .VGA_R(VGA_R),
        .VGA_G(VGA_G),
        .VGA_B(VGA_B),
        .VGA_HS(VGA_HS),
        .VGA_VS(VGA_VS),
        .VGA_CLK(VGA_CLK),
        .oPixelReadEn(pixel_fifo_rd_en),
        .VGA_BLANK_N(VGA_BLANK_N),
        .VGA_SYNC_N(VGA_SYNC_N)
    );

    I2C_Master i2c_master (
        .I2C_clk(CLOCK_50),
        .RESET(KEY[0]),
        .I2C_SCLK(I2C_SCLK),
        .I2C_SDATA(I2C_SDAT),
        .TRN_END(trn_end),
        .ACK(ack),
        .ACK_enable(ack_enable)
    );


endmodule