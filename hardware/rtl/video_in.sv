`timescale 1ns / 1ps

module video_in # (
    parameter integer grey_scale = 0
)(
    input  wire       iCLK_50,
    input  wire       iRST_N,

    // TV Decoder Hardware Pins (Bypassed internally)
    input  wire       TD_CLK27,
    input  wire [7:0] TD_DATA,
    input  wire       TD_HS,
    input  wire       TD_VS,
    output wire       TD_RESET_N,

    // Decoded Video Output Interface (RGB Format)
    output reg  [7:0] oVideo_R,    // Red channel
    output reg  [7:0] oVideo_G,    // Green channel
    output reg  [7:0] oVideo_B,    // Blue channel
    output reg        oVideo_Valid,// High when valid pixel data is present
    output reg        oV_Sync,     // Processed Vertical Sync
    output reg        oH_Sync,     // Processed Horizontal Sync
    output wire [7:0] debug_led
);

    // Keep safe constants for hardware assignments
    assign TD_RESET_N = iRST_N;
    assign debug_led  = 8'hA5; // Fixed pattern for visualization

    // =======================================================
    // NTSC 27MHz Timing Constants (Standard 858x525 Frame)
    // =======================================================
    localparam H_ACTIVE     = 720;
    localparam H_FRONT_PORCH= 16;
    localparam H_SYNC_WIDTH = 64;
    localparam H_BACK_PORCH = 58;
    localparam H_TOTAL      = H_ACTIVE + H_FRONT_PORCH + H_SYNC_WIDTH + H_BACK_PORCH; // 858

    localparam V_ACTIVE     = 485;
    localparam V_FRONT_PORCH= 4;
    localparam V_SYNC_WIDTH = 3;
    localparam V_BACK_PORCH = 33;
    localparam V_TOTAL      = V_ACTIVE + V_FRONT_PORCH + V_SYNC_WIDTH + V_BACK_PORCH; // 525

    // Width of each color bar (720 active pixels / 8 bars = 90 pixels per bar)
    localparam BAR_WIDTH    = 90;

    // Internal XY Scan Counters
    reg [9:0] h_cnt;
    reg [9:0] v_cnt;

    // =======================================================
    // Sync and Active Region Generation
    // =======================================================
    always @(posedge TD_CLK27 or negedge iRST_N) begin
        if (!iRST_N) begin
            h_cnt        <= 10'd0;
            v_cnt        <= 10'd0;
            oH_Sync      <= 1'b1;
            oV_Sync      <= 1'b1;
            oVideo_Valid <= 1'b0;
        end else begin
            // Horizontal Counter
            if (h_cnt == (H_TOTAL - 1)) begin
                h_cnt <= 10'd0;
                // Vertical Counter
                if (v_cnt == (V_TOTAL - 1)) begin
                    v_cnt <= 10'd0;
                end else begin
                    v_cnt <= v_cnt + 1'b1;
                end
            end else begin
                h_cnt <= h_cnt + 1'b1;
            end

            // Generate Active Video Window Flag
            if ((h_cnt < H_ACTIVE) && (v_cnt < V_ACTIVE)) begin
                oVideo_Valid <= 1'b1;
            end else begin
                oVideo_Valid <= 1'b0;
            end

            // Generate Active-Low H_Sync (Matches typical NTSC TV sync polarity)
            if ((h_cnt >= (H_ACTIVE + H_FRONT_PORCH)) && 
                (h_cnt < (H_ACTIVE + H_FRONT_PORCH + H_SYNC_WIDTH))) begin
                oH_Sync <= 1'b0;
            end else begin
                oH_Sync <= 1'b1;
            end

            // Generate Active-Low V_Sync
            if ((v_cnt >= (V_ACTIVE + V_FRONT_PORCH)) && 
                (v_cnt < (V_ACTIVE + V_FRONT_PORCH + V_SYNC_WIDTH))) begin
                oV_Sync <= 1'b0;
            end else begin
                oV_Sync <= 1'b1;
            end
        end
    end

    // =======================================================
    // 8-Color Bar Generator Matrix
    // =======================================================
    always @(posedge TD_CLK27 or negedge iRST_N) begin
        if (!iRST_N) begin
            oVideo_R <= 8'h00;
            oVideo_G <= 8'h00;
            oVideo_B <= 8'h00;
        end else if (oVideo_Valid) begin
            if (grey_scale) begin
                // Grayscale gradient staircase step down
                case (h_cnt / BAR_WIDTH)
                    3'd0: begin oVideo_R <= 8'hFF; oVideo_G <= 8'hFF; oVideo_B <= 8'hFF; end // White
                    3'd1: begin oVideo_R <= 8'hDB; oVideo_G <= 8'hDB; oVideo_B <= 8'hDB; end 
                    3'd2: begin oVideo_R <= 8'hB6; oVideo_G <= 8'hB6; oVideo_B <= 8'hB6; end 
                    3'd3: begin oVideo_R <= 8'h92; oVideo_G <= 8'h92; oVideo_B <= 8'h92; end 
                    3'd4: begin oVideo_R <= 8'h6D; oVideo_G <= 8'h6D; oVideo_B <= 8'h6D; end 
                    3'd5: begin oVideo_R <= 8'h49; oVideo_G <= 8'h49; oVideo_B <= 8'h49; end 
                    3'd6: begin oVideo_R <= 8'h24; oVideo_G <= 8'h24; oVideo_B <= 8'h24; end 
                    default: begin oVideo_R <= 8'h00; oVideo_G <= 8'h00; oVideo_B <= 8'h00; end // Black
                endcase
            end else begin
                // Standard 8 Color Bars: White, Yellow, Cyan, Green, Magenta, Red, Blue, Black
                case (h_cnt / BAR_WIDTH)
                    3'd0: begin oVideo_R <= 8'hFF; oVideo_G <= 8'hFF; oVideo_B <= 8'hFF; end // White
                    3'd1: begin oVideo_R <= 8'hFF; oVideo_G <= 8'hFF; oVideo_B <= 8'h00; end // Yellow
                    3'd2: begin oVideo_R <= 8'h00; oVideo_G <= 8'hFF; oVideo_B <= 8'hFF; end // Cyan
                    3'd3: begin oVideo_R <= 8'h00; oVideo_G <= 8'hFF; oVideo_B <= 8'h00; end // Green
                    3'd4: begin oVideo_R <= 8'hFF; oVideo_G <= 8'h00; oVideo_B <= 8'hFF; end // Magenta
                    3'd5: begin oVideo_R <= 8'hFF; oVideo_G <= 8'h00; oVideo_B <= 8'h00; end // Red
                    3'd6: begin oVideo_R <= 8'h00; oVideo_G <= 8'h00; oVideo_B <= 8'hFF; end // Blue
                    default: begin oVideo_R <= 8'h00; oVideo_G <= 8'h00; oVideo_B <= 8'h00; end // Black
                endcase
            end
        end else begin
            // Blanking period values must be completely zeroed out
            oVideo_R <= 8'h00;
            oVideo_G <= 8'h00;
            oVideo_B <= 8'h00;
        end
    end

endmodule
