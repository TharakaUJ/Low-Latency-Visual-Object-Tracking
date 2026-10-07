import shutil
p = "fpga_core.v"
shutil.copy(p, "fpga_core.v.echo_orig")
s = open(p).read()
old_hex = """always @(posedge clk) begin
    if (tx_udp_hdr_valid) begin
        dest_ip_reg <= tx_udp_ip_dest_ip;
    end

    if (rst) begin
        dest_ip_reg <= 0;
    end
end"""
assert old_hex in s
new_hex = """// DEBUG (bring-up): hex7..4 = bad-FCS frame count, hex3..0 = good rx frame count
wire       dbg_rx_good, dbg_rx_bad_fcs, dbg_rx_bad_frame, dbg_tx_good;
wire [1:0] dbg_speed;
reg  [15:0] dbg_good_cnt = 0, dbg_fcs_cnt = 0;
reg  [7:0]  dbg_led = 0;
always @(posedge clk) begin
    if (dbg_rx_good)    dbg_good_cnt <= dbg_good_cnt + 1;
    if (dbg_rx_bad_fcs) dbg_fcs_cnt  <= dbg_fcs_cnt + 1;
    dbg_led[1:0] <= dbg_speed;
    if (dbg_rx_good)      dbg_led[2] <= 1'b1;
    if (dbg_rx_bad_fcs)   dbg_led[3] <= 1'b1;
    if (dbg_rx_bad_frame) dbg_led[4] <= 1'b1;
    if (rx_eth_hdr_valid && rx_eth_hdr_ready && rx_eth_type == 16'h0806) dbg_led[5] <= 1'b1;
    if (rx_eth_hdr_valid && rx_eth_hdr_ready && rx_eth_dest_mac == local_mac) dbg_led[6] <= 1'b1;
    if (dbg_tx_good)      dbg_led[7] <= 1'b1;
    dest_ip_reg <= {dbg_fcs_cnt, dbg_good_cnt};
    if (rst) begin
        dest_ip_reg <= 0; dbg_good_cnt <= 0; dbg_fcs_cnt <= 0; dbg_led <= 0;
    end
end"""
s = s.replace(old_hex, new_hex)
assert s.count("assign ledg = led_reg;") == 1
s = s.replace("assign ledg = led_reg;", "assign ledg = dbg_led; // DEBUG (was led_reg)")
for a, b in [(".tx_fifo_good_frame(),", ".tx_fifo_good_frame(dbg_tx_good),"),
             (".rx_error_bad_frame(),", ".rx_error_bad_frame(dbg_rx_bad_frame),"),
             (".rx_error_bad_fcs(),", ".rx_error_bad_fcs(dbg_rx_bad_fcs),"),
             (".rx_fifo_good_frame(),", ".rx_fifo_good_frame(dbg_rx_good),"),
             (".speed(),", ".speed(dbg_speed),")]:
    assert s.count(a) == 1, a
    s = s.replace(a, b)
open(p, "w").write(s)
print("patched")
