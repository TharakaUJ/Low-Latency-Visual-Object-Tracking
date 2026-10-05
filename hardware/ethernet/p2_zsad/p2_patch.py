# Turn a copy of p1_rows into p2_zsad: PLL clk2 (tracker clock), row_stats (P2) + async FIFO + zsad_core.
# Run inside hardware/ethernet/p2_zsad after copying p1_rows there.
ROI = 80


def rep(s, a, b, n=1):
    assert s.count(a) == n, (a, s.count(a))
    return s.replace(a, b)


# ---------------- fpga.v: tracker clock 62.5 MHz = 50 * 5 / 4 on PLL clk2 ----------------
p = "rtl/fpga.v"
s = open(p).read()
s = rep(s, '    .clk1_phase_shift("2000"),\n',
        '    .clk1_phase_shift("2000"),\n'
        '    .clk2_divide_by(6),\n    .clk2_duty_cycle(50),\n    .clk2_multiply_by(5),\n    .clk2_phase_shift("0"),\n')
s = rep(s, '    .port_clk2("PORT_UNUSED"),', '    .port_clk2("PORT_USED"),')
s = rep(s, "wire clk90_int;\n", "wire clk90_int;\nwire clk_trk_int;   // tracker clock (41.67 MHz)\nwire rst_trk_int;\n")
s = rep(s, "    .clk({clk90_int, clk_int}),", "    .clk({clk_trk_int, clk90_int, clk_int}),")
s = rep(s, """sync_reset_inst (
    .clk(clk_int),
    .rst(~pll_locked),
    .out(rst_int)
);
""", """sync_reset_inst (
    .clk(clk_int),
    .rst(~pll_locked),
    .out(rst_int)
);

sync_reset #(
    .N(4)
)
sync_reset_trk_inst (
    .clk(clk_trk_int),
    .rst(~pll_locked),
    .out(rst_trk_int)
);
""")
s = rep(s, "    .rst(rst_int),\n\n    /*\n     * GPIO", "    .rst(rst_int),\n    .clk_trk(clk_trk_int),\n    .rst_trk(rst_trk_int),\n\n    /*\n     * GPIO")
open(p, "w").write(s)

# ---------------- fpga_core.v ----------------
p = "rtl/fpga_core.v"
s = open(p).read()
s = rep(s, "    input  wire       rst,\n", "    input  wire       rst,\n    input  wire       clk_trk,   // tracker clock\n    input  wire       rst_trk,\n")
s = rep(s, "row_stats #(\n    .PORT(16'd1234)\n)", "// tracker path wires\n" + """wire [15:0] trk_in_tdata, trk_out_tdata;
wire        trk_in_tvalid, trk_in_tready, trk_in_tlast, trk_in_tuser;
wire        trk_out_tvalid, trk_out_tready, trk_out_tlast;
wire        res_toggle;
wire [3:0]  res_ftag;
wire [7:0]  res_x, res_y;
wire [15:0] res_score, trk_frames;
""" + f"\nrow_stats #(\n    .PORT(16'd1234),\n    .ROI({ROI})\n)")
s = rep(s, """    .frames_done(rs_frames_done),
    .rows_bad_total(rs_rows_bad_total)
);
""", f"""    .trk_tdata(trk_in_tdata),
    .trk_tvalid(trk_in_tvalid),
    .trk_tready(trk_in_tready),
    .trk_tlast(trk_in_tlast),
    .trk_tuser(trk_in_tuser),
    .res_toggle(res_toggle),
    .res_ftag(res_ftag),
    .res_x(res_x),
    .res_y(res_y),
    .res_score(res_score),
    .frames_done(rs_frames_done),
    .rows_bad_total(rs_rows_bad_total)
);

// tracker path: one dual-clock frame FIFO (bad rows/templates dropped) into the ZSAD core

axis_async_fifo #(
    .DEPTH(8192),
    .DATA_WIDTH(16),
    .KEEP_ENABLE(0),
    .LAST_ENABLE(1),
    .ID_ENABLE(0),
    .DEST_ENABLE(0),
    .USER_ENABLE(1),
    .USER_WIDTH(1),
    .FRAME_FIFO(1),
    .DROP_OVERSIZE_FRAME(1),
    .DROP_BAD_FRAME(1),
    .DROP_WHEN_FULL(0)
)
trk_fifo (
    .s_clk(clk),
    .s_rst(rst),
    .s_axis_tdata(trk_in_tdata),
    .s_axis_tkeep(2'b11),
    .s_axis_tvalid(trk_in_tvalid),
    .s_axis_tready(trk_in_tready),
    .s_axis_tlast(trk_in_tlast),
    .s_axis_tid(8'd0),
    .s_axis_tdest(8'd0),
    .s_axis_tuser(trk_in_tuser),
    .m_clk(clk_trk),
    .m_rst(rst_trk),
    .m_axis_tdata(trk_out_tdata),
    .m_axis_tkeep(),
    .m_axis_tvalid(trk_out_tvalid),
    .m_axis_tready(trk_out_tready),
    .m_axis_tlast(trk_out_tlast),
    .m_axis_tid(),
    .m_axis_tdest(),
    .m_axis_tuser(),
    .s_pause_req(1'b0),
    .s_pause_ack(),
    .m_pause_req(1'b0),
    .m_pause_ack(),
    .s_status_depth(),
    .s_status_depth_commit(),
    .s_status_overflow(),
    .s_status_bad_frame(),
    .s_status_good_frame(),
    .m_status_depth(),
    .m_status_depth_commit(),
    .m_status_overflow(),
    .m_status_bad_frame(),
    .m_status_good_frame()
);

zsad_core #(
    .ROI({ROI})
)
zsad_core_inst (
    .clk(clk_trk),
    .rst(rst_trk),
    .s_tdata(trk_out_tdata),
    .s_tvalid(trk_out_tvalid),
    .s_tready(trk_out_tready),
    .s_tlast(trk_out_tlast),
    .res_toggle(res_toggle),
    .res_ftag(res_ftag),
    .res_x(res_x),
    .res_y(res_y),
    .res_score(res_score),
    .frames_tracked(trk_frames)
);
""")
s = rep(s, "// P1 row protocol (see rtl/row_stats.v)", "// P2 row protocol + ZSAD tracker (see rtl/row_stats.v, rtl/zsad_core.sv)")
open(p, "w").write(s)

# ---------------- Makefile: sources ----------------
p = "fpga/Makefile"
s = open(p).read()
s = rep(s, "SYN_FILES += rtl/row_stats.v\n",
        "SYN_FILES += rtl/row_stats.v\nSYN_FILES += rtl/zsad_core.sv\n"
        "SYN_FILES += ../../rtl/processing/line_buffer.sv\n"
        "SYN_FILES += ../../rtl/processing/window_buffer.sv\n"
        "SYN_FILES += ../../rtl/processing/template_match.sv\n")
open(p, "w").write(s)

# ---------------- quartus.mk: .sv -> SYSTEMVERILOG_FILE ----------------
p = "common/quartus.mk"
s = open(p).read()
s = rep(s, "\t\t\tv|V) echo set_global_assignment -name VERILOG_FILE $$x >> $(FPGA_TOP).qsf ;;\\\n",
        "\t\t\tv|V) echo set_global_assignment -name VERILOG_FILE $$x >> $(FPGA_TOP).qsf ;;\\\n"
        "\t\t\tsv|SV) echo set_global_assignment -name SYSTEMVERILOG_FILE $$x >> $(FPGA_TOP).qsf ;;\\\n")
open(p, "w").write(s)
print("p2 patch ok")
