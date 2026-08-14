`timescale 1ns / 1ps
//=============================================================================
// sdram_de2115_controller
//
// Real physical SDRAM controller for the Terasic DE2-115 board
// (ISSI IS42S16320D-7: 32MB, 16-bit data, 4 banks, 13-bit row, 9-bit column).
//
// Presents the SAME producer/consumer FIFO interface as your original
// behavioral "sdram_controller" module, so it can be dropped in as a
// replacement driven by frame_buffer_controller. Internally it issues real
// ACTIVATE / READ / WRITE / PRECHARGE / AUTO REFRESH commands to the chip.
//
// NOTE ON DATA WIDTH
// -------------------
// The physical SDRAM data bus is 16 bits wide. This controller's FIFO-facing
// ports are therefore 16-bit (DATA_WIDTH default 16), NOT the 26-bit
// PIXEL_WIDTH used in your simulation model. If your pixel word is wider than
// 16 bits, pack/split it into 16-bit beats in the FIFOs feeding this module
// (e.g. write high half then low half), or widen this controller to burst
// two 16-bit beats per pixel and reassemble on the read side.
//
// CLOCKING
// --------
// `clk` here is the SDRAM controller clock (typically 100 MHz on DE2-115).
// DRAM_CLK to the physical chip must come from a PLL output that is phase
// shifted (commonly -3ns to -3.5ns, i.e. ~54-72 degrees at 100MHz) relative
// to `clk` so that the clock edge arrives at the SDRAM pins after the
// address/command/data edges. Instantiate that PLL at the top level and
// drive DRAM_CLK from its shifted output, NOT from `clk` directly.
//=============================================================================

module sdram_de2115_controller #(
    parameter integer DATA_WIDTH      = 16,   // SDRAM native data width
    parameter integer ROW_WIDTH       = 13,
    parameter integer COL_WIDTH       = 9,
    parameter integer BANK_WIDTH      = 2,
    // Timing parameters expressed in `clk` cycles. Defaults assume ~100MHz
    // clk and IS42S16320D-7 (7ns) timings; re-derive if you change clk freq.
    parameter integer T_INIT_WAIT     = 10000, // >100us power-up wait (cycles)
    parameter integer T_RP            = 2,     // precharge -> command   (cycles)
    parameter integer T_RFC           = 7,     // refresh recovery       (cycles)
    parameter integer T_RCD           = 2,     // activate -> read/write (cycles)
    parameter integer T_MRD           = 2,     // mode-register set      (cycles)
    parameter integer CAS_LATENCY     = 2,     // CL2 (safe at 100MHz)
    parameter integer T_WR            = 2,     // write recovery         (cycles)
    parameter integer REFRESH_INTERVAL= 780,   // ~7.8us @100MHz -> 8192 refreshes/64ms
    // Must match WIDTH*HEIGHT*2 in frame_buffer_controller (2 SDRAM words
    // per pixel) so write_ptr/read_ptr wrap back to 0 at exactly the same
    // offset the ping-pong base swaps at.
    parameter integer FRAME_WORDS     = 720*480*2
)(
    input  wire                      clk,
    input  wire                      rst_n,

    // ---------------- FIFO-style front end (same shape as before) --------
    input  wire [ROW_WIDTH+COL_WIDTH+BANK_WIDTH-1:0] sdram_write_base,   // word address base
    input  wire [ROW_WIDTH+COL_WIDTH+BANK_WIDTH-1:0] sdram_read_base,

    input  wire                      sdram_wr_empty,
    input  wire [DATA_WIDTH-1:0]     sdram_wr_rd_data,
    output reg                       sdram_wr_rd_en,

    input  wire                      sdram_rd_full,
    output reg                       sdram_rd_wr_en,
    output reg  [DATA_WIDTH-1:0]     sdram_rd_wr_data,

    // ---------------- Physical SDRAM pins (DE2-115) -----------------------
    output wire                      DRAM_CKE,
    output wire                      DRAM_CS_N,
    output wire                      DRAM_RAS_N,
    output wire                      DRAM_CAS_N,
    output wire                      DRAM_WE_N,
    output wire [BANK_WIDTH-1:0]     DRAM_BA,
    output wire [ROW_WIDTH-1:0]      DRAM_ADDR,      // row/col mux'd address
    output wire [DATA_WIDTH/8-1:0]   DRAM_DQM,       // byte masks (UDQM/LDQM)
    inout  wire [DATA_WIDTH-1:0]     DRAM_DQ
);

    //-------------------------------------------------------------------
    // Command encoding: {CS_N, RAS_N, CAS_N, WE_N}
    //-------------------------------------------------------------------
    localparam [3:0] CMD_INHIBIT   = 4'b1111,
                      CMD_NOP      = 4'b0111,
                      CMD_ACTIVE   = 4'b0011,
                      CMD_READ     = 4'b0101,
                      CMD_WRITE    = 4'b0100,
                      CMD_PRECHARGE= 4'b0010,
                      CMD_REFRESH  = 4'b0001,
                      CMD_MRS      = 4'b0000;

    reg [3:0] cmd;
    assign {DRAM_CS_N, DRAM_RAS_N, DRAM_CAS_N, DRAM_WE_N} = cmd;

    reg        cke_r;
    assign DRAM_CKE = cke_r;

    reg [ROW_WIDTH-1:0] addr_r;
    reg [BANK_WIDTH-1:0] ba_r;
    assign DRAM_ADDR = addr_r;
    assign DRAM_BA   = ba_r;

    // DQM held low (both bytes enabled) whenever we're actually
    // reading/writing; held high otherwise to avoid glitches.
    reg [DATA_WIDTH/8-1:0] dqm_r;
    assign DRAM_DQM = dqm_r;

    // Bidirectional data bus
    reg                     dq_oe;
    reg  [DATA_WIDTH-1:0]   dq_out;
    assign DRAM_DQ = dq_oe ? dq_out : {DATA_WIDTH{1'bz}};

    //-------------------------------------------------------------------
    // Address decode: word address -> {bank, row, col}
    // Word-addressed pointer, wrapped mod chip depth, split as
    // [ BA | ROW | COL ]
    //-------------------------------------------------------------------
    localparam integer ADDR_WIDTH = ROW_WIDTH + COL_WIDTH + BANK_WIDTH; // total word-addr bits
    reg  [ADDR_WIDTH-1:0] write_ptr, read_ptr;
    wire [ADDR_WIDTH-1:0] write_word_addr = sdram_write_base + write_ptr;
    wire [ADDR_WIDTH-1:0] read_word_addr  = sdram_read_base  + read_ptr;

    // Straight bit-slicing: [ BANK | ROW | COL ] packed LSB-first from the
    // word address. No function needed -- keeps part-selects on plain wires.
    wire [BANK_WIDTH-1:0] wr_bank = write_word_addr[COL_WIDTH+ROW_WIDTH +: BANK_WIDTH];
    wire [ROW_WIDTH-1:0]  wr_row  = write_word_addr[COL_WIDTH +: ROW_WIDTH];
    wire [COL_WIDTH-1:0]  wr_col  = write_word_addr[0 +: COL_WIDTH];

    wire [BANK_WIDTH-1:0] rd_bank = read_word_addr[COL_WIDTH+ROW_WIDTH +: BANK_WIDTH];
    wire [ROW_WIDTH-1:0]  rd_row  = read_word_addr[COL_WIDTH +: ROW_WIDTH];
    wire [COL_WIDTH-1:0]  rd_col  = read_word_addr[0 +: COL_WIDTH];

    //-------------------------------------------------------------------
    // Main FSM
    //-------------------------------------------------------------------
    localparam [4:0]
        S_INIT_WAIT   = 5'd0,
        S_INIT_PRE    = 5'd1,
        S_INIT_PRE_WT = 5'd2,
        S_INIT_REF1   = 5'd3,
        S_INIT_REF1_WT= 5'd4,
        S_INIT_REF2   = 5'd5,
        S_INIT_REF2_WT= 5'd6,
        S_INIT_MRS    = 5'd7,
        S_INIT_MRS_WT = 5'd8,
        S_IDLE        = 5'd9,
        S_REFRESH     = 5'd10,
        S_REFRESH_WT  = 5'd11,
        S_WR_ACTIVE   = 5'd12,
        S_WR_ACT_WT   = 5'd13,
        S_WR_CMD      = 5'd14,
        S_WR_RECOVER  = 5'd15,
        S_WR_PRECHARGE= 5'd16,
        S_WR_PRE_WT   = 5'd17,
        S_RD_ACTIVE   = 5'd18,
        S_RD_ACT_WT   = 5'd19,
        S_RD_CMD      = 5'd20,
        S_RD_CAS_WT   = 5'd21,
        S_RD_CAPTURE  = 5'd22,
        S_RD_PRECHARGE= 5'd23,
        S_RD_PRE_WT   = 5'd24,
        S_REFRESH_PRE_WT = 5'd25;

    reg [4:0]  state;
    reg [15:0] wait_cnt;
    reg [15:0] refresh_cnt;
    reg        refresh_pending;
    reg        bank_open;         // is a row currently open (single-bank-open policy)
    reg [BANK_WIDTH-1:0] open_bank;
    reg [ROW_WIDTH-1:0]  open_row;

    // Mode register value (written on DRAM_ADDR during MRS):
    // burst length = 1, burst type = sequential, CAS latency = CAS_LATENCY,
    // write burst mode = single (bit9=1 -> no burst on writes)
    wire [ROW_WIDTH-1:0] mode_reg = {3'b000, 1'b1, 2'b00, CAS_LATENCY[2:0], 1'b0, 3'b000};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state           <= S_INIT_WAIT;
            wait_cnt        <= 16'd0;
            refresh_cnt     <= 16'd0;
            refresh_pending <= 1'b0;
            bank_open       <= 1'b0;
            open_bank       <= {BANK_WIDTH{1'b0}};
            open_row        <= {ROW_WIDTH{1'b0}};
            write_ptr       <= {ADDR_WIDTH{1'b0}};
            read_ptr        <= {ADDR_WIDTH{1'b0}};
            cke_r           <= 1'b0;
            cmd             <= CMD_INHIBIT;
            addr_r          <= {ROW_WIDTH{1'b0}};
            ba_r            <= {BANK_WIDTH{1'b0}};
            dqm_r           <= {(DATA_WIDTH/8){1'b1}};
            dq_oe           <= 1'b0;
            dq_out          <= {DATA_WIDTH{1'b0}};
            sdram_wr_rd_en  <= 1'b0;
            sdram_rd_wr_en  <= 1'b0;
            sdram_rd_wr_data<= {DATA_WIDTH{1'b0}};
        end else begin
            // Defaults each cycle; overridden below where needed
            cmd            <= CMD_NOP;
            sdram_wr_rd_en <= 1'b0;
            sdram_rd_wr_en <= 1'b0;
            dq_oe          <= 1'b0;
            dqm_r          <= {(DATA_WIDTH/8){1'b1}};

            // Free-running refresh request timer (active once init is done)
            if (state != S_INIT_WAIT && state != S_INIT_PRE && state != S_INIT_PRE_WT &&
                state != S_INIT_REF1 && state != S_INIT_REF1_WT && state != S_INIT_REF2 &&
                state != S_INIT_REF2_WT && state != S_INIT_MRS && state != S_INIT_MRS_WT) begin
                if (refresh_cnt >= REFRESH_INTERVAL) begin
                    refresh_cnt     <= 16'd0;
                    refresh_pending <= 1'b1;
                end else begin
                    refresh_cnt <= refresh_cnt + 1'b1;
                end
            end

            case (state)
            //-------------------- Power-up init sequence --------------------
            S_INIT_WAIT: begin
                cke_r <= 1'b1; // CKE asserted, but keep NOP/INHIBIT until stable
                cmd   <= CMD_INHIBIT;
                if (wait_cnt >= T_INIT_WAIT) begin
                    wait_cnt <= 16'd0;
                    state    <= S_INIT_PRE;
                end else
                    wait_cnt <= wait_cnt + 1'b1;
            end

            S_INIT_PRE: begin
                cmd          <= CMD_PRECHARGE;
                addr_r[10]   <= 1'b1;  // precharge ALL banks
                state        <= S_INIT_PRE_WT;
                wait_cnt     <= 16'd0;
            end
            S_INIT_PRE_WT: begin
                if (wait_cnt >= T_RP-1) begin
                    wait_cnt <= 16'd0; state <= S_INIT_REF1;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            S_INIT_REF1: begin
                cmd <= CMD_REFRESH; state <= S_INIT_REF1_WT; wait_cnt <= 16'd0;
            end
            S_INIT_REF1_WT: begin
                if (wait_cnt >= T_RFC-1) begin
                    wait_cnt <= 16'd0; state <= S_INIT_REF2;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            S_INIT_REF2: begin
                cmd <= CMD_REFRESH; state <= S_INIT_REF2_WT; wait_cnt <= 16'd0;
            end
            S_INIT_REF2_WT: begin
                if (wait_cnt >= T_RFC-1) begin
                    wait_cnt <= 16'd0; state <= S_INIT_MRS;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            S_INIT_MRS: begin
                cmd    <= CMD_MRS;
                ba_r   <= {BANK_WIDTH{1'b0}};
                addr_r <= mode_reg;
                state  <= S_INIT_MRS_WT;
                wait_cnt <= 16'd0;
            end
            S_INIT_MRS_WT: begin
                if (wait_cnt >= T_MRD-1) begin
                    wait_cnt <= 16'd0;
                    refresh_cnt <= 16'd0;
                    state <= S_IDLE;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            //-------------------- Idle: arbitrate refresh/write/read --------
            S_IDLE: begin
                if (refresh_pending) begin
                    refresh_pending <= 1'b0;
                    wait_cnt        <= 16'd0;
                    if (bank_open) begin
                        // Any open bank must be closed before refresh
                        cmd        <= CMD_PRECHARGE;
                        addr_r[10] <= 1'b1;
                        bank_open  <= 1'b0;
                        state      <= S_REFRESH_PRE_WT;
                    end else begin
                        state <= S_REFRESH;
                    end
                end else if (!sdram_wr_empty) begin
                    state <= S_WR_ACTIVE;
                end else if (!sdram_rd_full) begin
                    state <= S_RD_ACTIVE;
                end
            end

            S_REFRESH_PRE_WT: begin
                if (wait_cnt >= T_RP-1) begin
                    wait_cnt <= 16'd0; state <= S_REFRESH;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            //-------------------- Refresh --------------------
            S_REFRESH: begin
                cmd   <= CMD_REFRESH;
                state <= S_REFRESH_WT;
                wait_cnt <= 16'd0;
            end
            S_REFRESH_WT: begin
                if (wait_cnt >= T_RFC-1) begin
                    wait_cnt <= 16'd0; state <= S_IDLE;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            //-------------------- Write transaction --------------------
            S_WR_ACTIVE: begin
                if (bank_open && open_bank==wr_bank && open_row==wr_row) begin
                    state <= S_WR_CMD; // row already open, skip activate
                end else begin
                    if (bank_open) begin
                        cmd        <= CMD_PRECHARGE;
                        addr_r[10] <= 1'b1;
                        bank_open  <= 1'b0;
                        state      <= S_WR_PRE_WT;
                        wait_cnt   <= 16'd0;
                    end else begin
                        cmd      <= CMD_ACTIVE;
                        ba_r     <= wr_bank;
                        addr_r   <= wr_row;
                        state    <= S_WR_ACT_WT;
                        wait_cnt <= 16'd0;
                    end
                end
            end
            S_WR_PRE_WT: begin
                if (wait_cnt >= T_RP-1) begin
                    wait_cnt <= 16'd0; state <= S_WR_ACTIVE;
                end else wait_cnt <= wait_cnt + 1'b1;
            end
            S_WR_ACT_WT: begin
                if (wait_cnt >= T_RCD-1) begin
                    bank_open <= 1'b1; open_bank <= wr_bank; open_row <= wr_row;
                    wait_cnt  <= 16'd0; state <= S_WR_CMD;
                end else wait_cnt <= wait_cnt + 1'b1;
            end
            S_WR_CMD: begin
                cmd            <= CMD_WRITE;
                ba_r           <= wr_bank;
                addr_r         <= {{(ROW_WIDTH-COL_WIDTH-1){1'b0}}, 1'b0, wr_col}; // A10=0: no auto-precharge
                dqm_r          <= {(DATA_WIDTH/8){1'b0}};
                dq_oe          <= 1'b1;
                dq_out         <= sdram_wr_rd_data;
                sdram_wr_rd_en <= 1'b1;   // pop the write FIFO this cycle
                // Wrap at the frame boundary -- must match the point where
                // frame_buffer_controller swaps sdram_write_base, or writes
                // silently drift into the other (or unwritten) buffer.
                if (write_ptr == FRAME_WORDS-1)
                    write_ptr <= {ADDR_WIDTH{1'b0}};
                else
                    write_ptr <= write_ptr + 1'b1;
                state          <= S_WR_RECOVER;
                wait_cnt       <= 16'd0;
            end
            S_WR_RECOVER: begin
                if (wait_cnt >= T_WR-1) begin
                    wait_cnt <= 16'd0; state <= S_IDLE;
                end else wait_cnt <= wait_cnt + 1'b1;
            end

            //-------------------- Read transaction --------------------
            S_RD_ACTIVE: begin
                if (bank_open && open_bank==rd_bank && open_row==rd_row) begin
                    state <= S_RD_CMD;
                end else begin
                    if (bank_open) begin
                        cmd        <= CMD_PRECHARGE;
                        addr_r[10] <= 1'b1;
                        bank_open  <= 1'b0;
                        state      <= S_RD_PRE_WT;
                        wait_cnt   <= 16'd0;
                    end else begin
                        cmd      <= CMD_ACTIVE;
                        ba_r     <= rd_bank;
                        addr_r   <= rd_row;
                        state    <= S_RD_ACT_WT;
                        wait_cnt <= 16'd0;
                    end
                end
            end
            S_RD_PRE_WT: begin
                if (wait_cnt >= T_RP-1) begin
                    wait_cnt <= 16'd0; state <= S_RD_ACTIVE;
                end else wait_cnt <= wait_cnt + 1'b1;
            end
            S_RD_ACT_WT: begin
                if (wait_cnt >= T_RCD-1) begin
                    bank_open <= 1'b1; open_bank <= rd_bank; open_row <= rd_row;
                    wait_cnt  <= 16'd0; state <= S_RD_CMD;
                end else wait_cnt <= wait_cnt + 1'b1;
            end
            S_RD_CMD: begin
                cmd      <= CMD_READ;
                ba_r     <= rd_bank;
                addr_r   <= {{(ROW_WIDTH-COL_WIDTH-1){1'b0}}, 1'b0, rd_col}; // A10=0
                dqm_r    <= {(DATA_WIDTH/8){1'b0}};
                if (read_ptr == FRAME_WORDS-1)
                    read_ptr <= {ADDR_WIDTH{1'b0}};
                else
                    read_ptr <= read_ptr + 1'b1;
                wait_cnt <= 16'd0;
                state    <= S_RD_CAS_WT;
            end
            S_RD_CAS_WT: begin
                dqm_r <= {(DATA_WIDTH/8){1'b0}};
                if (wait_cnt >= CAS_LATENCY-1) begin
                    wait_cnt <= 16'd0; state <= S_RD_CAPTURE;
                end else wait_cnt <= wait_cnt + 1'b1;
            end
            S_RD_CAPTURE: begin
                sdram_rd_wr_data <= DRAM_DQ;   // sample data presented by SDRAM
                sdram_rd_wr_en   <= 1'b1;      // push into read FIFO
                state            <= S_IDLE;
            end

            default: state <= S_INIT_WAIT;
            endcase
        end
    end

endmodule