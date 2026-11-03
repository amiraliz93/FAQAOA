//============================================================================
// Documentation
//============================================================================
// Author: Amir Alizadeh (NTU), Hiroki Shibata (Tokyo Metropolitan University)
// Date: November 2025

// Description:
//   State machine controller Mixer_operation simulation. Handles:
//  Implement mixer operation of QAOA 
// BRAM nterface for quantum state storage (real.imaginary parts) 
// status reporting to control systm (ntu_smachine)

// Key Features:
//   - Supports up to 2^13 = 8192 state vector elements
//   - 6 independent BRAM banks for parallel access
//   - Pipelined mixer and cost operations
//   - Command-driven state machine (qa_WAIT, qa_RUN, qa_MIXER, qa_COST)

// Interface Protocol:
//   1. PC sends OP_SEND_CMD with qa_INIT → Initialize system
//   2. PC sends OP_SEND_CMD with qa_RUN → Start QAOA layer
//   3. System executes: qa_RUN → qa_MIXER → qa_COST → qa_WAIT
//   4. Repeat for nPLayer iterations

// BRAM Organization:
//   BRAM[0]: State vector real part (A_r)
//   BRAM[1]: State vector imaginary part (A_i)
//   BRAM[2]: Cost function coefficients
//   BRAM[5]: Parameters (cos(β), sin(β), γ)
//   BRAM[3-4]: Reserved for future use
//===========================================================================

module qaoa_system2#(
    //------------------------------------------------------------------------
    // CONFIGURABLE PARAMETERS
    //------------------------------------------------------------------------
    parameter NG = 10,
    parameter NM = 21,   // BRAM address width (2^13 = 8192 elements)
    parameter P = 64,    // Data width (64bit FP)
    parameter NBRAM=4,   // number of Bram banks
    parameter L_BRAM_R = 3
	 )  
  (
    //------------------------------------------------------------------------
    // CLOCK AND RESET
    //------------------------------------------------------------------------
    input  CLK,     // system clock
    input  RST,     // Active-high reset
    //------------------------------------------------------------------------
    // COMMAND INTERFACE (among Control Interface and addr_gen)
    //------------------------------------------------------------------------
    input [23:0]  r_CMD, // 
    output f_run_Computation_out, 
    input f_L1Computation_in, 
    input [1:0] mixSwitch_in, 
    input enPipe_in,
    input enCostF_in,
    input [23:0] en_Inits_in,
    //------------------------------------------------------------------------
    // MEMORY INTERFACE from Control Interface
    //------------------------------------------------------------------------
    // read Interface
    input [P-1:0] n_ci_addr_in,         // Read address
    input n_r_req,                 // Read request
    output reg [P-1:0] r_data,      // Read data output
    output reg r_vd,               // Read data valid
    
    // Write Interface
    input [P-1:0] n_w_data,   // Write data
    input n_w_req,           // Write request
    output reg [15:0] Status,      // Read data valid
    //------------------------------------------------------------------------
    // MIXER OPERATION INTERFACE
    //------------------------------------------------------------------------
    // Input to Mixer
    output reg [P-1:0] cosb,        // cos(β) parameter, for all pipelines
    output reg [P-1:0] sinb,        // sin(β) parameter, for all pipelines
    output reg [P-1:0] mix_ar,        // State real part input
    output reg [P-1:0] mix_ai,        // State imaginary part input
    output reg [NM:0] mix_info,     // Control info (address, enable, etc.)
    output reg [1:0] mix_switch,     // Control info (address, enable, etc.)
    

    // Output from Mixer
    input [P-1:0] mix_ar_res,
    input [P-1:0] mix_ai_res,
    input [NM:0] mix_info_res,

    //------------------------------------------------------------------------
    // COST HAMILTONIAN INTERFACE
    //------------------------------------------------------------------------
    output reg [P-1:0] gamma, // cos gamma - γ parameter
    output reg [P-1:0] HGC,    // Cost Hamiltonian coefficient

    input [P-1:0] Hr_res,
    input [P-1:0] Hi_res,
    
    //------------------------------------------------------------------------
    // Address INTERFACE (FOR MIXER, and COST FUNCTION GEN)
    //------------------------------------------------------------------------
    input wire  [NM-1:0] swapped_cAddr_in,
    input wire  [NM-1:0] cAddrCF_in,
    //------------------------------------------------------------------------
    //BRAM ARRAY INTERFACE (3 banks + 1 general bank)
    //------------------------------------------------------------------------
    output reg [NBRAM-1:0] bram_sR_wen,
    output reg [NBRAM-1:0] bram_sI_wen,
    output reg [NBRAM-1:0] bram_H_wen,
    output reg bram_G_wen,
    input [P-1:0] bram_sR_data_r [NBRAM],
    input [P-1:0] bram_sI_data_r [NBRAM],
    input [P-1:0] bram_H_data_r [NBRAM],
    input [P-1:0] bram_G_data_r,
    output reg [P-1:0] bram_sR_data_w [NBRAM],
    output reg [P-1:0] bram_sI_data_w [NBRAM],
    output reg [P-1:0] bram_H_data_w [NBRAM],
    output reg [P-1:0] bram_G_data_w,
    output reg [NM-1:0] bram_s_addr_r [NBRAM],
    output reg [NM-1:0] bram_s_addr_w [NBRAM],
    output reg [NM-1:0] bram_H_addr [NBRAM],
    output reg [NG-1:0] bram_G_addr
);
//============================================================================
// LOCALPARAMS - Internal Constants
//============================================================================
//----------------------------------------------------------------------------
// QAOA State Machine States
//----------------------------------------------------------------------------
localparam qa_WAIT  = 8'h1;   // Waiting for command from ntu_smachine
localparam qa_RUN   = 8'h2;   // Running QAOA layer initialization
localparam qa_RUNB1 = 8'h4;   // Executing mixer operation
localparam qa_RUNC  = 8'h8;   // Executing mixer operation

localparam W_REQ_BASE = NM + 8;
localparam LATENCY_BRAM = L_BRAM_R + 1; // need to add 1, for output register inside this block
//============================================================================
// INTERNAL REGISTERS & SIGNALS
//============================================================================
reg [15:0] StatusL;      // Read data valid

//----------------------------------------------------------------------------
// Main State Machine
//----------------------------------------------------------------------------
reg [7:0] cmd;                // Current command state
reg [7:0] cmd0;                // Current command state
reg [7:0] cmd1;                // Current command state
reg [7:0] cmdL;                // Current command state
logic [7:0] n_cmd;            // Next command state
 
reg f_run_Computation;
logic n_f_run_Computation;
assign f_run_Computation_out = f_run_Computation;
//----------------------------------------------------------------------------
// BRAM Access Registers (from ntu_smachine)
//----------------------------------------------------------------------------
reg [P-1:0] ci_addr;           // Buffered read address
reg r_req;                    // Buffered read request
reg [P-1:0] w_data;           // Buffered write data
reg w_req;                    // Buffered write request

logic [P-1:0] n_r_data;       // Next read data
logic n_r_vd;                 // Next read valid, for control interface
//-----------------
// Parameter Storage Pointer
//----------------------------------------------------------------------------
reg [31:0] P5pointer;         // Pointer into BRAM[3] for parameter reads
logic [31:0] n_P5pointer;     // Next pointer value

//----------------------------------------------------------------------------
// QAOA Parameters (cos(β), sin(β), γ)
//----------------------------------------------------------------------------
logic [P-1:0] nb_cosb;         // Next cos(β), buffer to align the timining 
logic [P-1:0] nb_sinb;         // Next sin(β), buffer to align the timining 
logic [P-1:0] n_cosb;         // Next cos(β), buffer to align the timining 
logic [P-1:0] n_sinb;         // Next sin(β), buffer to align the timining 
reg [P-1:0] b_cosb;         // Next cos(β), buffer to align the timining 
reg [P-1:0] b_sinb;         // Next sin(β), buffer to align the timining 
logic [P-1:0] n_gamma;        // Next γ
logic [P-1:0] nb_gamma;        // Next γ
reg [P-1:0] b_gamma; // cos gamma - γ parameter
logic [41: 0] n_CompCounter;
reg [41: 0] CompCounter;
//----------------------------------------------------------------------------
// Mixer Operation Registers
//----------------------------------------------------------------------------
logic [P-1:0] n_mix_ar;         // Next mixer real input
logic [P-1:0] n_mix_ai;         // Next mixer imaginary input
logic [NM:0] n_mix_info;      // Next mixer control info
logic [1:0]  n_mix_switch;
//----------------------------------------------------------------------------
// Cost function Operation Registers
//----------------------------------------------------------------------------

logic [P-1:0] n_HGC;            // next Cost Hamiltonian coefficient

//----------------------------------------------------------------------------
// BRAM Request Pipeline (3-stage delay)
//----------------------------------------------------------------------------
reg [W_REQ_BASE + 3*P+4-1:0] bram_reqP[LATENCY_BRAM];     // 2-stage pipeline
logic [W_REQ_BASE-1:0] n_bram_reqQ;   // Next request (input to pipeline)

logic [P-1:0] n_bram_gammaQ;
logic [P-1:0] n_bram_cosbQ;
logic [P-1:0] n_bram_sinbQ;
logic [3:0] n_bram_infoAQ;

wire [P-1:0] bram_gammaO;
wire [P-1:0] bram_cosbO;
wire [P-1:0] bram_sinbO;
wire [3:0] bram_infoAO;
wire [W_REQ_BASE-1:0] bram_reqR;   
assign {bram_infoAO, bram_sinbO, bram_cosbO, bram_gammaO, bram_reqR} = bram_reqP[LATENCY_BRAM-1];
//----------------------------------------------------------------------------
// BRAM Control Signals (Next Values)
//----------------------------------------------------------------------------
logic [NM-1:0] n_bram_s_addr_r [NBRAM];  // Next read addresses
logic [NM-1:0] n_bram_s_addr_w [NBRAM];  // Next write addresses
logic [NM-1:0] n_bram_H_addr [NBRAM];  // Next write addresses
logic [NG-1:0] n_bram_G_addr;  // Next write addresses
logic [P-1:0]  n_bram_sR_data_w [NBRAM];  // Next write data
logic [P-1:0]  n_bram_sI_data_w [NBRAM];  // Next write data
logic [P-1:0]  n_bram_H_data_w [NBRAM];  // Next write data
logic [P-1:0]  n_bram_G_data_w;  // Next write data
logic [NBRAM-1:0] n_bram_sR_wen;          // Next write enables
logic [NBRAM-1:0] n_bram_sI_wen;          // Next write enables
logic [NBRAM-1:0] n_bram_H_wen;          // Next write enables
logic n_bram_G_wen;          // Next write enables

//----------------------------------------------------------------------------
// Test/Debug Register
//----------------------------------------------------------------------------
reg [P-1:0] testReg;          // Test register for debug reads/writes
logic [P-1:0] n_testReg;      // Next test register value

always_comb begin: memorySwitchingBlock

    //------------------------------------------------------------------------
    // This block defines Memory interconnect. 
    // All memory addressing querying part must be in this block
    // A block only taking the read result can be in another block.  
    // DEFAULT ASSIGNMENTS - Prevent Latches
    //------------------------------------------------------------------------
    n_r_vd = 0;                         // No read valid by default
    n_testReg = testReg;                // Keep test register
    n_r_data = 'd0;                       // Clear read data
    n_bram_sR_wen = 'd0;                     // No BRAM writes by default
    n_bram_sI_wen = 'd0;                     // No BRAM writes by default
    n_bram_H_wen = 'd0;                     // No BRAM writes by default
    n_bram_G_wen = 'd0;                     // No BRAM writes by default

    n_bram_s_addr_w = bram_s_addr_w;        // Keep write addresses
    n_bram_s_addr_r = bram_s_addr_r;        // Keep read addresses
    n_bram_H_addr = bram_H_addr;        // Keep write addresses
    n_bram_G_addr = bram_G_addr;        // Keep write addresses
    n_bram_sR_data_w = bram_sR_data_w;        // Keep write data
    n_bram_sI_data_w = bram_sI_data_w;        // Keep write data
    n_bram_H_data_w = bram_H_data_w;        // Keep write data
    n_bram_G_data_w = bram_G_data_w;        // Keep write data
    n_bram_reqQ = '0;                  // No new BRAM request
    n_cmd = cmd0;                        // Keep current command

    n_mix_info = 'd0;                       // Clear mixer info
    n_mix_ar = 'd0;                         // Clear mixer real input
    n_mix_ai = 'd0;                         // Clear mixer imag input
    n_mix_switch = '0;
    n_HGC = 'd0;

    n_f_run_Computation = f_run_Computation;
    n_bram_gammaQ = b_gamma;
    n_bram_cosbQ =  b_cosb;
    n_bram_sinbQ = b_sinb;
    n_bram_infoAQ = '0;

    n_sinb = bram_sinbO;
    n_cosb = bram_cosbO;
    n_gamma = bram_gammaO;
    nb_gamma = b_gamma;  // Keep γ
    nb_cosb = b_cosb;
    nb_sinb = b_sinb;

    n_CompCounter = CompCounter;
    n_P5pointer = P5pointer;
    // read cosb, sinb, gamma, at the beginning of the first 
    // request cos(beta)
    if(en_Inits_in[0] || en_Inits_in[1] || en_Inits_in[2]) begin 
        n_P5pointer = P5pointer + 1;
    end

    if(en_Inits_in[LATENCY_BRAM]) begin
        nb_cosb = bram_G_data_r; // store to temporal buffer of cosb, later written to cosb itself.
    end
    if(en_Inits_in[LATENCY_BRAM+1]) begin
        // write to sinb
        nb_sinb = bram_G_data_r; // store to temporal buffer
    end
    if(en_Inits_in[LATENCY_BRAM+2]) begin 
        nb_gamma = bram_G_data_r;
    end
    //------------------------------------------------------------------------
    // MAIN STATE MACHINE
    //------------------------------------------------------------------------
    case(cmd)

    // qa_WAIT: Idle state - Handle read/write requests from ntu_smachine
    //========================================================================
    qa_WAIT: begin // accept operation from ntu_smachine.

        // READ OPERATIONS (based on r_addr[63:56])
        case(ci_addr[P-1:P-8])
        1: begin //read the state
            n_r_data[7:0] = cmd;
            n_r_data[P-1:8] = '0;
            n_r_vd = r_req;
        end
        2: begin
            n_r_data[41:0] = CompCounter;
            n_r_data[P-1:42] = '0;
            n_r_vd = r_req;
        end
        4: begin // Hamiltonian
            n_bram_H_addr[0] = ci_addr[NM-1:0];
            n_bram_reqQ[NM] = r_req;
            n_r_vd = bram_reqR[NM];
            n_r_data = bram_H_data_r[0];
        end
        8: begin  // read sin(b), cos(b), gamma, I think we will use this function just for debugging.
            n_bram_G_addr =  ci_addr[NM-1:0];
            n_bram_reqQ[NM+1] = r_req;
            n_r_vd = bram_reqR[NM+1];
            n_r_data = bram_G_data_r;
        end
        16: begin // read real part of the state vector
            n_bram_s_addr_r[0] =  ci_addr[NM-1:0]; 
            n_bram_reqQ[NM+2] = r_req;
            n_r_vd = bram_reqR[NM+2];
            n_r_data = bram_sR_data_r[0];
        end 
        32: begin // read imag part of the state vector
            n_bram_s_addr_r[0] =  ci_addr[NM-1:0];
            n_bram_reqQ[NM+3] = r_req;
            n_r_vd = bram_reqR[NM+3];
            n_r_data = bram_sI_data_r[0];
        end 
        default: begin 
            n_r_vd = r_req;
            n_r_data = testReg; // send counter.
        end
        endcase

        // WRITE OPERATIONS (based on ci_addr[63:56])
        //--------------------------------------------------------------------
        
        if(w_req) begin
            case(ci_addr[P-1:P-8])
            1: begin //write register
                n_testReg = w_data;
            end
            2: begin 
                n_testReg = testReg + 1;
            end
            4: begin // write to hamiltonian
                n_bram_H_addr[0] = ci_addr[NM-1:0];
                n_bram_H_data_w[0] = w_data;
                n_bram_H_wen[0] = 1;
            end
            8: begin // write to sin(b) cos(b), gamma, 
                n_bram_G_addr = ci_addr[NM-1:0];
                n_bram_G_data_w = w_data;
                n_bram_G_wen = 1;
            end
            16: begin // write to real part of state vector
                n_bram_s_addr_w[0] = ci_addr[NM-1:0];
                n_bram_sR_data_w[0] = w_data;
                n_bram_sR_wen[0] = 1;
            end 
            32: begin // write to imaginary part of state vector
                n_bram_s_addr_w[0] = ci_addr[NM-1:0];
                n_bram_sI_data_w[0] = w_data;
                n_bram_sI_wen[0] = 1;
            end 
            default: begin 
                n_testReg = w_data;
            end
            endcase
        end
    end
    // initialize. Start at the next clock.
    qa_RUN: begin
        n_f_run_Computation = 1;
        n_cmd = qa_RUNC;
        n_P5pointer = 0;
        n_CompCounter = 0;
    end
    // qa_RUN: Apply cost Hamiltonian and check layer completion
    //========================================================================
    qa_RUNC: begin
         // --------------------------------------------
        // Memory access part.
        // Index generator to BRAM. Index generator input is defined in n_bs_info_in.
        // --------------------------------------------
        n_bram_H_addr[0] = cAddrCF_in; // addressing for cost function generation
        n_bram_s_addr_r[0] = swapped_cAddr_in;
        n_bram_reqQ[NM-1:0] = swapped_cAddr_in; // pass address, for storation after mixer.
        n_bram_G_addr = P5pointer[NG-1:0];
        n_CompCounter = CompCounter + 1;
        // --------------------------------------------
        // BRAM data to each arithmetric block
        // --------------------------------------------
        n_HGC = bram_H_data_r[0]; // supply hamiltonian to generator.
        n_mix_switch = bram_infoAO[2:1];
        n_mix_ar = bram_sR_data_r[0]; 
        n_mix_ai = bram_sI_data_r[0];
        n_mix_info[NM-1:0] = bram_reqR[NM-1:0];
        n_mix_info[NM] = bram_infoAO[0]; // contains write enable.

        // --------------------------------------------
        // Write back output of arithmetric block to BRAM
        // Output from cost function gen is directly supplied to mixer block, see n_bs_info_in part in always_comb computingBlock.
        // --------------------------------------------
        n_bram_s_addr_w[0] = mix_info_res[NM-1:0];
        n_bram_sR_data_w[0] = mix_ar_res;
        n_bram_sI_data_w[0] = mix_ai_res;
        n_bram_sR_wen[0] = mix_info_res[NM];
        n_bram_sI_wen[0] = mix_info_res[NM];
        // !! remove bswap chain from pipeline. No need to include addressing latency. ok 20260429
        // !! any number of pipeline for addressing is possible!.
        // !! include enCostF in bs information chain.
        if(enCostF_in) begin  
            n_bram_cosbQ = Hr_res; // provided to mixer, pipe line of n_bram_reqQcosb consists of  bit swap  and memory access latency.
            n_bram_sinbQ = Hi_res; // provided to mixer
            n_bram_gammaQ = gamma; // keep the old value
        end 

        n_bram_infoAQ[0] = enPipe_in; // enable write back the result
        n_bram_infoAQ[1] = mixSwitch_in[0]; // 0 for cost
        n_bram_infoAQ[2] = mixSwitch_in[1]; // 0 for cost

        if(f_L1Computation_in) begin 
            n_cmd = qa_WAIT;
            n_f_run_Computation = 0;
        end
    end
	 default: begin
	 end
    endcase
    
end

//============================================================================
// SEQUENTIAL LOGIC - Register Updates
//============================================================================
integer i;
always@(posedge CLK) begin

    //------------------------------------------------------------------------
    // RESET: Initialize all registers
    //------------------------------------------------------------------------
    
    if(RST)begin
        // BRAM interface
        r_data <= '0;
        r_req <= '0;
        ci_addr <= '0;
        w_data <= '0;
        w_req <= '0;
        r_vd <= '0;

        // State machine
        cmd0 <= qa_WAIT;
        // Counters
        P5pointer <= '0;
            
        b_cosb <= '0;
        b_sinb <= '0;
        b_gamma <= '0;
        // QAOA parameters (default values for testing)
        // Debug
        testReg <= 'd175;
        // Configuration
        mix_switch <= 'd0;
        bram_G_wen <= 'd0;
        bram_H_wen <= 'd0;
        bram_sR_wen <= 'd0;
        bram_sI_wen <= 'd0;

        f_run_Computation <= 'd0;
        // initialize with invalid values.

    end

    // NORMAL OPERATION: Update registers
    //------------------------------------------------------------------------
    else begin
        //--------------------------------------------------------------------
        // Command Override (from ntu_smachine via r_CMD)
        //--------------------------------------------------------------------
        if(r_CMD[23]) begin
            cmd0 <= r_CMD[7:0]; // FIXED: Non-blocking assignment
        end
        else begin
            cmd0 <= n_cmd;
        end
        //--------------------------------------------------------------------
        // Update All Registers
        //--------------------------------------------------------------------
        P5pointer <= n_P5pointer;


        // BRAM read interface
        r_data <= n_r_data;
        r_req <= n_r_req;
        r_vd <= n_r_vd;

        // BRAM write interface
        ci_addr <= n_ci_addr_in;
        w_data <= n_w_data;
        w_req <= n_w_req;

        b_cosb <= nb_cosb;
        b_sinb <= nb_sinb;
        b_gamma <= nb_gamma;
        // en_CostF = 1, after finish cost generation. Do not use global timing, because
        // need to be disscussed more in detail.
        f_run_Computation <= n_f_run_Computation;
        testReg <= n_testReg;
        
    end
    
    cosb <= n_cosb;
    sinb <= n_sinb;
    gamma <= n_gamma; 
    
    // QAOA parameters
    // Mixer interface
    mix_ar <= n_mix_ar;
    mix_ai <= n_mix_ai;
    mix_info <= n_mix_info;
    mix_switch <= n_mix_switch;
    HGC <= n_HGC;

    // BRAM control
    bram_sR_wen <= n_bram_sR_wen;
    bram_sI_wen <= n_bram_sI_wen;
    bram_H_wen <= n_bram_H_wen;
    bram_G_wen <= n_bram_G_wen;
    bram_s_addr_w <= n_bram_s_addr_w;
    bram_s_addr_r <= n_bram_s_addr_r;
    bram_H_addr <= n_bram_H_addr;
    bram_G_addr <= n_bram_G_addr;
    bram_sR_data_w <= n_bram_sR_data_w;
    bram_sI_data_w <= n_bram_sI_data_w;
    bram_H_data_w <= n_bram_H_data_w;
    bram_G_data_w <= n_bram_G_data_w;
    
    // Debug
    StatusL[7:0] <= n_cmd[7:0];
    StatusL[8] <= f_run_Computation;
    StatusL[15:9] <= 7'(P5pointer);
    Status <= StatusL;
    CompCounter <= n_CompCounter;

    cmd1 <= cmd0;
    cmdL <= cmd1;
    cmd <= cmdL;
    // BRAM request pipeline (3-stage delay for timing)
    
    bram_reqP[0] <= {n_bram_infoAQ, n_bram_sinbQ, n_bram_cosbQ, n_bram_gammaQ, n_bram_reqQ};
    for(i=0;i<LATENCY_BRAM-1;i=i+1) begin 
        bram_reqP[i+1] <= bram_reqP[i];
    end 
end

endmodule