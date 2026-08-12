`timescale 1ns / 1ps

module video_in # (
    parameter integer grey_scale = 0
)(
    input  wire       iCLK_50,
    input  wire       iRST_N,

    // TV Decoder Hardware Pins (From ADV7181B chip)
    input  wire       TD_CLK27,
    input  wire [7:0] TD_DATA,
    input  wire       TD_HS,
    input  wire       TD_VS,
    output wire       TD_RESET_N,

    // Decoded Video Output Interface (RGB Format)
    output wire [7:0] oVideo_R,    // Red channel
    output wire [7:0] oVideo_G,    // Green channel
    output wire [7:0] oVideo_B,    // Blue channel
    output reg        oVideo_Valid,// High when valid pixel data is present
    output reg        oV_Sync,     // Processed Vertical Sync
    output reg        oH_Sync,     // Processed Horizontal Sync
    output wire [7:0] debug_led
);

    assign TD_RESET_N = iRST_N;
    assign debug_led  = TD_DATA; 

    // Pipeline Registers
    reg [7:0] rData_d1;
    reg       rHS_d1;
    reg       rVS_d1;
    reg       rHS_d2; 
    
    reg [1:0] rPixel_Count;
    reg [7:0] Y, U, V;

    // Detect the rising edge of HS relative to the d1 registered domain
    wire hs_rising_edge = (rHS_d1 && !rHS_d2);

    always @(posedge TD_CLK27 or negedge iRST_N) begin
        if (!iRST_N) begin
            rData_d1     <= 8'h00;
            rHS_d1       <= 1'b0;
            rVS_d1       <= 1'b0;
            rHS_d2       <= 1'b0;
            Y            <= 8'h00;
            U            <= 8'h80; 
            V            <= 8'h80; 
            oVideo_Valid <= 1'b0;
            oV_Sync      <= 1'b0;
            oH_Sync      <= 1'b0;
            rPixel_Count <= 2'b00;
        end else begin
            // Stage 1: Register inputs directly from the chip
            rData_d1 <= TD_DATA;
            rHS_d1   <= TD_HS;
            rVS_d1   <= TD_VS;
            
            // Stage 2: Secondary delay for edge matching
            rHS_d2   <= rHS_d1;

            // Align sync signals with the 1-clock data capture delay
            oH_Sync  <= rHS_d1;
            oV_Sync  <= rVS_d1;

            // Enforce stream discipline 
            if (hs_rising_edge && rVS_d1) begin
                // Line starts exactly here. Capture first byte (U/Cb) immediately.
                oVideo_Valid <= 1'b1;
                U            <= rData_d1; // First byte of YUV422 is typically U (Cb)
                rPixel_Count <= 2'b01;    // Next byte will be Y0 (2'b01)
            end else if (rHS_d1 && rVS_d1) begin
                oVideo_Valid <= 1'b1;
                rPixel_Count <= rPixel_Count + 1'b1;

                case (rPixel_Count)
                    2'b00: U <= rData_d1; // Cb
                    2'b01: Y <= rData_d1; // Y0
                    2'b10: V <= rData_d1; // Cr
                    2'b11: Y <= rData_d1; // Y1
                endcase
            end else begin
                oVideo_Valid <= 1'b0;
                rPixel_Count <= 2'b00;
            end
        end
    end

    // =======================================================
    // YCbCr to RGB Color Space Conversion (Combinational)
    // =======================================================
    
    function [7:0] clamp;
        input signed [31:0] val;
        begin
            if (val < 0)
                clamp = 8'd0;
            else if (val > 255)
                clamp = 8'd255;
            else
                clamp = val[7:0];
        end
    endfunction

    wire signed [31:0] C = $signed({1'b0, Y}) - 32'sd16;
    wire signed [31:0] D = $signed({1'b0, U}) - 32'sd128;
    wire signed [31:0] E = $signed({1'b0, V}) - 32'sd128;

    assign oVideo_R = (grey_scale) ? Y : clamp((298 * C             + 409 * E + 128) >>> 8);
    assign oVideo_G = (grey_scale) ? Y : clamp((298 * C - 100 * D - 208 * E + 128) >>> 8);
    assign oVideo_B = (grey_scale) ? Y : clamp((298 * C + 516 * D           + 128) >>> 8);

    // reg [9:0] test_x;
    // always @(posedge TD_CLK27) begin
    //     if (hs_rising_edge) test_x <= 0;
    //     else if (oVideo_Valid) test_x <= test_x + 1;
    // end

    // // Bypass the TV chip data entirely to test your VGA path
    // assign oVideo_G = (test_x < 10) ? 8'hFF : 8'h00; // Solid Red vertical bar
    // assign oVideo_R = 8'h00;
    // assign oVideo_B = 8'h00;

endmodule
