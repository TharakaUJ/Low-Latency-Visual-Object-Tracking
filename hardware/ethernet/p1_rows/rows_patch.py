# Turn the p1_echo (debug) fpga_core.v into p1_rows: UDP echo -> row_stats.
import re

p = "rtl/fpga_core.v"
s = open(p).read()

# 1. replace the UDP loopback logic with row_stats
a = s.index("// Loop back UDP")
b = s.index("// Place first payload byte onto LEDs")
rows = """// P1 row protocol (see rtl/row_stats.v)
wire [15:0] rs_frames_done, rs_rows_bad_total;

assign tx_udp_ip_dscp = 0;
assign tx_udp_ip_ecn = 0;
assign tx_udp_ip_ttl = 64;
assign tx_udp_ip_source_ip = local_ip;
assign tx_udp_checksum = 0;
assign tx_udp_payload_axis_tuser = 0;

row_stats #(
    .PORT(16'd1234)
)
row_stats_inst (
    .clk(clk),
    .rst(rst),
    .rx_hdr_valid(rx_udp_hdr_valid),
    .rx_hdr_ready(rx_udp_hdr_ready),
    .rx_ip_source_ip(rx_udp_ip_source_ip),
    .rx_source_port(rx_udp_source_port),
    .rx_dest_port(rx_udp_dest_port),
    .rx_length(rx_udp_length),
    .rx_tdata(rx_udp_payload_axis_tdata),
    .rx_tvalid(rx_udp_payload_axis_tvalid),
    .rx_tready(rx_udp_payload_axis_tready),
    .rx_tlast(rx_udp_payload_axis_tlast),
    .rx_tuser(rx_udp_payload_axis_tuser),
    .tx_hdr_valid(tx_udp_hdr_valid),
    .tx_hdr_ready(tx_udp_hdr_ready),
    .tx_ip_dest_ip(tx_udp_ip_dest_ip),
    .tx_source_port(tx_udp_source_port),
    .tx_dest_port(tx_udp_dest_port),
    .tx_length(tx_udp_length),
    .tx_tdata(tx_udp_payload_axis_tdata),
    .tx_tvalid(tx_udp_payload_axis_tvalid),
    .tx_tready(tx_udp_payload_axis_tready),
    .tx_tlast(tx_udp_payload_axis_tlast),
    .frames_done(rs_frames_done),
    .rows_bad_total(rs_rows_bad_total)
);

"""
s = s[:a] + rows + s[b:]

# 2. drop the echo payload FIFO
a = s.index("axis_fifo #(")
b = s.index("endmodule")
s = s[:a] + s[b:]

# 3. hex views: 00 = frames done | rows bad, 01 = last RX src IP, 10 = last RX dst IP, 11 = MAC bad-FCS | good counts
old = "        default: dest_ip_reg <= {dbg_fcs_cnt, dbg_good_cnt};"
assert s.count(old) == 1
s = s.replace(old, "        2'b11:   dest_ip_reg <= {dbg_fcs_cnt, dbg_good_cnt};\n"
                   "        default: dest_ip_reg <= {rs_frames_done, rs_rows_bad_total};")
s = s.replace("// SW15,SW14 select the hex view: 00 = counters,",
              "// SW15,SW14 select the hex view: 00 = frames done | rows bad, 11 = MAC bad-FCS | good,")
open(p, "w").write(s)

m = "fpga/Makefile"
t = open(m).read()
t = t.replace("SYN_FILES += rtl/fpga_core.v\n", "SYN_FILES += rtl/fpga_core.v\nSYN_FILES += rtl/row_stats.v\n")
open(m, "w").write(t)
print("rows patch ok")
