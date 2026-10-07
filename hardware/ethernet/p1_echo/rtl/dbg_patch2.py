p = "fpga_core.v"
s = open(p).read()
old = "    dest_ip_reg <= {dbg_fcs_cnt, dbg_good_cnt};"
assert s.count(old) == 1
new = """    // SW1..0 select the hex view: 00 = counters, 01 = last RX IP source, 10 = last RX IP dest
    if (rx_udp_hdr_valid && rx_udp_hdr_ready) begin
        if (rx_udp_ip_source_ip != 0) dbg_src <= rx_udp_ip_source_ip;
        dbg_dst <= rx_udp_ip_dest_ip;
    end else if (rx_ip_hdr_valid && rx_ip_hdr_ready) begin
        if (rx_ip_source_ip != 0) dbg_src <= rx_ip_source_ip;
        dbg_dst <= rx_ip_dest_ip;
    end
    case (sw[1:0])
        2'b01:   dest_ip_reg <= dbg_src;
        2'b10:   dest_ip_reg <= dbg_dst;
        default: dest_ip_reg <= {dbg_fcs_cnt, dbg_good_cnt};
    endcase"""
s = s.replace(old, new)
s = s.replace("reg  [7:0]  dbg_led = 0;", "reg  [7:0]  dbg_led = 0;\nreg  [31:0] dbg_src = 0, dbg_dst = 0;")
open(p, "w").write(s)
print("patched2")
