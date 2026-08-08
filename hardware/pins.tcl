# ==============================================================================
# Pin & Location Assignments
# ==============================================================================
# VGA_R[0] PIN_E12 VGA Red[0] 3.3V
# VGA_R[1] PIN_E11 VGA Red[1] 3.3V
# VGA_R[2] PIN_D10 VGA Red[2] 3.3V
# VGA_R[3] PIN_F12 VGA Red[3] 3.3V
# VGA_R[4] PIN_G10 VGA Red[4] 3.3V
# VGA_R[5] PIN_J12 VGA Red[5] 3.3V
# VGA_R[6] PIN_H8 VGA Red[6] 3.3V
# VGA_R[7] PIN_H10 VGA Red[7] 3.3V
# VGA_G[0] PIN_G8 VGA Green[0] 3.3V
# VGA_G[1] PIN_G11 VGA Green[1] 3.3V
# VGA_G[2] PIN_F8 VGA Green[2] 3.3V
# VGA_G[3] PIN_H12 VGA Green[3] 3.3V
# VGA_G[4] PIN_C8 VGA Green[4] 3.3V
# VGA_G[5] PIN_B8 VGA Green[5] 3.3V
# VGA_G[6] PIN_F10 VGA Green[6] 3.3V
# VGA_G[7] PIN_C9 VGA Green[7] 3.3V
# VGA_B[0] PIN_B10 VGA Blue[0] 3.3V
# VGA_B[1] PIN_A10 VGA Blue[1] 3.3V
# VGA_B[2] PIN_C11 VGA Blue[2] 3.3V
# VGA_B[3] PIN_B11 VGA Blue[3] 3.3V
# VGA_B[4] PIN_A11 VGA Blue[4] 3.3V
# VGA_B[5] PIN_C12 VGA Blue[5] 3.3V
# VGA_B[6] PIN_D11 VGA Blue[6] 3.3V
# VGA_B[7] PIN_D12 VGA Blue[7] 3.3V
# VGA_CLK PIN_A12 VGA Clock 3.3V
# VGA_BLANK_N PIN_F11 VGA BLANK 3.3V
# VGA_HS PIN_G13 VGA H_SYNC 3.3V
# VGA_VS PIN_C13 VGA V_SYNC 3.3V
# VGA_SYNC_N PIN_C10 VGA SYNC 3.3V


# TD_ DATA [0] PIN_E8 TV Decoder Data[0] 3.3V
# TD_ DATA [1] PIN_A7 TV Decoder Data[1] 3.3V
# TD_ DATA [2] PIN_D8 TV Decoder Data[2] 3.3V
# TD_ DATA [3] PIN_C7 TV Decoder Data[3] 3.3V
# TD_ DATA [4] PIN_D7 TV Decoder Data[4] 3.3V
# TD_ DATA [5] PIN_D6 TV Decoder Data[5] 3.3V
# TD_ DATA [6] PIN_E7 TV Decoder Data[6] 3.3V
# TD_ DATA [7] PIN_F7 TV Decoder Data[7] 3.3V
# TD_HS PIN_E5 TV Decoder H_SYNC 3.3V
# TD_VS PIN_E4 TV Decoder V_SYNC 3.3V
# TD_CLK27 PIN_B14 TV Decoder Clock Input. 3.3V
# TD_RESET_N PIN_G7 TV Decoder Reset 3.3V
# I2C_SCLK PIN_B7 I2C Clock 3.3V
# I2C_SDAT PIN_A8 I2C Data 3.3V
# ------------------------------------------------------------------------------
# Clock and Reset (Using standard DE2-115 pins)
# ------------------------------------------------------------------------------
set_location_assignment PIN_Y2 -to CLOCK_50
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to CLOCK_50

set_location_assignment PIN_M23 -to KEY[0]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to KEY[0]

# ------------------------------------------------------------------------------
# VGA Red
# ------------------------------------------------------------------------------
set_location_assignment PIN_E12 -to VGA_R[0]
set_location_assignment PIN_E11 -to VGA_R[1]
set_location_assignment PIN_D10 -to VGA_R[2]
set_location_assignment PIN_F12 -to VGA_R[3]
set_location_assignment PIN_G10 -to VGA_R[4]
set_location_assignment PIN_J12 -to VGA_R[5]
set_location_assignment PIN_H8  -to VGA_R[6]
set_location_assignment PIN_H10 -to VGA_R[7]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_R[*]

# ------------------------------------------------------------------------------
# VGA Green
# ------------------------------------------------------------------------------
set_location_assignment PIN_G8  -to VGA_G[0]
set_location_assignment PIN_G11 -to VGA_G[1]
set_location_assignment PIN_F8  -to VGA_G[2]
set_location_assignment PIN_H12 -to VGA_G[3]
set_location_assignment PIN_C8  -to VGA_G[4]
set_location_assignment PIN_B8  -to VGA_G[5]
set_location_assignment PIN_F10 -to VGA_G[6]
set_location_assignment PIN_C9  -to VGA_G[7]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_G[*]

# ------------------------------------------------------------------------------
# VGA Blue
# ------------------------------------------------------------------------------
set_location_assignment PIN_B10 -to VGA_B[0]
set_location_assignment PIN_A10 -to VGA_B[1]
set_location_assignment PIN_C11 -to VGA_B[2]
set_location_assignment PIN_B11 -to VGA_B[3]
set_location_assignment PIN_A11 -to VGA_B[4]
set_location_assignment PIN_C12 -to VGA_B[5]
set_location_assignment PIN_D11 -to VGA_B[6]
set_location_assignment PIN_D12 -to VGA_B[7]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_B[*]

# ------------------------------------------------------------------------------
# VGA Control Signals
# ------------------------------------------------------------------------------
set_location_assignment PIN_A12 -to VGA_CLK
set_location_assignment PIN_F11 -to VGA_BLANK_N
set_location_assignment PIN_G13 -to VGA_HS
set_location_assignment PIN_C13 -to VGA_VS
set_location_assignment PIN_C10 -to VGA_SYNC_N

set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_CLK
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_BLANK_N
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_HS
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_VS
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to VGA_SYNC_N

# ------------------------------------------------------------------------------
# TV Decoder Hardware Pins
# ------------------------------------------------------------------------------
set_location_assignment PIN_E8  -to TD_DATA[0]
set_location_assignment PIN_A7  -to TD_DATA[1]
set_location_assignment PIN_D8  -to TD_DATA[2]
set_location_assignment PIN_C7  -to TD_DATA[3]
set_location_assignment PIN_D7  -to TD_DATA[4]
set_location_assignment PIN_D6  -to TD_DATA[5]
set_location_assignment PIN_E7  -to TD_DATA[6]
set_location_assignment PIN_F7  -to TD_DATA[7]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to TD_DATA[*]

set_location_assignment PIN_E5  -to TD_HS
set_location_assignment PIN_E4  -to TD_VS
set_location_assignment PIN_B14 -to TD_CLK27
set_location_assignment PIN_G7  -to TD_RESET_N

set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to TD_HS
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to TD_VS
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to TD_CLK27
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to TD_RESET_N

# ------------------------------------------------------------------------------
# I2C Pins (Provided in list but absent in RTL top module)
# Uncomment these if you add I2C_SCLK and I2C_SDAT to your module ports
# ------------------------------------------------------------------------------
# set_location_assignment PIN_B7 -to I2C_SCLK
# set_location_assignment PIN_A8 -to I2C_SDAT
# set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to I2C_SCLK
# set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to I2C_SDAT