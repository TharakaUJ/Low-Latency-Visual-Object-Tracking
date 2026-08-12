`timescale 1ns/1ps

module frame_buffer # (
    parameter integer WIDTH  = 720,
    parameter integer HEIGHT = 480,
    parameter integer DATA_WIDTH  = 8
)(
) (
    input  wire       CLOCK_50,
    input  wire [DATA_WIDTH-1:0] iVideo_R,
    input  wire [DATA_WIDTH-1:0] iVideo_G,
    input  wire [DATA_WIDTH-1:0] iVideo_B,
    input  wire       iVideo_Valid,
    input  wire       iV_Sync,
    input  wire       iH_Sync,

    output wire [(3*DATA_WIDTH)-1:0] data_out,
    input wire [$clog2(WIDTH*HEIGHT)-1:0] read_addr,

    output wire[DATA_WIDTH-1:0] oVideo_R,
    output wire[DATA_WIDTH-1:0] oVideo_G,
    output wire[DATA_WIDTH-1:0] oVideo_B,


);

endmodule