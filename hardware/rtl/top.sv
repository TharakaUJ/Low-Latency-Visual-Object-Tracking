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

    // TV Decoder Hardware Pins (From ADV7181B chip)
    input  wire       TD_CLK27,
    input  wire [7:0] TD_DATA,
    input  wire       TD_HS,
    input  wire       TD_VS,
    output wire       TD_RESET_N
);

    // Instantiate Video Input Decoder
    wire [7:0] video_in_R, video_in_G, video_in_B;
    wire       video_valid, v_sync, h_sync;

    assign TD_RESET_N = KEY[0];

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
        .oH_Sync(h_sync)
    );

    vga_out vga_output (
        .CLOCK_50(CLOCK_50),
        .rst_n(KEY[0]),
        .iVideo_R(video_in_R),
        .iVideo_G(video_in_G),
        .iVideo_B(video_in_B),
        .iVideo_Valid(video_valid),
        .iV_Sync(v_sync),
        .iH_Sync(h_sync),
        .VGA_R(VGA_R),
        .VGA_G(VGA_G),
        .VGA_B(VGA_B),
        .VGA_HS(VGA_HS),
        .VGA_VS(VGA_VS),
        .VGA_CLK(VGA_CLK),
        .VGA_BLANK_N(VGA_BLANK_N),
        .VGA_SYNC_N(VGA_SYNC_N)
    );


endmodule