`default_nettype none
module top1 (
   input  wire CLK,
   input  wire RST,
   input  wire tx_OK,
   output wire tx_en,
   output wire [7:0] tx_data_out,
   input wire [7:0] rx_data_in,  
   input wire rx_dv,
   output wire [31:0]  o_Status
);
 
localparam NM = 21; // address width for state vector's and cost function's BRAM. Thus, the number of maximum qubits the system can deal with.
localparam NG = 10; // address width of general memory
localparam P = 64; // data width for numerical number
localparam Ni = 5 + 24 + NM;// data width of auxiary information on pipeline.
localparam NBRAM = 1; // number of block RAMs connected to qaoa system. 
localparam N_BIT_SWAP_POINTER = $clog2(NM);
localparam LP_BRAM_A = 2; // Address transmisshon pipeline latency
localparam LP_BRAM_D = 1; // Data retrieving pipeline latency 
localparam LP_GEN_COST = 0;
localparam LP_MIXER_IN = 0;
localparam LP_MIXER_OUT = 0;
localparam L_BRAM_W = LP_BRAM_A + LP_BRAM_D + 2; // Write latency
localparam L_BRAM_R = LP_BRAM_A + LP_BRAM_D + 2; // Read latency


// Declare signals to connect to the UART module
wire  [P-1:0] ci_r_data;
wire  [P-1:0] ci_addr;
wire  [P-1:0] ci_w_data;
wire ci_r_req;
wire ci_r_vd;
wire ci_w_req;

wire [23:0] ci_CMD;
wire [15:0] rS; // status of qaoa system.
// we need transmitter and receiver to tset state machine (ntu_smachine)
assign o_Status = rS[15:0];

wire [1 + 8 + NM-1:0] ag_CI_wire, ag_CI_wireR;

wire f_run_Computation;

wire [NM-1:0] ag_cAddr;       // Next address counter
wire [N_BIT_SWAP_POINTER-1:0] bsp1;
wire [N_BIT_SWAP_POINTER-1:0] bsp2;

wire [NM-1:0] bram_H_addr [NBRAM];
wire [P-1:0] bram_H_data_w [NBRAM];
wire [P-1:0] bram_H_data_r [NBRAM];
wire [NBRAM-1:0] bram_H_wen;

wire [NG-1:0] bram_G_addr;
wire [P-1:0] bram_G_data_w;
wire [P-1:0] bram_G_data_r;
wire bram_G_wen;

wire [NM-1:0] bram_s_addr_r [NBRAM];
wire [NM-1:0] bram_s_addr_w [NBRAM];
wire [P-1:0] bram_sR_data_r [NBRAM];
wire [P-1:0] bram_sI_data_r [NBRAM];
wire [P-1:0] bram_sR_data_w [NBRAM];
wire [P-1:0] bram_sI_data_w [NBRAM];
wire [NBRAM-1:0] bram_sR_wen;
wire [NBRAM-1:0] bram_sI_wen;

wire [P-1:0] cosb, sinb;
wire [P-1:0] p_ar, p_ai,  p_ar_o,p_ai_o;
wire  [Ni-1:0]  ag_info; // information, like addresses, enabled signal, and so on.
wire  [Ni-1:0]  bs_info, bs_infoR; // information, like addresses, enabled signal, and so on.
wire  [1:0]  mix_switch; // information, like addresses, enabled signal, and so on.
wire [NM:0] mix_info, mix_infoR;  // NM-1:0 is for address, NM for enable signal.

wire  [P-1:0]  gamma, gammaP; // cos gamma
wire  [P-1:0]  HGC, HGCP;
wire  [P-1:0]  Hr_o, Hr_oP;
wire  [P-1:0]  Hi_o, Hi_oP;

wire [NM-1:0] bswap_out, bswap_outR;

reg RSTci, RSTag, RSTqs; 
always @(posedge CLK) begin
   RSTci <= RST;
   RSTag <= RST;
   RSTqs <= RST;
end

control_interface #(.P(P), .NM(NM)) CI 
(
   .CLK(CLK),        // Connect to your system clock wire
   .RST(RSTci),        // Connect to your system reset wire
   .tx_OK(tx_OK),
   .tx_en(tx_en),
   .tx_data_out(tx_data_out),
   .rx_data_in(rx_data_in),
   .rx_dv(rx_dv),
   // --------- interfaces to qaoa system
   .r_data(ci_r_data),
   .addr_out(ci_addr),
   .r_req(ci_r_req),
   .rbram_vd(ci_r_vd),
   .w_data(ci_w_data),
   .w_req(ci_w_req),
   .CMD(ci_CMD),
   .rS(rS),
   // --------- interfaces to addr_gen

   .ag_addr_Param_out(ag_CI_wire[0+:8]),
   .ag_Param_out(ag_CI_wire[8+:NM]),
   .ag_wen_out(ag_CI_wire[8+NM])
   
);


regPipeline  #(.W_INFO($bits(ag_CI_wire)), .NPipe(4)) P_ci_addr (
   .CLK(CLK),
   .info_in(ag_CI_wire),
   .info_out(ag_CI_wireR)
);


addr_gen #(.N_BIT_SWAP_POINTER(N_BIT_SWAP_POINTER), .NM(NM)) addr_gen_inst(
   .CLK(CLK),
   .RST(RSTag), 
   // connected to control interface
   .addr_Param_in(ag_CI_wireR[0+:8]),
   .Param_in(ag_CI_wireR[8+:NM]),
   .wen_in(ag_CI_wireR[8+NM]),
   // connected to qaoa_system
   .en_Pipe_out(ag_info[0]),
   .en_CostF_out(ag_info[1]),
   .f_run_Computation_in(f_run_Computation),
   .f_L1Computation_out(ag_info[2]),
   .en_Inits_out(ag_info[5+:24]),
   .mixSwitch_out(ag_info[4:3]),
   .cAddrGC_out(ag_info[29+:NM]),
   // connected to bit_swap
   .cAddr_out(ag_cAddr),
   .bsp1_out(bsp1),
   .bsp2_out(bsp2)
);

qaoa_system2 #(.NM(NM), .NG(NG), .P(P), .NBRAM(NBRAM),  .L_BRAM_R(L_BRAM_R)) qs2
(
   .CLK(CLK),
   .RST(RSTqs),
   
    //------------------------------------------------------------------------
    // COMMAND INTERFACE (among Control Interface and addr_gen)
    //------------------------------------------------------------------------
   .enPipe_in(bs_infoR[0]),
   .enCostF_in(bs_infoR[1]),
   .f_L1Computation_in(bs_infoR[2]),
   .en_Inits_in(bs_infoR[5+:24]),
   .mixSwitch_in(bs_infoR[4:3]),
   .f_run_Computation_out(f_run_Computation),
   
    //------------------------------------------------------------------------
    // Address INTERFACE (FOR MIXER, and COST FUNCTION GEN)
    //------------------------------------------------------------------------
   .swapped_cAddr_in(bswap_outR),
   .cAddrCF_in(bs_infoR[29+:NM]),
    //------------------------------------------------------------------------
    // MEMORY INTERFACE from Control Interface
    //------------------------------------------------------------------------

   .r_data(ci_r_data),
   .n_ci_addr_in(ci_addr),
   .n_r_req(ci_r_req),
   .r_vd(ci_r_vd),
   .n_w_data(ci_w_data),
   .n_w_req(ci_w_req),
   .r_CMD(ci_CMD),

    //------------------------------------------------------------------------
    //BRAM ARRAY INTERFACE (3 banks + 1 general bank)
    //------------------------------------------------------------------------
   .bram_s_addr_r(bram_s_addr_r),
   .bram_s_addr_w(bram_s_addr_w),
   .bram_sR_data_r(bram_sR_data_r),
   .bram_sI_data_r(bram_sI_data_r),
   .bram_sR_data_w(bram_sR_data_w),
   .bram_sI_data_w(bram_sI_data_w),
   .bram_sR_wen(bram_sR_wen),
   .bram_sI_wen(bram_sI_wen),

   .bram_H_addr(bram_H_addr),
   .bram_H_data_r(bram_H_data_r),
   .bram_H_data_w(bram_H_data_w),
   .bram_H_wen(bram_H_wen),
   
   .bram_G_addr(bram_G_addr),
   .bram_G_data_r(bram_G_data_r),
   .bram_G_data_w(bram_G_data_w),
   .bram_G_wen(bram_G_wen),

    //------------------------------------------------------------------------
    // MIXER OPERATION PIPELINE INTERFACE
    //------------------------------------------------------------------------

   .cosb(cosb),
   .sinb(sinb),
   .mix_ar(p_ar),
   .mix_ai(p_ai),
   .mix_info(mix_info),
   .mix_switch(mix_switch),
   
   .mix_ar_res(p_ar_o),
   .mix_ai_res(p_ai_o),
   .mix_info_res(mix_infoR),
   .Status(rS),

    //------------------------------------------------------------------------
    // COST HAMILTONIAN INTERFACE
    //------------------------------------------------------------------------
   .gamma(gamma), 
   .HGC(HGC),
   .Hr_res(Hr_o),
   .Hi_res(Hi_o)


);

regPipeline  #(.W_INFO($bits({bs_info, bswap_out})), .NPipe(4)) P_bs_system (
   .CLK(CLK),
   .info_in({bs_info, bswap_out}),
   .info_out({bs_infoR, bswap_outR})
);

bit_swap #(.M(N_BIT_SWAP_POINTER), .N(NM), .Np(5), .Ni(Ni)) bit_swap_inst(
    .CLK(CLK),
    .a_in(ag_cAddr),
    .a_out(bswap_out),
    .q_in(bsp1),
    .p_in(bsp2),
    .info_in(ag_info),
    .info_out(bs_info)
);

// gen_costFixedP  #(.P(P)) inst_gencostFixedP
//   (
//    .CLK(CLK), // input
//    .gamma(gammaP), //  gamma, input
//    .H(HGCP), // input
//    .Hr_o(Hr_o),
//    .Hi_o(Hi_o)
// );

updated_gen_cost #(.P(P)) inst_updated_gencost
  (
   .CLK(CLK), // input
   .gamma(gamma), //  gamma, input
   .H(HGC), // input
   .Hr_o(Hr_o),
   .Hi_o(Hi_o)
);

Update_mixer #(.P(P),.Ni(NM+1)) Umix // width of additional information
(
   .CLK(CLK),
   .cos_beta(cosb), // cos beta
   .sin_beta(sinb), // sin beta
   .p_r(p_ar),
   .p_i(p_ai),
   .p_r_o(p_ar_o),
   .p_i_o(p_ai_o),
   .switch_in(mix_switch),
   .info_in(mix_info), // information, like addresses, enabled signal, and so on.
   .info_out(mix_infoR) // information, like addresses, enabled signal, and so on.
);


genvar j;

generate
    for (j = 0; j < NBRAM; j = j + 1) begin : GEN_BRAM

        // ================================================================
        // Stage p0 registers
        // These capture qaoa_system2 outputs first.
        // ================================================================

        reg [P-1:0]  Rdata_w_p0 /* synthesis preserve */;
        reg [P-1:0]  Idata_w_p0 /* synthesis preserve */;
        reg [P-1:0]  Hdata_w_p0 /* synthesis preserve */;

        reg [NM-1:0] Raddr_w_p0 /* synthesis preserve maxfan = 16 */;
        reg [NM-1:0] Raddr_r_p0 /* synthesis preserve maxfan = 16 */;

        reg [NM-1:0] Iaddr_w_p0 /* synthesis preserve maxfan = 16 */;
        reg [NM-1:0] Iaddr_r_p0 /* synthesis preserve maxfan = 16 */;

        reg [NM-1:0] Haddr_p0   /* synthesis preserve maxfan = 16 */;

        reg Rwen_p0 /* synthesis preserve */;
        reg Iwen_p0 /* synthesis preserve */;
        reg Hwen_p0 /* synthesis preserve */;


        // ================================================================
        // Final RAM-input registers
        // These directly drive each RAM instance.
        // Quartus can place these close to each RAM port.
        // ================================================================

        reg [P-1:0]  Rdata_w /* synthesis preserve */;
        reg [P-1:0]  Idata_w /* synthesis preserve */;
        reg [P-1:0]  Hdata_w /* synthesis preserve */;

        reg [NM-1:0] Raddr_w /* synthesis preserve maxfan = 16 */;
        reg [NM-1:0] Raddr_r /* synthesis preserve maxfan = 16 */;

        reg [NM-1:0] Iaddr_w /* synthesis preserve maxfan = 16 */;
        reg [NM-1:0] Iaddr_r /* synthesis preserve maxfan = 16 */;

        reg [NM-1:0] Haddr   /* synthesis preserve maxfan = 16 */;

        reg Rwen /* synthesis preserve */;
        reg Iwen /* synthesis preserve */;
        reg Hwen /* synthesis preserve */;


        // ================================================================
        // Registered RAM read outputs
        // ================================================================

        reg  [P-1:0] Rdata_r;
        reg  [P-1:0] Idata_r;
        reg  [P-1:0] Hdata_r;

        wire [P-1:0] mRdata_r;
        wire [P-1:0] mIdata_r;
        wire [P-1:0] mHdata_r;


        // ================================================================
        // Two-stage RAM input pipeline
        // ================================================================

        always @(posedge CLK) begin

            // ------------------------------------------------------------
            // Pipeline stage p0
            // Capture signals from qaoa_system2
            // ------------------------------------------------------------

            Rdata_w_p0 <= bram_sR_data_w[j];
            Idata_w_p0 <= bram_sI_data_w[j];
            Hdata_w_p0 <= bram_H_data_w[j];

            Raddr_w_p0 <= bram_s_addr_w[j];
            Raddr_r_p0 <= bram_s_addr_r[j];

            Iaddr_w_p0 <= bram_s_addr_w[j];
            Iaddr_r_p0 <= bram_s_addr_r[j];

            Haddr_p0   <= bram_H_addr[j];

            Rwen_p0    <= bram_sR_wen[j];
            Iwen_p0    <= bram_sI_wen[j];
            Hwen_p0    <= bram_H_wen[j];


            // ------------------------------------------------------------
            // Final RAM-input stage
            // These registers directly drive RAM ports.
            // ------------------------------------------------------------

            Rdata_w <= Rdata_w_p0;
            Idata_w <= Idata_w_p0;
            Hdata_w <= Hdata_w_p0;

            Raddr_w <= Raddr_w_p0;
            Raddr_r <= Raddr_r_p0;

            Iaddr_w <= Iaddr_w_p0;
            Iaddr_r <= Iaddr_r_p0;

            Haddr   <= Haddr_p0;

            Rwen    <= Rwen_p0;
            Iwen    <= Iwen_p0;
            Hwen    <= Hwen_p0;


            // ------------------------------------------------------------
            // RAM output register stage
            // ------------------------------------------------------------

            Rdata_r <= mRdata_r;
            Idata_r <= mIdata_r;
            Hdata_r <= mHdata_r;
        end


        // ================================================================
        // Connect registered RAM outputs back to qaoa_system2
        // ================================================================

        assign bram_sR_data_r[j] = Rdata_r;
        assign bram_sI_data_r[j] = Idata_r;
        assign bram_H_data_r[j]  = Hdata_r;


        // ================================================================
        // RAM instances
        // Each RAM now has its own duplicated address path.
        // ================================================================

        ram RAMR (
            .address_a(Raddr_r),
            .address_b(Raddr_w),
            .clock(CLK),
            .data_b(Rdata_w),
            .wren_b(Rwen),
            .q_a(mRdata_r)
        );

        ram RAMI (
            .address_a(Iaddr_r),
            .address_b(Iaddr_w),
            .clock(CLK),
            .data_b(Idata_w),
            .wren_b(Iwen),
            .q_a(mIdata_r)
        );

        ramH RAMH (
            .address(Haddr),
            .clock(CLK),
            .data(Hdata_w),
            .wren(Hwen),
            .q(mHdata_r)
        );

    end
endgenerate

reg [P-1:0] ddata_w, ddata_wp0, ddata_r;
reg [NG-1:0] daddr, daddrp0;
wire [P-1:0] mdata_r;
reg wen, wenp0;
always @(posedge CLK) begin
   ddata_wp0 <= bram_G_data_w;
   ddata_w <= ddata_wp0;
   daddrp0 <= bram_G_addr;
   daddr <= daddrp0;
   ddata_r <= mdata_r;
   wenp0 <= bram_G_wen;
   wen <= wenp0;
end
assign bram_G_data_r = ddata_r;

ram1G RAMG(
   .clock(CLK),
   .data(ddata_w),
   .address(daddr),
   .wren(wen),
   .q(mdata_r)
);

endmodule
