module process_top #(
    parameter int WIN = 16,
    parameter int IMG_W  = 640,
    parameter int IMG_H  = 480
)(
    input logic clk,       // 27 MHz - pixel/processing domain
    input logic clk_50,    // 50 MHz - Avalon-MM domain
    input logic rst_n,

    // avalon slave interface (clk_50 domain)
    input logic [8:0] avs_address,   // widened: 2 bound regs + 256 template regs (9 bits = 0..511)
    input logic avs_read,
    output logic [31:0] avs_readdata,
    input logic avs_write,
    input logic [31:0] avs_writedata,
    output logic avs_waitrequest,

    input logic [7:0] Y,
    input logic data_valid_in,
    input logic v_sync,
    input logic [9:0] TV_X,

    output logic [9:0] boundary_x,
    output logic [9:0] boundary_y,

    output logic [31:0] debug_data
);

    localparam int IDX_WIDTH = $clog2(WIN*WIN);

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

    // -----------------------------------------------------------------
    // CDC #1: boundary_x/boundary_y, produced in the clk (27MHz) domain,
    // need to be read out over Avalon in the clk_50 domain. They update
    // once per frame (frame_done), so a toggle-strobe + registered-capture
    // bus sync is safe and cheap. The two are packed together so they are
    // captured as one atomic pair on the clk_50 side.
    // -----------------------------------------------------------------
    logic [19:0] bound_sync_50;
    wire  [9:0]  bound_x_50 = bound_sync_50[19:10];
    wire  [9:0]  bound_y_50 = bound_sync_50[9:0];

    cdc_bus_sync #(
        .WIDTH (20)
    ) u_bound_cdc (
        .src_clk   (clk),
        .src_rst_n (rst_n),
        .src_data  ({boundary_x, boundary_y}),
        .src_valid (frame_done),          // boundary_x/y update exactly on frame_done

        .dst_clk   (clk_50),
        .dst_rst_n (rst_n),
        .dst_data  (bound_sync_50)
    );

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

    // -----------------------------------------------------------------
    // CDC #2: template register-file writes originate on the Avalon slave
    // (clk_50 domain) but the register file physically lives inside
    // template_match, clocked by clk (27MHz). avalon_slave_top already
    // handshakes (busy/waitrequest) so only one request is outstanding at
    // a time; cdc_pulse_sync ferries the request pulse over to clk domain
    // and the ack pulse back.
    // -----------------------------------------------------------------
    logic                  tmpl_wr_req_50;
    logic [IDX_WIDTH-1:0]  tmpl_wr_index_50;
    logic [7:0]            tmpl_wr_data_50;
    logic                  tmpl_wr_ack_50;

    logic                  tmpl_wr_pulse_clk;
    logic [IDX_WIDTH-1:0]  tmpl_wr_index_clk;
    logic [7:0]            tmpl_wr_data_clk;

    cdc_pulse_sync u_tmpl_req_cdc (
        .src_clk   (clk_50),
        .src_rst_n (rst_n),
        .src_pulse (tmpl_wr_req_50),

        .dst_clk   (clk),
        .dst_rst_n (rst_n),
        .dst_pulse (tmpl_wr_pulse_clk)
    );

    // index/data are captured combinationally alongside tmpl_wr_req_50 by
    // avalon_slave_top and held stable (via its busy/waitrequest handshake)
    // until tmpl_wr_ack_50 arrives, so no separate CDC is needed for them -
    // by the time tmpl_wr_pulse_clk fires they've been stable for many
    // clk_50 cycles already. We just re-register them onto clk for timing.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tmpl_wr_index_clk <= '0;
            tmpl_wr_data_clk  <= '0;
        end else begin
            tmpl_wr_index_clk <= tmpl_wr_index_50;
            tmpl_wr_data_clk  <= tmpl_wr_data_50;
        end
    end

    cdc_pulse_sync u_tmpl_ack_cdc (
        .src_clk   (clk),
        .src_rst_n (rst_n),
        .src_pulse (tmpl_wr_pulse_clk),

        .dst_clk   (clk_50),
        .dst_rst_n (rst_n),
        .dst_pulse (tmpl_wr_ack_50)
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
        .debug_data      (debug_data),
        .tmpl_wr_pulse   (tmpl_wr_pulse_clk),
        .tmpl_wr_index   (tmpl_wr_index_clk),
        .tmpl_wr_data    (tmpl_wr_data_clk)
    );

    avalon_slave_top #(
        .DATA_WIDTH (32),
        .WIN        (WIN)
    ) avalon_slave_inst (
        .clk            (clk_50),
        .reset          (~rst_n),
        .avs_address    (avs_address),
        .avs_read       (avs_read),
        .avs_readdata   (avs_readdata),
        .avs_write      (avs_write),
        .avs_writedata  (avs_writedata),
        .avs_waitrequest(avs_waitrequest),
        .bound_x        (bound_x_50),
        .bound_y        (bound_y_50),
        .tmpl_wr_req    (tmpl_wr_req_50),
        .tmpl_wr_index  (tmpl_wr_index_50),
        .tmpl_wr_data   (tmpl_wr_data_50),
        .tmpl_wr_ack    (tmpl_wr_ack_50)
    );
endmodule
