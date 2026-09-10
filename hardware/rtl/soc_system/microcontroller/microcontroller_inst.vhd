	component microcontroller is
		port (
			clk_clk                         : in    std_logic                     := 'X';             -- clk
			reset_reset_n                   : in    std_logic                     := 'X';             -- reset_n
			de2_115_tv_leds_ledg            : out   std_logic_vector(8 downto 0);                     -- ledg
			de2_115_tv_leds_ledr            : out   std_logic_vector(17 downto 0);                    -- ledr
			de2_115_tv_vga_vga_b            : out   std_logic_vector(7 downto 0);                     -- vga_b
			de2_115_tv_vga_vga_blank_n      : out   std_logic;                                        -- vga_blank_n
			de2_115_tv_vga_vga_clk          : out   std_logic;                                        -- vga_clk
			de2_115_tv_vga_vga_g            : out   std_logic_vector(7 downto 0);                     -- vga_g
			de2_115_tv_vga_vga_hs           : out   std_logic;                                        -- vga_hs
			de2_115_tv_vga_vga_r            : out   std_logic_vector(7 downto 0);                     -- vga_r
			de2_115_tv_vga_vga_sync_n       : out   std_logic;                                        -- vga_sync_n
			de2_115_tv_vga_vga_vs           : out   std_logic;                                        -- vga_vs
			de2_115_tv_i2c_i2c_sclk         : out   std_logic;                                        -- i2c_sclk
			de2_115_tv_i2c_i2c_sdat         : inout std_logic                     := 'X';             -- i2c_sdat
			de2_115_tv_tvdecoder_td_clk27   : in    std_logic                     := 'X';             -- td_clk27
			de2_115_tv_tvdecoder_td_data    : in    std_logic_vector(7 downto 0)  := (others => 'X'); -- td_data
			de2_115_tv_tvdecoder_td_hs      : in    std_logic                     := 'X';             -- td_hs
			de2_115_tv_tvdecoder_td_reset_n : out   std_logic;                                        -- td_reset_n
			de2_115_tv_tvdecoder_td_vs      : in    std_logic                     := 'X';             -- td_vs
			de2_115_tv_sdram_dram_addr      : out   std_logic_vector(12 downto 0);                    -- dram_addr
			de2_115_tv_sdram_dram_ba        : out   std_logic_vector(1 downto 0);                     -- dram_ba
			de2_115_tv_sdram_dram_cas_n     : out   std_logic;                                        -- dram_cas_n
			de2_115_tv_sdram_dram_cke       : out   std_logic;                                        -- dram_cke
			de2_115_tv_sdram_dram_clk       : out   std_logic;                                        -- dram_clk
			de2_115_tv_sdram_dram_cs_n      : out   std_logic;                                        -- dram_cs_n
			de2_115_tv_sdram_dram_dq        : inout std_logic_vector(31 downto 0) := (others => 'X'); -- dram_dq
			de2_115_tv_sdram_dram_dqm       : out   std_logic_vector(3 downto 0);                     -- dram_dqm
			de2_115_tv_sdram_dram_ras_n     : out   std_logic;                                        -- dram_ras_n
			de2_115_tv_sdram_dram_we_n      : out   std_logic                                         -- dram_we_n
		);
	end component microcontroller;

	u0 : component microcontroller
		port map (
			clk_clk                         => CONNECTED_TO_clk_clk,                         --                  clk.clk
			reset_reset_n                   => CONNECTED_TO_reset_reset_n,                   --                reset.reset_n
			de2_115_tv_leds_ledg            => CONNECTED_TO_de2_115_tv_leds_ledg,            --      de2_115_tv_leds.ledg
			de2_115_tv_leds_ledr            => CONNECTED_TO_de2_115_tv_leds_ledr,            --                     .ledr
			de2_115_tv_vga_vga_b            => CONNECTED_TO_de2_115_tv_vga_vga_b,            --       de2_115_tv_vga.vga_b
			de2_115_tv_vga_vga_blank_n      => CONNECTED_TO_de2_115_tv_vga_vga_blank_n,      --                     .vga_blank_n
			de2_115_tv_vga_vga_clk          => CONNECTED_TO_de2_115_tv_vga_vga_clk,          --                     .vga_clk
			de2_115_tv_vga_vga_g            => CONNECTED_TO_de2_115_tv_vga_vga_g,            --                     .vga_g
			de2_115_tv_vga_vga_hs           => CONNECTED_TO_de2_115_tv_vga_vga_hs,           --                     .vga_hs
			de2_115_tv_vga_vga_r            => CONNECTED_TO_de2_115_tv_vga_vga_r,            --                     .vga_r
			de2_115_tv_vga_vga_sync_n       => CONNECTED_TO_de2_115_tv_vga_vga_sync_n,       --                     .vga_sync_n
			de2_115_tv_vga_vga_vs           => CONNECTED_TO_de2_115_tv_vga_vga_vs,           --                     .vga_vs
			de2_115_tv_i2c_i2c_sclk         => CONNECTED_TO_de2_115_tv_i2c_i2c_sclk,         --       de2_115_tv_i2c.i2c_sclk
			de2_115_tv_i2c_i2c_sdat         => CONNECTED_TO_de2_115_tv_i2c_i2c_sdat,         --                     .i2c_sdat
			de2_115_tv_tvdecoder_td_clk27   => CONNECTED_TO_de2_115_tv_tvdecoder_td_clk27,   -- de2_115_tv_tvdecoder.td_clk27
			de2_115_tv_tvdecoder_td_data    => CONNECTED_TO_de2_115_tv_tvdecoder_td_data,    --                     .td_data
			de2_115_tv_tvdecoder_td_hs      => CONNECTED_TO_de2_115_tv_tvdecoder_td_hs,      --                     .td_hs
			de2_115_tv_tvdecoder_td_reset_n => CONNECTED_TO_de2_115_tv_tvdecoder_td_reset_n, --                     .td_reset_n
			de2_115_tv_tvdecoder_td_vs      => CONNECTED_TO_de2_115_tv_tvdecoder_td_vs,      --                     .td_vs
			de2_115_tv_sdram_dram_addr      => CONNECTED_TO_de2_115_tv_sdram_dram_addr,      --     de2_115_tv_sdram.dram_addr
			de2_115_tv_sdram_dram_ba        => CONNECTED_TO_de2_115_tv_sdram_dram_ba,        --                     .dram_ba
			de2_115_tv_sdram_dram_cas_n     => CONNECTED_TO_de2_115_tv_sdram_dram_cas_n,     --                     .dram_cas_n
			de2_115_tv_sdram_dram_cke       => CONNECTED_TO_de2_115_tv_sdram_dram_cke,       --                     .dram_cke
			de2_115_tv_sdram_dram_clk       => CONNECTED_TO_de2_115_tv_sdram_dram_clk,       --                     .dram_clk
			de2_115_tv_sdram_dram_cs_n      => CONNECTED_TO_de2_115_tv_sdram_dram_cs_n,      --                     .dram_cs_n
			de2_115_tv_sdram_dram_dq        => CONNECTED_TO_de2_115_tv_sdram_dram_dq,        --                     .dram_dq
			de2_115_tv_sdram_dram_dqm       => CONNECTED_TO_de2_115_tv_sdram_dram_dqm,       --                     .dram_dqm
			de2_115_tv_sdram_dram_ras_n     => CONNECTED_TO_de2_115_tv_sdram_dram_ras_n,     --                     .dram_ras_n
			de2_115_tv_sdram_dram_we_n      => CONNECTED_TO_de2_115_tv_sdram_dram_we_n       --                     .dram_we_n
		);

