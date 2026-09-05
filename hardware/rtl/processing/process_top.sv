module process_top #(
    parameter int WIN = 16,
    parameter int IMG_W  = 640,
    parameter int IMG_H  = 480
)(
    input logic clk,
    input logic rst_n,

    input logic [7:0] Y,
    input logic data_valid_in,
    input logic v_sync,
    input logic [9:0] TV_X,

    output logic [9:0] boundary_x,
    output logic [9:0] boundary_y,

    output logic [31:0] debug_data
);

    logic [9:0] temp_boundary_x;
    logic [9:0] temp_boundary_y;

    logic [8:0] line_count;
    logic [9:0] pixel_count;

    logic [7:0] window [WIN-1:0][WIN-1:0];
    logic       window_valid;
    logic [$clog2(IMG_W)-1:0] anchor_x;
    logic [$clog2(IMG_H)-1:0] anchor_y;

    logic v_sync_d;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) v_sync_d <= 1'b0;
        else        v_sync_d <= v_sync;
    end
    wire frame_done = v_sync & ~v_sync_d;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            boundary_x  <= 10'd0;
            boundary_y  <= 10'd0;
            line_count  <= 9'd0;
            pixel_count <= 10'd0;
        end
        else if (frame_done) begin
            boundary_x  <= temp_boundary_x;
            boundary_y  <= temp_boundary_y;
            line_count  <= 9'd0;
            pixel_count <= 10'd0;
        end
        else if (data_valid_in) begin
            if (pixel_count == 10'd639) begin
                pixel_count <= 10'd0;
                if (line_count == 9'd479)
                    line_count <= 9'd0;
                else
                    line_count <= line_count + 9'd1;
            end
            else begin
                pixel_count <= pixel_count + 10'd1;
            end
        end
    end

    window_buffer #(
        .WIN   (WIN),
        .IMG_W (640),
        .IMG_H (480)
    ) window_buffer_inst (
        .clk          (clk),
        .rst_n        (rst_n),
        .clock_enable (data_valid_in),
        .frame_done   (frame_done),
        .data_in      (Y),
        .window_out   (window),
        .window_valid (window_valid),
        .anchor_x     (anchor_x),
        .anchor_y     (anchor_y)
    );

    template_match #(
        .WIN (WIN)
    ) template_match_inst (
        .clk             (clk),
        .rst_n           (rst_n),
        .search_start    (frame_done),
        .window_valid    (window_valid),
        .data_in         (window),
        .current_x       (anchor_x),
        .current_y       (anchor_y),
        .temp_boundary_x (temp_boundary_x),
        .temp_boundary_y (temp_boundary_y),
        .debug_data      (debug_data)
    );

endmodule