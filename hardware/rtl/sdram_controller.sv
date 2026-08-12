module frame_buffer_controller (
    input  wire        clk_tv,         // 27 MHz TV Decoder Clock
    input  wire        clk_vga,        // 25.175 MHz VGA Pixel Clock
    input  wire        rst_n,
    
    // Video Status Inputs
    input  wire        tv_frame_done,  // Pulse high when TV finishes writing a frame
    input  wire        vga_vsync,      // VGA Vertical Sync (indicates end of read frame)
    
    // Memory Addressing Outputs to SDRAM Master Engine
    output reg  [22:0] sdram_write_base,
    output reg  [22:0] sdram_read_base
);

    localparam BUFFER_0_ADDR = 23'h000000;
    localparam BUFFER_1_ADDR = 23'h400000;

    reg        tv_current_buffer;  // 0 = Buffer 0, 1 = Buffer 1
    reg        vga_current_buffer; 

    // Status flags
    reg        new_frame_ready;
    reg        frame_read_done;

    // Synchronizers for crossing clock domains safely
    reg  [2:0] tv_done_sync;
    reg  [2:0] vga_vsync_sync;

    //-----------------------------------------------------------------
    // 1. Write Domain Logic (TV Decoder)
    //-----------------------------------------------------------------
    always @(posedge clk_tv or negedge rst_n) begin
        if (!rst_n) begin
            tv_current_buffer <= 1'b0;
            sdram_write_base  <= BUFFER_0_ADDR;
            new_frame_ready   <= 1'b0;
        end else begin
            // Synchronize the read-done flag from VGA domain to safely clear flag
            tv_done_sync <= {tv_done_sync[1:0], frame_read_done};
            
            if (tv_frame_done) begin
                // Alternates the target buffer once the active one is compiled
                tv_current_buffer <= !tv_current_buffer;
                sdram_write_base  <= (!tv_current_buffer) ? BUFFER_1_ADDR : BUFFER_0_ADDR;
                new_frame_ready   <= 1'b1; // Announce to VGA side that a fresh frame is ready
            end else if (tv_done_sync[2]) begin
                new_frame_ready   <= 1'b0;
            end
        end
    end

    //-----------------------------------------------------------------
    // 2. Read Domain Logic (VGA Out)
    //-----------------------------------------------------------------
    always @(posedge clk_vga or negedge rst_n) begin
        if (!rst_n) begin
            vga_current_buffer <= 1'b1; // Start by reading the alternative buffer
            sdram_read_base    <= BUFFER_1_ADDR;
            frame_read_done    <= 1'b0;
        end else begin
            // Synchronize the frame-ready signal from TV domain
            vga_vsync_sync <= {vga_vsync_sync[1:0], new_frame_ready};
            
            // Swap read buffer ONLY during VGA vertical blanking interval to avoid tearing
            if (vga_vsync) begin
                frame_read_done <= 1'b1;
                if (vga_vsync_sync[2]) begin
                    // Safely capture the buffer that TV completed writing to
                    vga_current_buffer <= !tv_current_buffer; 
                    sdram_read_base    <= (!tv_current_buffer) ? BUFFER_0_ADDR : BUFFER_1_ADDR;
                end
            end else begin
                frame_read_done <= 1'b0;
            end
        end
    end

endmodule
