`timescale 1ns/1ps

module vga_out (
    input  wire       CLOCK_50,
    input  wire       rst_n,
    input  wire [7:0] iVideo_R,
    input  wire [7:0] iVideo_G,
    input  wire [7:0] iVideo_B,
    input  wire       iVideo_Valid,
    input  wire       iV_Sync,
    input  wire       iH_Sync,

    output reg  [7:0] VGA_R,
    output reg  [7:0] VGA_G,
    output reg  [7:0] VGA_B,
    output reg        VGA_HS,
    output reg        VGA_VS,
    output reg        VGA_CLK,      // Clean 25MHz Toggle Output for DAC
    output reg        oPixelReadEn,
    output wire       VGA_BLANK_N,
    output wire       VGA_SYNC_N
);

    wire rst = !rst_n;

    // Generate a Clock Enable pulse every 2 cycles (True 25 MHz pace)
    reg clk_en;
    always @(posedge CLOCK_50 or posedge rst) begin
        if (rst) begin
            clk_en  <= 1'b0;
            VGA_CLK <= 1'b0;
        end else begin
            clk_en  <= !clk_en; // High every second 50MHz cycle
            VGA_CLK <= !VGA_CLK; // Balanced 25MHz square wave for external DAC chip
        end
    end

    // VGA Timing Constants (640x480 @ 60Hz)
    parameter H_ACTIVE      = 640;
    parameter H_FRONT_PORCH = 16;
    parameter H_SYNC_PULSE  = 96;
    parameter H_BACK_PORCH  = 48;
    parameter H_TOTAL       = 800; 

    parameter V_ACTIVE      = 480;
    parameter V_FRONT_PORCH = 10;
    parameter V_SYNC_PULSE  = 2;
    parameter V_BACK_PORCH  = 33;
    parameter V_TOTAL       = 525; 

    reg [9:0] h_count;
    reg [9:0] v_count;

    // Run ALL logic synchronously on CLOCK_50, gated by clk_en
    always @(posedge CLOCK_50 or posedge rst) begin
        if (rst) begin
            h_count <= 10'd0;
            v_count <= 10'd0;
        end else if (clk_en) begin
            // Horizontal Counter
            if (h_count == (H_TOTAL - 1))
                h_count <= 10'd0;
            else
                h_count <= h_count + 1'b1;

            // Vertical Counter
            if (h_count == (H_TOTAL - 1)) begin
                if (v_count == (V_TOTAL - 1))
                    v_count <= 10'd0;
                else
                    v_count <= v_count + 1'b1;
            end
        end
    end

    // Registered Sync Signals aligned with counters
    always @(posedge CLOCK_50 or posedge rst) begin
        if (rst) begin
            VGA_HS <= 1'b1;
            VGA_VS <= 1'b1;
        end else if (clk_en) begin
            VGA_HS <= !((h_count >= (H_ACTIVE + H_FRONT_PORCH)) && 
                        (h_count < (H_ACTIVE + H_FRONT_PORCH + H_SYNC_PULSE)));
            
            VGA_VS <= !((v_count >= (V_ACTIVE + V_FRONT_PORCH)) && 
                        (v_count < (V_ACTIVE + V_FRONT_PORCH + V_SYNC_PULSE)));
        end
    end

    wire video_on = (h_count < H_ACTIVE) && (v_count < V_ACTIVE);
    assign VGA_BLANK_N = video_on; 
    assign VGA_SYNC_N  = 1'b0;     

    // Latched Output Pipeline to prevent glitching on display
    always @(posedge CLOCK_50 or posedge rst) begin
        if (rst) begin
            VGA_R <= 8'h00;
            VGA_G <= 8'h00;
            VGA_B <= 8'h00;
            oPixelReadEn <= 1'b0;
        end else if (clk_en) begin
            oPixelReadEn <= video_on && iVideo_Valid;

            if (video_on && iVideo_Valid) begin
                // WARNING: Directly sampling across clock domains will still jitter!
                VGA_R <= iVideo_R;
                VGA_G <= iVideo_G;
                VGA_B <= iVideo_B;
            end else begin
                VGA_R <= 8'h00;
                VGA_G <= 8'h00;
                VGA_B <= 8'h00;
            end
        end
    end

endmodule
