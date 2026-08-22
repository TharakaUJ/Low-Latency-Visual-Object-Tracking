//lpm_divide CBX_SINGLE_OUTPUT_FILE="ON" LPM_DREPRESENTATION="UNSIGNED" LPM_HINT="LPM_REMAINDERPOSITIVE=TRUE" LPM_NREPRESENTATION="UNSIGNED" LPM_PIPELINE=1 LPM_TYPE="LPM_DIVIDE" LPM_WIDTHD=4 LPM_WIDTHN=9 aclr clock denom numer quotient remain
//VERSION_BEGIN 25.1 cbx_mgl 2025:10:22:10:38:57:SC cbx_stratixii 2025:10:22:10:31:18:SC cbx_util_mgl 2025:10:22:10:31:18:SC  VERSION_END
// synthesis VERILOG_INPUT_VERSION VERILOG_2001
// altera message_off 10463



// Copyright (C) 2025  Altera Corporation. All rights reserved.
//  Your use of Altera Corporation's design tools, logic functions 
//  and other software and tools, and any partner logic 
//  functions, and any output files from any of the foregoing 
//  (including device programming or simulation files), and any 
//  associated documentation or information are expressly subject 
//  to the terms and conditions of the Altera Program License 
//  Subscription Agreement, the Altera Quartus Prime License Agreement,
//  the Altera IP License Agreement, or other applicable license
//  agreement, including, without limitation, that your use is for
//  the sole purpose of programming logic devices manufactured by
//  Altera and sold by Altera or its authorized distributors.  Please
//  refer to the Altera Software License Subscription Agreements 
//  on the Quartus Prime software download page.



//synthesis_resources = lpm_divide 1 
//synopsys translate_off
`timescale 1 ps / 1 ps
//synopsys translate_on
module  mghrm
	( 
	aclr,
	clock,
	denom,
	numer,
	quotient,
	remain) /* synthesis synthesis_clearbox=1 */;
	input   aclr;
	input   clock;
	input   [3:0]  denom;
	input   [8:0]  numer;
	output   [8:0]  quotient;
	output   [3:0]  remain;

	wire  [8:0]   wire_mgl_prim1_quotient;
	wire  [3:0]   wire_mgl_prim1_remain;

	lpm_divide   mgl_prim1
	( 
	.aclr(aclr),
	.clock(clock),
	.denom(denom),
	.numer(numer),
	.quotient(wire_mgl_prim1_quotient),
	.remain(wire_mgl_prim1_remain));
	defparam
		mgl_prim1.lpm_drepresentation = "UNSIGNED",
		mgl_prim1.lpm_nrepresentation = "UNSIGNED",
		mgl_prim1.lpm_pipeline = 1,
		mgl_prim1.lpm_type = "LPM_DIVIDE",
		mgl_prim1.lpm_widthd = 4,
		mgl_prim1.lpm_widthn = 9,
		mgl_prim1.lpm_hint = "LPM_REMAINDERPOSITIVE=TRUE";
	assign
		quotient = wire_mgl_prim1_quotient,
		remain = wire_mgl_prim1_remain;
endmodule //mghrm
//VALID FILE
