//====================================================================
// I2C_Video_Cfg.v
//
// Register-write sequencer for the ADV7180 NTSC/PAL/SECAM decoder on
// the DE2-115 board. Configures the chip for COMPOSITE (CVBS) video
// input on AIN1 -- the yellow RCA "video in" jack -- with autodetect
// of NTSC/PAL/SECAM standard.
//
// Interface matches the I2C_config instance in I2C_Master.v:
//   clk    <- mi2c_ctrl_clk  (~80kHz toggle clock from I2C_Master)
//   reset  <- RESET
//   mend   <- TRN_END        (pulses high when one 24-bit frame is done)
//   mack   <- ACK            (slave ACK bits, not used for retry here)
//   mgo    -> GO              (drives the bit-bang state machine)
//   mstep  -> current table index (debug/status only)
//   i2c_data -> 24-bit {slave_addr+W, sub_addr, data} for I2C_Master
//
// NOTE: The exact ADV7180 recommended register set can vary slightly
// by silicon revision -- double check these against the ADV7180
// datasheet / DE2_115_datasheets\TV Decoder folder before relying on
// this in a graded/production design. The values below reflect the
// commonly used Analog Devices / Terasic reference init sequence for
// CVBS autodetect on AIN1.
//====================================================================

module I2C_Video_Cfg (
    input             clk,     // mi2c_ctrl_clk from I2C_Master
    input             reset,   // active-low system reset
    input             mend,    // TRN_END from I2C_Master
    input             mack,    // ACK from I2C_Master (unused, available for retry logic)
    output reg        mgo,     // GO -> I2C_Master
    input             SCLK,    // I2C_SCLK, provided for future use / observation
    output reg [4:0]  mstep,   // current ROM index
    output reg [23:0] i2c_data // {addr+W[7:0], subaddr[7:0], data[7:0]}
);

    // ADV7180 I2C write address is 0x40 (per board datasheet: W/R = 0x40/0x41)
    localparam ADV7180_ADDR_W = 8'h40;

    // Number of register-write entries in the config table
    localparam NUM_REGS = 16;

    // ROM holding {addr, subaddr, data} triples
    reg [23:0] rom [0:NUM_REGS-1];

    integer i;
    initial begin
        // Software reset first
        rom[0]  = {ADV7180_ADDR_W, 8'h0F, 8'h00}; // Exit power-down / reset ADI recommended
        rom[1]  = {ADV7180_ADDR_W, 8'h52, 8'hCD}; // ADI recommended write
        rom[2]  = {ADV7180_ADDR_W, 8'h00, 8'h00}; // Input Control: CVBS in on AIN1 (yellow jack)
        rom[3]  = {ADV7180_ADDR_W, 8'h01, 8'hC8}; // Video Selection 1: autodetect PAL B/G/H/I/D, NTSC J, SECAM
        rom[4]  = {ADV7180_ADDR_W, 8'h02, 8'h04}; // Video Selection 2: autodetect enabled, CVBS mode
        rom[5]  = {ADV7180_ADDR_W, 8'h03, 8'h00}; // Output Control: standard 8-bit 4:2:2 ITU-R BT.656 output
        rom[6]  = {ADV7180_ADDR_W, 8'h04, 8'h07}; // Extended Output Control: EAV/SAV codes, blanking enabled
        rom[7]  = {ADV7180_ADDR_W, 8'h05, 8'h00}; // Reserved / ADI default
        rom[8]  = {ADV7180_ADDR_W, 8'h06, 8'h02}; // Reserved / ADI default
        rom[9]  = {ADV7180_ADDR_W, 8'h07, 8'h7F}; // Reserved / ADI default
        rom[10] = {ADV7180_ADDR_W, 8'h08, 8'h80}; // Reserved / ADI default
        rom[11] = {ADV7180_ADDR_W, 8'h0A, 8'h00}; // Brightness = 0
        rom[12] = {ADV7180_ADDR_W, 8'h0B, 8'h00}; // Contrast = default
        rom[13] = {ADV7180_ADDR_W, 8'h0C, 8'h00}; // Hue = 0
        rom[14] = {ADV7180_ADDR_W, 8'h0D, 8'h7F}; // Default Value Y
        rom[15] = {ADV7180_ADDR_W, 8'h14, 8'h11}; // Free-run enable / ADI recommended
    end

    reg mend_d;
    reg [1:0] state;
    localparam IDLE = 2'd0,
               RUN  = 2'd1,
               HOLD = 2'd2,
               DONE = 2'd3;

    always @ (posedge clk or negedge reset) begin
        if (!reset) begin
            mstep    <= 0;
            mgo      <= 0;
            i2c_data <= rom[0];
            mend_d   <= 1'b1;
            state    <= IDLE;
        end
        else begin
            mend_d <= mend;

            case (state)

                // Load the first table entry and start the transfer
                IDLE: begin
                    mstep    <= 0;
                    i2c_data <= rom[0];
                    mgo      <= 1'b1;
                    state    <= RUN;
                end

                // Wait for I2C_Master to finish shifting the current 24 bits out
                RUN: begin
                    if (mend && !mend_d) begin // rising edge of TRN_END = transfer complete
                        if (mstep == NUM_REGS - 1) begin
                            // last register written -> stop
                            mgo   <= 1'b0;
                            state <= DONE;
                        end
                        else begin
                            // drop GO for one clock; this resets SD_COUNTER
                            // inside I2C_Master (GO==0 -> SD_COUNTER=0)
                            mgo   <= 1'b0;
                            state <= HOLD;
                        end
                    end
                end

                // One-cycle gap, then load next entry and restart
                HOLD: begin
                    mstep    <= mstep + 1'b1;
                    i2c_data <= rom[mstep + 1'b1];
                    mgo      <= 1'b1;
                    state    <= RUN;
                end

                // All registers written; sit idle
                DONE: begin
                    mgo <= 1'b0;
                end

                default: state <= IDLE;

            endcase
        end
    end

endmodule