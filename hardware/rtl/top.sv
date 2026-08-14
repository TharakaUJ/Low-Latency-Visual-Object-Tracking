`timescale 1ns / 1ps

module top (
    input  wire        CLOCK_50,
    input  wire  [0:0] KEY,          // Reset button (KEY0)

    // DE2-115 VGA Port Connections
    output wire  [7:0] VGA_R,
    output wire  [7:0] VGA_G,
    output wire  [7:0] VGA_B,
    output wire        VGA_CLK,
    output wire        VGA_HS,
    output wire        VGA_VS,
    output wire        VGA_BLANK_N,
    output wire        VGA_SYNC_N,

    // TV Decoder Hardware Pins (From ADV7181B chip)
    input  wire        TD_CLK27,
    input  wire  [7:0] TD_DATA,
    input  wire        TD_HS,
    input  wire        TD_VS,
    output wire        TD_RESET_N,
    
    // I2C Configuration (REQUIRED to initialize TV Decoder)
    output wire        I2C_SCLK,
    inout  wire        I2C_SDAT,

    output wire  [17:0] LEDR,
    output wire  [8:0] LEDG,
    input  wire  [7:0] SW,

    // DE2-115 32-bit SDRAM pins
    output wire        DRAM_CLK,     // Added missing SDRAM Clock
    output wire        DRAM_CKE,
    output wire        DRAM_CS_N,
    output wire        DRAM_RAS_N,
    output wire        DRAM_CAS_N,
    output wire        DRAM_WE_N,
    output wire  [1:0] DRAM_BA,
    output wire [12:0] DRAM_ADDR,
    output wire  [3:0] DRAM_DQM,     // Corrected to 4-bit (DE2-115)
    inout  wire [31:0] DRAM_DQ       // Corrected to 32-bit (DE2-115)
);

    // Instantiate Video Input Decoder
    wire [7:0] video_in_R, video_in_G, video_in_B;
    localparam integer PIXEL_STREAM_WIDTH = 26;
    wire       video_valid, v_sync, h_sync;
    localparam integer PIXEL_FIFO_ADDR_WIDTH = 11; // larger depth for SDRAM burst buffering
    localparam integer SOURCE_ACTIVE_WIDTH  = 720;
    localparam integer TARGET_ACTIVE_WIDTH  = 640;
    localparam integer TARGET_ACTIVE_HEIGHT = 480;
    localparam integer H_CROP_START         = (SOURCE_ACTIVE_WIDTH - TARGET_ACTIVE_WIDTH) / 2;
    localparam integer H_CROP_END           = H_CROP_START + TARGET_ACTIVE_WIDTH;
    // Both the ping-pong frame buffer and the SDRAM master's own read/write
    // pointers must wrap at exactly TARGET_ACTIVE_WIDTH*TARGET_ACTIVE_HEIGHT*2
    // words -- i.e. the amount of data actually written per CROPPED frame
    // (2 x 16-bit beats per pixel). Both modules previously defaulted to
    // 720x480, but only 640x480 pixels are ever written after the H-crop,
    // so the internal write_ptr/read_ptr never wrapped at the same point
    // that frame_buffer_controller swapped ping-pong buffers. That drift
    // is a likely cause of the screen not being fully/correctly covered.
    localparam integer FRAME_WORDS_CROPPED  = TARGET_ACTIVE_WIDTH * TARGET_ACTIVE_HEIGHT * 2;

    // 1) Capture FIFO: asynchronous capture from TV domain into 50MHz domain
    wire [PIXEL_STREAM_WIDTH-1:0] pixel_capture_wr_data;
    wire [PIXEL_STREAM_WIDTH-1:0] pixel_capture_rd_data;
    wire                          pixel_capture_full;
    wire                          pixel_capture_empty;
    wire                          pixel_capture_wr_en;
    reg                           pixel_capture_rd_en_reg;
    wire                          pixel_capture_rd_en = pixel_capture_rd_en_reg;
    reg  [9:0]                    source_x_count;
    reg                           h_sync_d;
    wire                          cropped_pixel_valid;

    assign pixel_capture_wr_data = {v_sync, h_sync, video_in_R, video_in_G, video_in_B};
    assign cropped_pixel_valid    = video_valid && (source_x_count >= H_CROP_START) && (source_x_count < H_CROP_END);
    assign pixel_capture_wr_en    = cropped_pixel_valid && !pixel_capture_full;

    // 2) SDRAM Write FIFO: burst buffer that the SDRAM master will drain
    wire [PIXEL_STREAM_WIDTH-1:0] sdram_wr_rd_data;
    wire [PIXEL_STREAM_WIDTH-1:0] sdram_wr_wr_data;
    wire                          sdram_wr_full;
    wire                          sdram_wr_empty;
    reg                           sdram_wr_wr_en_reg;
    wire                          sdram_wr_wr_en = sdram_wr_wr_en_reg;
    reg                           sdram_wr_rd_en_reg;

    // 3) SDRAM Read FIFO: burst buffer filled by SDRAM master and consumed by VGA
    wire [PIXEL_STREAM_WIDTH-1:0] sdram_rd_rd_data;
    wire                          sdram_rd_full;
    wire                          sdram_rd_empty;
    wire                          sdram_rd_rd_en; // driven by vga_out.oPixelReadEn

    wire [15:0] sdram_ctrl_wr_data;
    wire        sdram_ctrl_wr_empty;
    wire        sdram_ctrl_wr_rd_en;
    wire [15:0] sdram_ctrl_rd_wr_data;
    wire        sdram_ctrl_rd_wr_en;

    reg         sdram_wr_bridge_pending;
    reg [1:0]   sdram_wr_bridge_phase;
    reg [25:0]  sdram_wr_pixel_reg;
    reg [15:0]  sdram_ctrl_wr_data_reg;
    reg [15:0]  sdram_rd_lower_reg;
    reg [1:0]   sdram_rd_bridge_phase;
    reg         sdram_rd_fifo_wr_en_reg;
    reg [25:0]  sdram_rd_fifo_wr_data_reg;

    assign sdram_ctrl_wr_empty = !sdram_wr_bridge_pending && sdram_wr_empty;
    wire [7:0] vga_fifo_R = sdram_rd_rd_data[23:16];
    wire [7:0] vga_fifo_G = sdram_rd_rd_data[15:8];
    wire [7:0] vga_fifo_B = sdram_rd_rd_data[7:0];
    wire       vga_fifo_H = sdram_rd_rd_data[24];
    wire       vga_fifo_V = sdram_rd_rd_data[25];





    assign LEDR[7:0] = vga_fifo_R[7:0]; // Debug: show the last pixel written to the SDRAM read FIFO
    assign LEDR[15:8] = vga_fifo_B[7:0]; // Debug: show the last pixel written to the SDRAM read FIFO
    assign LEDR[16] = pll_locked; // Debug: PLL locked
    assign LEDR[17] = sdram_rd_empty; // Debug: SDRAM read FIFO empty
    // (previously wired to clk_sdram_shifted -- driving a free-running
    // ~100MHz clock onto an LED does not show anything useful and the
    // comment already claimed it was meant to show the read-FIFO-empty
    // status, so it's fixed to actually do that.)


    // PLL: generates the SDRAM-domain clock and a phase-shifted DRAM_CLK
    wire clk_sys;      // replaces CLOCK_50 for all SDRAM/VGA/logic domains
    wire clk_sdram_shifted;
    wire pll_locked;

    sdram_pll sdram_pll_inst (
        .inclk0 (CLOCK_50),
        .c0     (clk_sys),            // 0 degrees -- system/controller clock
        .c1     (clk_sdram_shifted),  // -3ns shift -- physical SDRAM clock
        .locked (pll_locked)
    );

    assign DRAM_CLK = clk_sdram_shifted;

    // Combine the button reset with PLL lock so nothing runs until the
    // clock is stable
    wire rst_n_sys = KEY[0] & pll_locked;

    video_in video_in_decoder (
        .iCLK_50(clk_sys),
        .iRST_N(rst_n_sys),
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

    // Capture FIFO: asynchronous FIFO to safely transfer TV pixels into 50MHz domain
    async_fifo #(
        .DATA_WIDTH(PIXEL_STREAM_WIDTH),
        .ADDR_WIDTH(PIXEL_FIFO_ADDR_WIDTH)
    ) pixel_capture_fifo (
        .wr_clk(TD_CLK27),
        .wr_rst_n(rst_n_sys),
        .wr_en(pixel_capture_wr_en),
        .wr_data(pixel_capture_wr_data),
        .full(pixel_capture_full),
        .rd_clk(clk_sys),
        .rd_rst_n(rst_n_sys & SW[0]),
        .rd_en(pixel_capture_rd_en),
        .rd_data(pixel_capture_rd_data),
        .empty(pixel_capture_empty)
    );

    // SDRAM write FIFO: holds bursts to feed the SDRAM master engine
    async_fifo #(
        .DATA_WIDTH(PIXEL_STREAM_WIDTH),
        .ADDR_WIDTH(PIXEL_FIFO_ADDR_WIDTH)
    ) sdram_wr_fifo (
        .wr_clk(clk_sys),
        .wr_rst_n(rst_n_sys),
        .wr_en(sdram_wr_wr_en),
        .wr_data(sdram_wr_wr_data),
        .full(sdram_wr_full),
        .rd_clk(clk_sys),
        .rd_rst_n(rst_n_sys),
        .rd_en(sdram_wr_rd_en_reg),
        .rd_data(sdram_wr_rd_data),
        .empty(sdram_wr_empty)
    );

    // SDRAM read FIFO: filled by SDRAM master engine and consumed by VGA
    async_fifo #(
        .DATA_WIDTH(PIXEL_STREAM_WIDTH),
        .ADDR_WIDTH(PIXEL_FIFO_ADDR_WIDTH)
    ) sdram_rd_fifo (
        .wr_clk(clk_sys),
        .wr_rst_n(rst_n_sys),
        .wr_en(sdram_rd_fifo_wr_en_reg),
        .wr_data(sdram_rd_fifo_wr_data_reg),
        .full(sdram_rd_full),
        .rd_clk(clk_sys),
        .rd_rst_n(rst_n_sys & SW[0]),
        .rd_en(sdram_rd_rd_en),
        .rd_data(sdram_rd_rd_data),
        .empty(sdram_rd_empty)
    );

    vga_out vga_output (
        .CLOCK_50(clk_sys),
        .rst_n(rst_n_sys & SW[0]),
        .iVideo_R(vga_fifo_R),
        .iVideo_G(vga_fifo_G),
        .iVideo_B(vga_fifo_B),
        .iVideo_Valid(!sdram_rd_empty),
        .iV_Sync(vga_fifo_V),
        .iH_Sync(vga_fifo_H),
        .VGA_R(VGA_R),
        .VGA_G(VGA_G),
        .VGA_B(VGA_B),
        .VGA_HS(VGA_HS),
        .VGA_VS(VGA_VS),
        .VGA_CLK(VGA_CLK),
        .oPixelReadEn(sdram_rd_rd_en),
        .VGA_BLANK_N(VGA_BLANK_N),
        .VGA_SYNC_N(VGA_SYNC_N)
    );

    // Frame buffer controller for ping-pong SDRAM base addresses
    wire [22:0] sdram_write_base;
    wire [22:0] sdram_read_base;

    // NOTE: TD_VS from the ADV7181B is a field sync for interlaced
    // NTSC/PAL sources -- it pulses twice per full visual frame (once per
    // field), not once. Swapping the write buffer on every edge of it, as
    // done below, means each ping-pong buffer only ever receives ONE
    // field's worth of active lines (~240 of 480) before the buffer is
    // swapped away, leaving the remaining lines full of stale/old data.
    // That alone is enough to explain a picture that doesn't cover the
    // whole screen. Fixing this properly requires decoding field ID (a
    // decoder status pin/register, or embedded field bit) and writing
    // each field's lines to the correct interleaved row -- not implemented
    // here. Confirm with a logic analyzer / ChipScope whether TD_VS is
    // firing once or twice per visible frame before assuming this design
    // even needs it (some ADV7181B configs can be set to output
    // progressively / line-doubled).
    frame_buffer_controller #(
        .WIDTH  (TARGET_ACTIVE_WIDTH),
        .HEIGHT (TARGET_ACTIVE_HEIGHT)
    ) fb_ctrl (
        .clk_tv(TD_CLK27),
        .clk_vga(clk_sys),
        .rst_n(rst_n_sys & SW[0]),
        .tv_frame_done(v_sync),
        .vga_vsync(VGA_VS),
        .sdram_write_base(sdram_write_base),
        .sdram_read_base(sdram_read_base)
    );

    // SDRAM master engine: bridge between the 26-bit pixel FIFOs and the
    // physical SDRAM controller's 16-bit data interface.
    sdram_de2115_controller #(
        .DATA_WIDTH(16),
        .ROW_WIDTH(13),
        .COL_WIDTH(9),
        .BANK_WIDTH(2),
        .FRAME_WORDS(FRAME_WORDS_CROPPED)
    ) sdram_master (
        .clk(clk_sys),
        .rst_n(rst_n_sys & SW[0]),
        .sdram_write_base(sdram_write_base),
        .sdram_read_base(sdram_read_base),
        .sdram_wr_empty(sdram_ctrl_wr_empty),
        .sdram_wr_rd_data(sdram_ctrl_wr_data),
        .sdram_wr_rd_en(sdram_ctrl_wr_rd_en),
        .sdram_rd_full(sdram_rd_full),
        .sdram_rd_wr_en(sdram_ctrl_rd_wr_en),
        .sdram_rd_wr_data(sdram_ctrl_rd_wr_data),
        .DRAM_CKE(DRAM_CKE),
        .DRAM_CS_N(DRAM_CS_N),
        .DRAM_RAS_N(DRAM_RAS_N),
        .DRAM_CAS_N(DRAM_CAS_N),
        .DRAM_WE_N(DRAM_WE_N),
        .DRAM_BA(DRAM_BA),
        .DRAM_ADDR(DRAM_ADDR),
        // sdram_de2115_controller is a 16-bit-wide engine (DATA_WIDTH=16),
        // but the DE2-115's physical SDRAM bus is 32 bits wide (DRAM_DQ[31:0],
        // DRAM_DQM[3:0]). Connecting the 16-bit/2-bit module ports straight
        // to the 32-bit/4-bit top-level ports (as this file did before)
        // silently truncates: DRAM_DQ[31:16] and DRAM_DQM[3:2] are left
        // floating/undriven on the physical pins. A floating DQM input on
        // the SDRAM chip is out-of-spec and can cause it to drive/mask the
        // upper data byte-lanes unpredictably -- risking bus contention
        // with whatever else is on those lines. Explicitly use only the
        // lower 16 bits and permanently mask (disable) the upper 2 DQM
        // bits so the unused half of the bus stays safely deselected.
        .DRAM_DQM(DRAM_DQM[1:0]),
        .DRAM_DQ(DRAM_DQ[15:0])
    );

    assign DRAM_DQM[3:2] = 2'b11; // upper 16 data bits unused -- keep masked/deselected

    // Simple mover: on CLOCK_50 domain move captured pixels into SDRAM write FIFO
    reg [PIXEL_STREAM_WIDTH-1:0] sdram_wr_data_reg;
    always @(posedge TD_CLK27 or negedge rst_n_sys) begin
        if (!rst_n_sys) begin
            source_x_count <= 10'd0;
            h_sync_d <= 1'b0;
        end else begin
            h_sync_d <= h_sync;

            if (h_sync && !h_sync_d) begin
                // Start of a new line: restart horizontal position tracking.
                source_x_count <= 10'd0;
            end else if (video_valid) begin
                if (source_x_count < SOURCE_ACTIVE_WIDTH - 1)
                    source_x_count <= source_x_count + 1'b1;
                else
                    source_x_count <= 10'd0;
            end else begin
                source_x_count <= 10'd0;
            end
        end
    end

    always @(posedge clk_sys or negedge rst_n_sys) begin
        if (!rst_n_sys) begin
            pixel_capture_rd_en_reg <= 1'b0;
            sdram_wr_wr_en_reg <= 1'b0;
            sdram_wr_data_reg <= {PIXEL_STREAM_WIDTH{1'b0}};
            sdram_wr_bridge_pending <= 1'b0;
            sdram_wr_bridge_phase <= 2'd0;
            sdram_wr_pixel_reg <= 26'd0;
            sdram_ctrl_wr_data_reg <= 16'd0;
            sdram_rd_lower_reg <= 16'd0;
            sdram_rd_bridge_phase <= 2'd0;
            sdram_rd_fifo_wr_en_reg <= 1'b0;
            sdram_rd_fifo_wr_data_reg <= 26'd0;
        end else begin
            // Move only cropped pixels when there is captured data and write FIFO has space.
            if (!pixel_capture_empty && !sdram_wr_full) begin
                pixel_capture_rd_en_reg <= 1'b1;
                sdram_wr_wr_en_reg <= 1'b1;
                sdram_wr_data_reg <= pixel_capture_rd_data;
            end else begin
                pixel_capture_rd_en_reg <= 1'b0;
                sdram_wr_wr_en_reg <= 1'b0;
            end

            sdram_wr_rd_en_reg <= 1'b0;
            sdram_rd_fifo_wr_en_reg <= 1'b0;

            // Pack each 26-bit pixel into two 16-bit SDRAM beats.
            if (!sdram_wr_bridge_pending && !sdram_wr_empty) begin
                sdram_wr_pixel_reg <= sdram_wr_rd_data;
                sdram_wr_bridge_pending <= 1'b1;
                sdram_wr_bridge_phase <= 2'd0;
                sdram_wr_rd_en_reg <= 1'b1;
            end

            if (sdram_ctrl_wr_rd_en && sdram_wr_bridge_pending) begin
                if (sdram_wr_bridge_phase == 2'd0) begin
                    sdram_ctrl_wr_data_reg <= sdram_wr_pixel_reg[15:0];
                    sdram_wr_bridge_phase <= 2'd1;
                end else begin
                    sdram_ctrl_wr_data_reg <= {6'b0, sdram_wr_pixel_reg[25:16]};
                    sdram_wr_bridge_pending <= 1'b0;
                    sdram_wr_bridge_phase <= 2'd0;
                end
            end

            // Reassemble each pair of 16-bit SDRAM beats back into a 26-bit pixel.
            if (sdram_ctrl_rd_wr_en) begin
                if (sdram_rd_bridge_phase == 2'd0) begin
                    sdram_rd_lower_reg <= sdram_ctrl_rd_wr_data;
                    sdram_rd_bridge_phase <= 2'd1;
                end else begin
                    sdram_rd_fifo_wr_en_reg <= 1'b1;
                    sdram_rd_fifo_wr_data_reg <= {sdram_ctrl_rd_wr_data[9:0], sdram_rd_lower_reg};
                    sdram_rd_bridge_phase <= 2'd0;
                end
            end

            // SDRAM read FIFO rd enable is directly driven by vga_out.oPixelReadEn
        end
    end

    // Connect registers to FIFO ports
    assign sdram_wr_wr_data = sdram_wr_data_reg;
    assign sdram_ctrl_wr_data = sdram_ctrl_wr_data_reg;

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