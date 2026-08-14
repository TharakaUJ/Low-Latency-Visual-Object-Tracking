`timescale 1ns / 1ps

module frame_buffer_controller #(
    parameter integer WIDTH      = 720,
    parameter integer HEIGHT     = 480,
    parameter integer ADDR_WIDTH = 23
)(
    input  wire                  clk_tv,
    input  wire                  clk_vga,
    input  wire                  rst_n,
    input  wire                  tv_frame_done,
    input  wire                  vga_vsync,
    output reg  [ADDR_WIDTH-1:0] sdram_write_base,
    output reg  [ADDR_WIDTH-1:0] sdram_read_base
);

    // Each pixel is packed into 2 x 16-bit SDRAM beats (see top.sv bridge
    // logic), so a buffer is WIDTH*HEIGHT*2 SDRAM words, not WIDTH*HEIGHT.
    // BASE_B must start after that or the two ping-pong buffers overlap.
    localparam integer FRAME_WORDS = WIDTH * HEIGHT * 2;
    localparam [ADDR_WIDTH-1:0] BASE_A = {ADDR_WIDTH{1'b0}};
    localparam [ADDR_WIDTH-1:0] BASE_B = FRAME_WORDS[ADDR_WIDTH-1:0];

    reg write_select;
    reg tv_frame_done_d;
    reg read_select_sync_1;
    reg read_select_sync_2;
    reg vga_vsync_d;

    always @(posedge clk_tv or negedge rst_n) begin
        if (!rst_n) begin
            write_select     <= 1'b0;
            tv_frame_done_d  <= 1'b0;
            sdram_write_base <= BASE_A;
        end else begin
            tv_frame_done_d <= tv_frame_done;
            if (tv_frame_done && !tv_frame_done_d)
                write_select <= ~write_select;

            sdram_write_base <= write_select ? BASE_B : BASE_A;
        end
    end

    always @(posedge clk_vga or negedge rst_n) begin
        if (!rst_n) begin
            read_select_sync_1 <= 1'b0;
            read_select_sync_2 <= 1'b0;
            vga_vsync_d        <= 1'b0;
            sdram_read_base    <= BASE_B;
        end else begin
            read_select_sync_1 <= write_select;
            read_select_sync_2 <= read_select_sync_1;
            vga_vsync_d        <= vga_vsync;

            if (vga_vsync && !vga_vsync_d)
                sdram_read_base <= read_select_sync_2 ? BASE_A : BASE_B;
        end
    end

endmodule