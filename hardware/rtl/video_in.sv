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
    output reg        oH_Sync      // Processed Horizontal Sync
);

    assign TD_RESET_N = iRST_N;

    reg [7:0] rData_d1;
    reg       rHS_d1;
    reg       rVS_d1;
    reg [1:0] rPixel_Count;
    
    // Internal registers to hold the extracted YCbCr components
    reg [7:0] Y, U, V;

    always @(posedge TD_CLK27 or negedge iRST_N) begin
        if (!iRST_N) begin
            rData_d1     <= 8'h00;
            rHS_d1       <= 1'b0;
            rVS_d1       <= 1'b0;
            Y            <= 8'h00;
            U            <= 8'h80; // 128 is neutral chroma (no color)
            V            <= 8'h80; // 128 is neutral chroma (no color)
            oVideo_Valid <= 1'b0;
            oV_Sync      <= 1'b0;
            oH_Sync      <= 1'b0;
            rPixel_Count <= 2'b00;
        end else begin
            rData_d1 <= TD_DATA;
            rHS_d1   <= TD_HS;
            rVS_d1   <= TD_VS;
            
            // Replicate synchronization signals 
            oH_Sync <= rHS_d1;
            oV_Sync <= rVS_d1;

            if (!rHS_d1 && !rVS_d1) begin
                oVideo_Valid <= 1'b1;
                rPixel_Count <= rPixel_Count + 1'b1;
                
                case (rPixel_Count)
                    2'b00: U <= rData_d1; // Cb (U) Channel
                    2'b01: Y <= rData_d1; // Luma (Y0)
                    2'b10: V <= rData_d1; // Cr (V) Channel
                    2'b11: Y <= rData_d1; // Luma (Y1)
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
    
    // Clamping function to prevent color wrapping artifacts 
    // (e.g., negative values wrapping to pure white)
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

    // Standard ITU-R BT.601 integer math
    // Ensure all operands are strictly signed to prevent implicit unsigned conversions
    wire signed [31:0] C = $signed({1'b0, Y}) - 32'sd16;
    wire signed [31:0] D = $signed({1'b0, U}) - 32'sd128;
    wire signed [31:0] E = $signed({1'b0, V}) - 32'sd128;

    // R = clip( ( 298 * C           + 409 * E + 128) >> 8 )
    // G = clip( ( 298 * C - 100 * D - 208 * E + 128) >> 8 )
    // B = clip( ( 298 * C + 516 * D           + 128) >> 8 )
    
    assign oVideo_R = (grey_scale) ? Y : clamp((298 * C             + 409 * E + 128) >>> 8);
    assign oVideo_G = (grey_scale) ? Y : clamp((298 * C - 100 * D - 208 * E + 128) >>> 8);
    assign oVideo_B = (grey_scale) ? Y : clamp((298 * C + 516 * D           + 128) >>> 8);

endmodule