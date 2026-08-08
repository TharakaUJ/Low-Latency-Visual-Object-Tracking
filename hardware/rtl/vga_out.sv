`timescale 1ns/1ps

module vga_out (
    input  wire       CLOCK_50,
    input  wire [7:0] rst_n,
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
    output reg        VGA_CLK,      // VGA Pixel Clock (25 MHz)
    output wire       VGA_BLANK_N,
    output wire       VGA_SYNC_N
);

    wire rst = !rst_n;

    // 1. Generate 25 MHz Pixel Clock from 50 MHz Clock
    always @(posedge CLOCK_50 or posedge rst) begin
        if (rst)
            VGA_CLK <= 1'b0;
        else
            VGA_CLK <= !VGA_CLK;
    end

    // 2. VGA Timing Constants (640x480 @ 60Hz)
    parameter H_ACTIVE      = 640;
    parameter H_FRONT_PORCH = 16;
    parameter H_SYNC_PULSE  = 96;
    parameter H_BACK_PORCH  = 48;
    parameter H_TOTAL       = 800; // Total horizontal pixels

    parameter V_ACTIVE      = 480;
    parameter V_FRONT_PORCH = 10;
    parameter V_SYNC_PULSE  = 2;
    parameter V_BACK_PORCH  = 33;
    parameter V_TOTAL       = 525; // Total vertical lines

    // 3. Sync Counters
    reg [9:0] h_count;
    reg [9:0] v_count;

    // Horizontal counter loop
    always @(posedge VGA_CLK or posedge rst) begin
        if (rst)
            h_count <= 10'd0;
        else if (h_count == (H_TOTAL - 1))
            h_count <= 10'd0;
        else
            h_count <= h_count + 1'b1;
    end

    // Vertical counter loop
    always @(posedge VGA_CLK or posedge rst) begin
        if (rst)
            v_count <= 10'd0;
        else if (h_count == (H_TOTAL - 1)) begin
            if (v_count == (V_TOTAL - 1))
                v_count <= 10'd0;
            else
                v_count <= v_count + 1'b1;
        end
    end

    // 4. Generate Sync Signals (Active Low)
    always @(posedge VGA_CLK or posedge rst) begin
        if (rst) begin
            VGA_HS <= 1'b1;
            VGA_VS <= 1'b1;
        end else begin
            // HS pulse occurs between Active+FrontPorch and Active+FrontPorch+SyncPulse
            VGA_HS <= !((h_count >= (H_ACTIVE + H_FRONT_PORCH)) && 
                        (h_count < (H_ACTIVE + H_FRONT_PORCH + H_SYNC_PULSE)));
            
            // VS pulse occurs between Active+FrontPorch and Active+FrontPorch+SyncPulse
            VGA_VS <= !((v_count >= (V_ACTIVE + V_FRONT_PORCH)) && 
                        (v_count < (V_ACTIVE + V_FRONT_PORCH + V_SYNC_PULSE)));
        end
    end

    // 5. Blanking & Signal Control for ADV7123 DAC
    // Video is active only when counters are within display dimensions
    wire video_on = (h_count < H_ACTIVE) && (v_count < V_ACTIVE);
    
    assign VGA_BLANK_N = video_on; 
    assign VGA_SYNC_N  = 1'b0;     // Not using Sync-on-Green

    // 6. Test Pattern Generation (8 Vertical Color Bars)
    always @(posedge VGA_CLK or posedge rst) begin
        if (rst) begin
            VGA_R <= 8'h00;
            VGA_G <= 8'h00;
            VGA_B <= 8'h00;
        end else if (video_on) begin
            VGA_R <= iVideo_R;
            VGA_G <= iVideo_G;
            VGA_B <= iVideo_B;
            
        end else begin
            VGA_R <= 8'h00;
            VGA_G <= 8'h00;
            VGA_B <= 8'h00;
        end
    end

endmodule