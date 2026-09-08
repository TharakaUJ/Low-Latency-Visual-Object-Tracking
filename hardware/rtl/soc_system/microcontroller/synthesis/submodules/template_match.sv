module template_match #(
    parameter int WIN = 16,
    parameter int IMG_W  = 640,
    parameter int IMG_H  = 480,
    parameter int IDX_WIDTH = $clog2(WIN*WIN)
)(
    input logic clk,
    input logic rst_n,
    input logic search_start,
    input logic window_valid,
    input logic [7:0] data_in [WIN-1:0][WIN-1:0],
    input logic [$clog2(IMG_W)-1:0] current_x,
    input logic [$clog2(IMG_H)-1:0] current_y,
    output logic [9:0] temp_boundary_x,
    output logic [9:0] temp_boundary_y,
    output logic [31:0] debug_data,

    // Template register-file write port. tmpl_wr_pulse is expected to
    // already be synchronized into THIS (clk) clock domain - e.g. by
    // cdc_pulse_sync at the top level, bridging from the Avalon slave
    // which lives on clk_50. tmpl_wr_index = row*WIN + col.
    input logic                   tmpl_wr_pulse,
    input logic [IDX_WIDTH-1:0]   tmpl_wr_index,
    input logic [7:0]             tmpl_wr_data
);
    localparam int SAD_W = $clog2(WIN*WIN*255 + 1);
    logic [SAD_W-1:0] min_sad;
    logic [SAD_W-1:0] total_sad;
    assign debug_data = {min_sad[SAD_W-1:0], total_sad[SAD_W-1:0]};

    // Template register file - now a real, runtime-writable array instead
    // of a fixed 'initial' constant. Reset to 8'hFF to preserve the old
    // default behavior until the host loads a real template.
    logic [7:0] tmpl [WIN-1:0][WIN-1:0];

    wire [$clog2(WIN)-1:0] tmpl_wr_row = tmpl_wr_index / WIN;
    wire [$clog2(WIN)-1:0] tmpl_wr_col = tmpl_wr_index % WIN;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int r = 0; r < WIN; r++)
                for (int c = 0; c < WIN; c++)
                    tmpl[r][c] <= 8'hFF;
        end else if (tmpl_wr_pulse) begin
            tmpl[tmpl_wr_row][tmpl_wr_col] <= tmpl_wr_data;
        end
    end

    function automatic logic [7:0] absolute_difference(input logic [7:0] a, input logic [7:0] b);
        return (a > b) ? (a - b) : (b - a);
    endfunction

    always_comb begin
        total_sad = '0;
        for (int r = 0; r < WIN; r++)
            for (int c = 0; c < WIN; c++)
                total_sad = total_sad + SAD_W'(absolute_difference(data_in[r][c], tmpl[r][c]));
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            min_sad <= '1; temp_boundary_x <= 10'd0; temp_boundary_y <= 10'd0;
        end else if (search_start) begin
            min_sad <= '1; temp_boundary_x <= 10'd0; temp_boundary_y <= 10'd0;
        end else if (window_valid) begin
            if (total_sad < min_sad) begin
                min_sad <= total_sad; temp_boundary_x <= current_x; temp_boundary_y <= current_y;
            end
        end
    end
endmodule
