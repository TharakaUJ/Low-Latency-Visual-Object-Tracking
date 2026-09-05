`timescale 1ns/1ps
// ============================================================
// tb_line_buffer
// Checks:
//   1. dout returns the value written IMG_W cycles ago at the
//      same address (read-before-write, one-line delay).
//   2. wr_en=0 -> memory not modified (dout still reflects old data).
//   3. One cycle read latency (dout is registered).
// ============================================================
module tb_line_buffer;

    localparam int WIDTH = 8;
    localparam int IMG_W = 8;      // small, so test finishes fast
    localparam int ADDR_W = $clog2(IMG_W);

    logic clk = 0;
    logic wr_en;
    logic [ADDR_W-1:0] addr;
    logic [WIDTH-1:0] din;
    logic [WIDTH-1:0] dout;

    int errors = 0;

    line_buffer #(.WIDTH(WIDTH), .IMG_W(IMG_W)) dut (
        .clk(clk), .wr_en(wr_en), .addr(addr), .din(din), .dout(dout)
    );

    always #5 clk = ~clk;

    // model: a simple queue per address, IMG_W deep circular buffer
    logic [WIDTH-1:0] shadow_mem [0:IMG_W-1];
    logic [WIDTH-1:0] expected_dout;

    task automatic check(string msg);
        if (dout !== expected_dout) begin
            $error("[%0t] MISMATCH %s: dout=%0h expected=%0h", $time, msg, dout, expected_dout);
            errors++;
        end
    endtask

    initial begin
        // init shadow mem to 0 (matches uninitialized... actually mem is X in
        // real HW/sim until written; we only check addresses after they've
        // been written at least once around the ring)
        for (int i = 0; i < IMG_W; i++) shadow_mem[i] = '0;

        wr_en = 0; addr = 0; din = 0;
        @(negedge clk);

        // Drive 3 full passes around the IMG_W-deep line so we exercise the
        // "row above" wraparound behavior multiple times. Pass 0 writes into
        // memory that is uninitialized (X at power-up, just like real BRAM),
        // so we only check dout content from pass 1 onward, once every
        // address has been written at least once.
        for (int pass = 0; pass < 3; pass++) begin
            for (int col = 0; col < IMG_W; col++) begin
                addr = col[ADDR_W-1:0];
                din  = (pass*IMG_W + col + 1) & 8'hFF;
                wr_en = 1;

                // Predict dout for THIS cycle: it is whatever was stored
                // at 'addr' at the end of the previous write to this address
                // (i.e. shadow_mem[col] before we overwrite it now).
                expected_dout = shadow_mem[col];

                @(posedge clk);
                #1; // allow dout (registered, updates on this edge) to settle
                if (pass > 0)
                    check($sformatf("pass=%0d col=%0d", pass, col));

                shadow_mem[col] = din; // commit the write for next pass' prediction
            end
        end

        // Test wr_en=0: address should keep returning the last stored value,
        // memory must NOT be overwritten by din while wr_en is low.
        addr = 2; din = 8'hAA; wr_en = 0;
        expected_dout = shadow_mem[2];
        @(posedge clk); #1;
        check("wr_en=0 read");

        addr = 2; din = 8'h55; wr_en = 0; // try again, din changes, must not write
        expected_dout = shadow_mem[2];
        @(posedge clk); #1;
        check("wr_en=0 second read, din changed but must not write");

        // Now confirm a real write still lands correctly after those no-ops
        addr = 2; din = 8'h33; wr_en = 1;
        expected_dout = shadow_mem[2];
        @(posedge clk); #1;
        check("write after idle reads");
        shadow_mem[2] = 8'h33;

        addr = 2; wr_en = 0;
        expected_dout = shadow_mem[2];
        @(posedge clk); #1;
        check("readback of new value");

        if (errors == 0)
            $display("TB_LINE_BUFFER: PASS (all checks ok)");
        else
            $display("TB_LINE_BUFFER: FAIL (%0d errors)", errors);

        $finish;
    end

endmodule
