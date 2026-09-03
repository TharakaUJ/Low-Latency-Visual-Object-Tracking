module template_match #(
    parameter int WIN = 16
)(
    input logic clk,
    input logic rst_n,
    input logic search_start,
    input logic window_valid,
    input logic [7:0] data_in [WIN-1:0][WIN-1:0],

    input logic [9:0] current_x,
    input logic [9:0] current_y,

    output logic [9:0] temp_boundary_x,
    output logic [9:0] temp_boundary_y,

    output logic [31:0] debug_data
);

    localparam int SAD_W = $clog2(WIN*WIN*255 + 1);

    logic [SAD_W-1:0] min_sad;
    logic [SAD_W-1:0] total_sad;

    assign debug_data = {min_sad[SAD_W-1:0], total_sad[SAD_W-1:0]};

    // ------------------------------------------------------------
    // Template storage.
    //  - For small WIN (3x3, 5x5) a localparam array like below is fine,
    //    Quartus will fold it into LUTs/constants.
    //  - For WIN=32 (1024 bytes) switch this to a small ROM initialized
    //    with $readmemh from a .hex/.mif file instead of a localparam,
    //    e.g.:
    //        (* ramstyle = "M9K" *) logic [7:0] tmpl_rom [0:WIN*WIN-1];
    //        initial $readmemh("template32.hex", tmpl_rom);
    //    and index it as tmpl_rom[r*WIN+c]. That keeps it in one BRAM
    //    instead of ~1000 flip-flops / LUT constants.
    // ------------------------------------------------------------
    localparam logic [7:0] tmpl [WIN-1:0][WIN-1:0] = '{
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF},
        '{8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF, 8'hFF}
    };

    function automatic logic [7:0] absolute_difference(
        input logic [7:0] a,
        input logic [7:0] b
    );
        return (a > b) ? (a - b) : (b - a);
    endfunction

    // ------------------------------------------------------------
    // Combinational SAD calculation over the full WIN x WIN window.
    // At WIN=32 this is 1024 subtractors in one comb cloud — if timing
    // gets tight, pipeline this (e.g. sum in two stages, row-sums then
    // total) rather than doing it all as one combinational block.
    // ------------------------------------------------------------
    always_comb begin
        total_sad = '0;
        for (int r = 0; r < WIN; r++) begin
            for (int c = 0; c < WIN; c++) begin
                total_sad = total_sad + SAD_W'(absolute_difference(data_in[r][c], tmpl[r][c]));
            end
        end
    end

    // ------------------------------------------------------------
    // Sequential minimum tracking - only updates once the window is
    // actually full of valid image data.
    // ------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            min_sad         <= '1;
            temp_boundary_x <= 10'd0;
            temp_boundary_y <= 10'd0;
        end
        else if (search_start) begin
            min_sad         <= '1;
            temp_boundary_x <= 10'd0;
            temp_boundary_y <= 10'd0;
        end
        else if (window_valid) begin
            if (total_sad < min_sad) begin
                min_sad         <= total_sad;
                temp_boundary_x <= current_x;
                temp_boundary_y <= current_y;
            end
        end
    end

endmodule
