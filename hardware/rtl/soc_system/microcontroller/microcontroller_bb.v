
module microcontroller (
	clk_clk,
	reset_reset_n,
	de2_115_tv_leds_ledg,
	de2_115_tv_leds_ledr,
	de2_115_tv_vga_vga_b,
	de2_115_tv_vga_vga_blank_n,
	de2_115_tv_vga_vga_clk,
	de2_115_tv_vga_vga_g,
	de2_115_tv_vga_vga_hs,
	de2_115_tv_vga_vga_r,
	de2_115_tv_vga_vga_sync_n,
	de2_115_tv_vga_vga_vs,
	de2_115_tv_i2c_i2c_sclk,
	de2_115_tv_i2c_i2c_sdat,
	de2_115_tv_tvdecoder_td_clk27,
	de2_115_tv_tvdecoder_td_data,
	de2_115_tv_tvdecoder_td_hs,
	de2_115_tv_tvdecoder_td_reset_n,
	de2_115_tv_tvdecoder_td_vs,
	de2_115_tv_sdram_dram_addr,
	de2_115_tv_sdram_dram_ba,
	de2_115_tv_sdram_dram_cas_n,
	de2_115_tv_sdram_dram_cke,
	de2_115_tv_sdram_dram_clk,
	de2_115_tv_sdram_dram_cs_n,
	de2_115_tv_sdram_dram_dq,
	de2_115_tv_sdram_dram_dqm,
	de2_115_tv_sdram_dram_ras_n,
	de2_115_tv_sdram_dram_we_n);	

	input		clk_clk;
	input		reset_reset_n;
	output	[8:0]	de2_115_tv_leds_ledg;
	output	[17:0]	de2_115_tv_leds_ledr;
	output	[7:0]	de2_115_tv_vga_vga_b;
	output		de2_115_tv_vga_vga_blank_n;
	output		de2_115_tv_vga_vga_clk;
	output	[7:0]	de2_115_tv_vga_vga_g;
	output		de2_115_tv_vga_vga_hs;
	output	[7:0]	de2_115_tv_vga_vga_r;
	output		de2_115_tv_vga_vga_sync_n;
	output		de2_115_tv_vga_vga_vs;
	output		de2_115_tv_i2c_i2c_sclk;
	inout		de2_115_tv_i2c_i2c_sdat;
	input		de2_115_tv_tvdecoder_td_clk27;
	input	[7:0]	de2_115_tv_tvdecoder_td_data;
	input		de2_115_tv_tvdecoder_td_hs;
	output		de2_115_tv_tvdecoder_td_reset_n;
	input		de2_115_tv_tvdecoder_td_vs;
	output	[12:0]	de2_115_tv_sdram_dram_addr;
	output	[1:0]	de2_115_tv_sdram_dram_ba;
	output		de2_115_tv_sdram_dram_cas_n;
	output		de2_115_tv_sdram_dram_cke;
	output		de2_115_tv_sdram_dram_clk;
	output		de2_115_tv_sdram_dram_cs_n;
	inout	[31:0]	de2_115_tv_sdram_dram_dq;
	output	[3:0]	de2_115_tv_sdram_dram_dqm;
	output		de2_115_tv_sdram_dram_ras_n;
	output		de2_115_tv_sdram_dram_we_n;
endmodule
