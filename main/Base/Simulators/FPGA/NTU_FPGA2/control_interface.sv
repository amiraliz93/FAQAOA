//============================================================================
// Documentation
//============================================================================
// Author: Amir Alizadeh (Nottingham Trent University), Hiroki Shibata (Tokyo Metropolitan University)
// Date: December 28, 2025
// Description:
//   State machine controller for FPGA-based QAOA simulation. Handles:
//   - UART communication (command/data exchange with PC)
//   - Register file management (rA, rB, rT, rU - 64-bit each)
//   - Arithmetic operations (fixed-point and FP64)
//   - BRAM interface for quantum state storage
//   - QAOA-specific operations (mixer, cost phases)

//    - interface description (port)
//    Inputs: CLK, RST, rbram_vd, r_data
//    Output: ci_addr, w_data, w_req, r_req
//===========================================================================

module control_interface#(
    //------------------------------------------------------------------------
    // CONFIGURABLE PARAMETERS
    //------------------------------------------------------------------------
      parameter MAX_QUBITS = 20,              // Maximum qubits
      parameter MAX_EDGES = 190,              // Maximum graph edges
      parameter P = 64,            // FP precision (32 or 64)
      parameter BRAM_ADDR_WIDTH = P,         // BRAM address width
      parameter BRAM_DATA_WIDTH = P,         // BRAM data width
      parameter FIXED_INT_BITS = 40,          // Fixed-point integer bits
      parameter FIXED_FRAC_BITS = 24,         // Fixed-point fractional bits
      parameter FIX64_ADD_LATENCY = 3,        // Fixed add latency
      parameter HOST_DATA_WIDTH = 8,           // DATA width between Host
	parameter NM = 32
   )
  (
    //------------------------------------------------------------------------
    // CLOCK AND RESET
    //------------------------------------------------------------------------
    input  wire CLK,
    input  wire RST,
    //------------------------------------------------------------------------
    // HOST INTERFACE
    //------------------------------------------------------------------------
    input  wire tx_OK,
    output wire tx_en,
    output wire [HOST_DATA_WIDTH-1:0] tx_data_out,
    input  wire [HOST_DATA_WIDTH-1:0] rx_data_in,
    input rx_dv,
    
    //------------------------------------------------------------------------
    // BRAM INTERFACE
    //------------------------------------------------------------------------
    output reg  [BRAM_ADDR_WIDTH-1:0] addr_out,   // Read address
    output reg  [BRAM_DATA_WIDTH-1:0] w_data,   // Write data
    input  wire [BRAM_DATA_WIDTH-1:0] r_data,   // Read data
    output wire        w_req,                   // Write request
    output reg         r_req,                   // Read request
    input  wire        rbram_vd,                // Read data valid
    
    //------------------------------------------------------------------------
    // ADDRESS FLOW CONTROLER INTERFACE
    //------------------------------------------------------------------------
    output [7:0] ag_addr_Param_out,
    output [NM-1:0] ag_Param_out,
    output ag_wen_out,
    //------------------------------------------------------------------------
    // Interface for testing, not core 
    //------------------------------------------------------------------------
    input wire [15:0] rS, // status of qaoa system.
    output reg [23:0] CMD
);

//============================================================================
//---------------------- Localparam / Parameters 
//============================================================================

//---------------------------  MAIN STATE MACHINE STATES -----------------------
//---------------------------------------------------------------------------
// 8 state so need max 3 bit width  - formula = ceil(log2(max value +1))
// 3 Width - d(base) - 0 (value)
localparam s_IDLE       = 10'h01;
localparam s_Fetch      = 10'h02;
localparam s_Operation  = 10'h04;
localparam s_WAIT_COMP  = 10'h08;
localparam s_WRITE_REG  = 10'h10;
localparam s_WRITE_BRAM = 10'h20;
localparam s_READ_BRAM  = 10'h40;
localparam s_TXData     = 10'h80;
localparam s_FetchWait  = 10'h100;
localparam s_WRITE_AG   = 10'h200;


//---------------------- Operation Code (Data Transfer) --------------------
//---------------------------------------------------------------------------
// 255 value - max width 8
localparam OP_NONE       = 8'h0;   // No operation
localparam OP_SEND1T     = 8'h1;   // Request 1 byte from PC → rT
localparam OP_SEND8T     = 8'h2;   // Request 8 bytes from PC → rT
localparam OP_MOV_T2A    = 8'h3;   // Move rT → rA
localparam OP_MOV_T2B    = 8'h4;   // Move rT → rB
localparam OP_MOV_A2U    = 8'h5;   // Move rA → rU (address register)
localparam OP_MOV_A2B    = 8'h6;   // Move rA → rB
localparam OP_MOV_Info2U = 8'h7;   // send firmware version info
localparam OP_MOV_S2U    = 8'h8;   // status value to rU.
//------------------- Data Retrieval Operations (60-70)
localparam OP_FETCH1U    = 8'd60;  // Send 1 byte from rU to PC
localparam OP_FETCH8U    = 8'd61;  // Send 8 bytes from rU to PC


//---------------  Arithmetic Operations (Fixed-Point) (80-85)
localparam OP_ADD_B2A    = 8'd80;  // rA = rA + rB (64-bit fixed, 2 cycles)
localparam OP_INC_A     = 8'd84;    // rA = rA + 1 (64-bit fixed, 1 cycles)

//-------------------- Memory Operations 
localparam OP_WRITE_T2RAM = 8'd111;  // Write rT to BRAM[rA]
localparam OP_READ_RAM2U  = 8'd112;  // Read BRAM[rA] → rU
localparam OP_SEND_CMD    = 8'd118;  // send: 0, Res: 0. see qa_INIT, qa_WAIT, qa_RUN in qaoa_system.sv
localparam OP_WRITE_T2_AG = 8'd119;  // rT -> ag_Param_out, rA -> ag_addr_Param

//---------------------  SUB-STATE DEFINITIONS (Fetch, Store) --------------
//---------------------------------------------------------------------------
//--------------------- Fetch parameters
localparam FETCH_IDLE    = 3'd0;  // Idle: not fetching
localparam FETCH_DATA    = 3'd1;  // Fetching data bytes into rT
localparam FETCH_WAIT    = 3'd2;  // Waiting for FIFO data valid
localparam FETCH_GETOP   = 3'd4;  // Getting operation code
localparam FETCH_w_BRAM  = 3'd6;  // (Reserved for BRAM streaming - not implemented)

//--------------------- Store parameters
localparam STORE_IDLE    = 3'd0;  // Idle: not transmitting
localparam STORE_LEN     = 3'd1;  // Transmitting bytes from rU
localparam STORE_BRAM    = 3'd2;  // (Reserved for BRAM streaming - not implemented)
localparam STORE_WAIT    = 3'd4;  // Waiting for TX FIFO space


//--------------------------- Write Operation parameters (Codes) --------------------
//---------------------------------------------------------------------------
localparam WRITE_NONE        = 5'd0;   // No write operation
localparam WRITE_T2A         = 5'd1;   // rA = rT
localparam WRITE_T2B         = 5'd2;   // rB = rT
localparam WRITE_A2B         = 5'd3;   // rB = rA
localparam WRITE_A2U         = 5'd4;   // rU = rA
localparam WRITE_B2A         = 5'd5;   // rA = rB
localparam WRITE_mulFP64_rA  = 5'd6;   // rA = res_mulFP64 (FP multiply result)
localparam WRITE_addFP64_rA  = 5'd7;   // rA = res_addFP64 (FP add result)
localparam WRITE_add_rA      = 5'd9;   // rA = res_addAB (fixed add result)
localparam WRITE_rA1         = 5'd10;  // rA = rA + 1
localparam WRITE_rB1         = 5'd11;  // rB = rB + 1
localparam WRITE_BRAM_U      = 5'd12;  // rU = r_data (BRAM read result)
localparam WRITE_Info2U      = 5'd13;  // rU = firmware version string 
localparam WRITE_S2U         = 5'd14;
//======================================================================================

//============================================================================
//---------------------- INTERNAL REGISTERS & SIGNALS
//============================================================================
// 2.1 Inputs (Clock, Reset, External signals)
// 2.2 Outputs (UART, Control signals)
// 2.3 Bidirectional (if any)

//------------ Main State Mchine Registers
reg [10:0] state;              // Current main state
logic [10:0] n_state;          // Next state

reg [7:0] ope_state;          // Current operation code
logic [7:0] n_ope_state;      // Next operation code

//--------------- Fetch Sub-State Machine
reg [2:0] fetchState;           //current fetch state
logic [2:0] n_fetchState;        // Next fetch state

reg [3:0] rPos;         //Current byte position in rT(0-7)
logic [3:0] n_rPos;      // next byte position

reg [3:0] fetchMaxPos;   //Max bytes to fetch (0=1 byte, 7=8 bytes)
logic [3:0] n_fetchMaxPos;    // Next max position

reg [10:0] rBRPos; // position to store the byte 
logic [10:0] n_rBRPos; // position to store the byte  // Next BRAM transmit position


//--------------------- Store/TX Sub-state Mchine
reg [2:0] storeState;           //Current strore state
logic [2:0] n_storeState;      // Next store state

reg [3:0] txPos;         // current tx byte position (0-7)
logic [3:0] n_txPos;     // Next TX position

reg [3:0] txMaxPos;
logic [3:0] n_txMaxPos;  // Next max tx position


//------------------- Write Backend Control 
reg [4:0] writeReg;           //current write operation
reg [4:0] bwriteReg;          // buffered write (for arthemetic operation)
logic [4:0] n_writeReg;       // Next write operation
logic [4:0] n_bwriteReg;      // Next buffered write

// ------------- Data Path Registers (64bit)
reg [P-1:0] rA;                // Register A (general purpose)
reg [P-1:0] rB;                // Register B
reg [P-1:0] rT;                // Temporary Register (RX data)
reg [P-1:0] rU;                // Address register (TX data)

logic [P-1:0] n_rA, n_rB, n_rT, n_rU;      //Next values

logic [23:0] n_CMD;

//------------------------ Arithmetic Unit Inputs/Outputs

// Fixed-point units
// These perform integer/fixed-point operations with shorter latency
reg [P-1:0] addA, addB;        // Adder inputs
reg [P-1:0] res_addAB;         // Add result

//------------------  Wait Counter (for arithmetic latency)
reg [7:0] c_wait;             // Current wait cycles
reg [7:0] opa_c_wait;         // Target wait cycles
logic [7:0] n_c_wait;         // Next wait count
logic [7:0] n_opa_c_wait;     // Next target


//============================================================================
//---------------------- FIFO Interface Signals & Registers
//===========================================================================

//------------------------  RX FIFO (incoming data from UART)
wire [7:0] rf_data;           // Data from RX FIFO
wire rf_empty;                // RX FIFO empty flag
wire rf_full;                 // RX FIFO full flag
logic rf_req;                 // Read request
reg [1:0] rf_dv;              // Data valid (delayed)

//---------------------   TX FIFO (outgoing data to UART)
logic [7:0] tf_data;          // Data to TX FIFO
wire tf_empty;                // TX FIFO empty flag
wire tf_full;                 // TX FIFO full flag
logic tf_write;               // Write enable
reg [1:0] tx_dv;              // TX data valid

// -----------------------  BRAM Interface Signals
logic  [P-1:0] n_w_data;       // Next read address
logic  [P-1:0] n_ci_addr;       // Next write data
logic n_r_req;                // next write request
logic n_w_req;                // next read request

assign w_req = n_w_req;
assign tx_en = tx_dv[1];
reg [7:0] ag_addr_Param; logic [7:0] n_ag_addr_Param;
reg [NM-1:0] ag_Param; logic [NM-1:0] n_ag_Param;
reg ag_wen; logic n_ag_wen;

assign ag_addr_Param_out = ag_addr_Param;
assign ag_Param_out = ag_Param;
assign ag_wen_out = ag_wen;

//---------------------- Helper Wires
wire [P-1:0] rAinc = rA + 1;
wire [P-1:0] rBinc = rB + 1;
reg RSTlv1A;          // buffer register of reset signal.

//---------- Conditional states (wait if FIFO full/empty)
wire [3:0] wstoreState = tf_full? STORE_WAIT: storeState;
wire [3:0] wfetchState = rf_dv[0]? fetchState: FETCH_WAIT;
//============================================================================


//============================================================================
// MAIN STATE MACHINE - COMBINATIONAL LOGIC
//============================================================================
// This block determines next state and outputs based on current state

always_comb begin: main_StateBlock
//------------------------------------------------------------------------
      // DEFAULT VALUES - Prevent latches by assigning all signals
      //------------------------------------------------------------------------
      n_state = state;                    // Stay in current state by default
      n_opa_c_wait = opa_c_wait;          // Keep wait counter target
      n_fetchState = fetchState;          // Keep fetch state
      n_storeState = storeState;          // Keep store state
      n_c_wait = c_wait;                  // Keep current wait count
      n_fetchMaxPos = fetchMaxPos;        // Keep fetch byte limit
      n_writeReg = writeReg;              // Keep write operation
      n_bwriteReg = bwriteReg;            // Keep buffered write op
      n_txMaxPos = txMaxPos;              // Keep TX byte limit
      n_w_req = '0;                       // Default: no BRAM write request
      n_ci_addr = rA;                      // BRAM write address = rA
      n_w_data = rT;                      // BRAM write data = rT
      n_CMD = 'd0;    
      n_rA = rA;                          // Keep register A value
      n_rB = rB;                          // Keep register B value
      n_rT = rT;                          // Keep temporary register
      n_rU = rU;                          // Keep address register
      n_txPos = '0;                        // Reset TX position
      tf_data = '0;                        // No TX FIFO write by default
      tf_write = '0;                       // TX FIFO write disabled
      n_rPos = rPos;                      // Keep receive position
      n_rBRPos = rBRPos;                  // Keep BRAM receive position
      
      n_ag_Param = rT[NM-1:0];                    // BRAM write data = rT
      n_ag_addr_Param = rA[7:0];               // BRAM write data = rT
      n_ag_wen = '0;
      
      // RX FIFO read request: read if (1) FIFO not empty AND (2) not in IDLE
      rf_req = (!rf_empty) & (fetchState != FETCH_IDLE);
      
      n_ope_state = ope_state;            // Keep operation code
      n_r_req = 0;                        // Default: no BRAM read request
      
      //------------------------------------------------------------------------
      // MAIN STATE MACHINE LOGIC
      //------------------------------------------------------------------------
      case(state)
      //------------------------------------------------------------------------
      // s_Fetch: Receive opcode and optional data from UART/FIFO
      //------------------------------------------------------------------------
      s_Fetch: begin
            case(wfetchState)// Check fetch sub-state (with FIFO check)

            // FETCH_DATA: Receiving data bytes into rT register
            FETCH_DATA: begin
                  // Extract byte from FIFO and place in rT at current position
                  n_rT[rPos*8+:8] = rf_data; // [rPos*8+:8] = 8 bits starting at rPos*8
                  n_rPos = rPos + 1'b1;         // Move to next byte position

                  // If all bytes received, get next opcode
                  if(rPos == fetchMaxPos) begin
                        n_fetchState = FETCH_GETOP;
                  end
            end
            // FETCH_WAIT: Waiting for FIFO to have data
            FETCH_WAIT: begin
                  n_rPos = rPos;     // Hold position
                  n_rBRPos = rBRPos; // Hold BRAM position
            end
            // FETCH_GETOP: Getting operation code from FIFO

            FETCH_GETOP:begin
                  n_ope_state = rf_data;  // Store opcode
                  n_state = s_Operation;  // Move to operation state
                  n_rPos = '0;             // Reset byte position
            end
            // Default case
            default: begin
                  n_rPos = '0;             // Reset positions
                  n_rBRPos = '0;
            end
            endcase
      end
      //------------------------------------------------------------------------
      // s_Operation: Decode opcode and dispatch to appropriate action
      //------------------------------------------------------------------------
      s_Operation: begin
            // writing backend of register
            case (ope_state)
            
            //--------------------------------------------------------------------
            // DATA TRANSFER OPERATIONS
            //--------------------------------------------------------------------
            
            // OP_SEND1T: Request 1 byte from PC
            OP_SEND1T: begin
                  n_state = s_Fetch;          // Return to fetch state
                  n_fetchState = FETCH_DATA;    // Set to receive data
                  n_fetchMaxPos = 0;          // Receive 1 byte (position 0)
            end
            // OP_SEND8T: Request 8 bytes from PC
            OP_SEND8T: begin
                  n_state = s_Fetch;          // Return to fetch state
                  n_fetchMaxPos = 7;          // Receive 8 bytes (positions 0-7)
                  n_fetchState = FETCH_DATA;    // Set to receive data
            end
            
            // OP_MOV_T2A: Move temporary register to register A
            OP_MOV_T2A: begin
                  n_state = s_WRITE_REG;      // Go to write state
                  n_writeReg = WRITE_T2A;     // Set write operation
            end
            OP_MOV_T2B: begin
                  n_state = s_WRITE_REG;      // Go to write state
                  n_writeReg = WRITE_T2B;     // Set write operation
            end
            // OP_MOV_A2U: Move register A to address register U
            OP_MOV_A2U: begin
                  n_state = s_WRITE_REG;
                  n_writeReg = WRITE_A2U;
            end
            // OP_MOV_A2B: Move register A to register B
            OP_MOV_A2B: begin
                  n_state = s_WRITE_REG;
                  n_writeReg = WRITE_A2B;
            end
            OP_MOV_S2U: begin
                  n_state = s_WRITE_REG;
                  n_writeReg = WRITE_S2U;
            end
		OP_MOV_Info2U: begin
                  n_state = s_WRITE_REG;
                  n_writeReg = WRITE_Info2U;
            end
            OP_SEND_CMD: begin 
                  n_CMD[23] = 1;
                  n_CMD[7:0] = rT[7:0];
                  n_state = s_IDLE;
            end
            
            //--------------------------------------------------------------------
            // ARITHMETIC OPERATIONS (with wait cycles)
            //--------------------------------------------------------------------
            // OP_INC_A: Increment register A
            OP_INC_A: begin
                  n_opa_c_wait = 'd1;           // Wait 1 cycle
                  n_state = s_WAIT_COMP;      // Go to wait state
                  n_bwriteReg = WRITE_rA1;    // Buffer write operation
            end
            // OP_ADD_B2A: Fixed-point addition (rA = rA + rB)
            OP_ADD_B2A: begin
                  n_opa_c_wait = 'd2;           // Wait 2 cycles (addfix8 latency)
                  n_state = s_WAIT_COMP;
                  n_bwriteReg = WRITE_add_rA;
            end
            //--------------------------------------------------------------------
            // DATA RETRIEVAL OPERATIONS
            //--------------------------------------------------------------------
            
            // OP_FETCH1U: Send 1 byte from rU to PC
            OP_FETCH1U: begin
                  n_storeState = STORE_LEN;     // Set to transmit mode
                  n_txMaxPos = 'd0;             // Send 1 byte
                  n_state = s_TXData;         // Go to transmit state
            end

            // OP_FETCH8U: Send 8 bytes from rU to PC
            OP_FETCH8U: begin
                  n_storeState = STORE_LEN;
                  n_txMaxPos = 'd7;             // Send 8 bytes (positions 0-7)
                  n_state = s_TXData;
            end
            
            //--------------------------------------------------------------------
            // MEMORY OPERATIONS
            
            OP_WRITE_T2RAM: begin
                  n_w_req = 1;                // Assert write request
                  n_state = s_WRITE_BRAM;     // Go to BRAM write state
            end
            OP_WRITE_T2_AG: begin   // rT -> ag_Param_out, rA -> ag_addr_Param
                  n_ag_wen = 1; 
                  n_state = s_WRITE_BRAM;     // Go to BRAM write state
            end
            
            // OP_READ_RAM2U: Read BRAM[rA] into rU
            OP_READ_RAM2U: begin
                  // Note: No streaming support as of Sept 2025
                  n_r_req = 1;                // Assert read request
                  n_state = s_READ_BRAM;      // Go to BRAM read state
            end
            
            //--------------------------------------------------------------------
            // DEFAULT: Unknown opcode
            //--------------------------------------------------------------------
            default: begin
                  n_state = s_IDLE;           // Return to idle on error
            end
            endcase
      end
      //------------------------------------------------------------------------
      // s_READ_BRAM: Wait for BRAM read data to be valid
      //------------------------------------------------------------------------
      s_READ_BRAM: begin
            n_r_req = 0;  // De-assert read request (only 1 cycle needed)
            
            // When BRAM data is valid, store it in rU
            if(rbram_vd) begin
                  n_writeReg = WRITE_BRAM_U;  // Set write operation (rU = r_data)
                  n_state = s_WRITE_REG;      // Go to register write state
            end
            // else: stay in this state until rbram_vd = 1
      end
      
      //------------------------------------------------------------------------
      // s_WRITE_BRAM: Write data to BRAM (single cycle)
      //------------------------------------------------------------------------
      s_WRITE_BRAM: begin
            n_w_req = 0;                      // De-assert write request
            n_ag_wen = 0;
            n_state = s_IDLE;                 // Write completes immediately
      end
      
      //------------------------------------------------------------------------
      // s_WAIT_COMP: Wait for arithmetic operation to complete
      //------------------------------------------------------------------------
      s_WAIT_COMP: begin
            n_c_wait = c_wait + 1'b1;            // Increment wait counter
            
            // When counter reaches target latency, write result
            if(c_wait == opa_c_wait) begin
                  n_writeReg = bwriteReg;     // Use buffered write operation
                  n_state = s_WRITE_REG;      // Go to register write state
            end
            // else: stay in this state
      end
      
      //------------------------------------------------------------------------
      // s_WRITE_REG: Write result to destination register
      //------------------------------------------------------------------------
      s_WRITE_REG: begin
            case (writeReg)
                  
                  // WRITE_T2A: rA = rT
                  WRITE_T2A: begin
                        n_rA = rT;
                  end
                  
                  // WRITE_T2B: rB = rT
                  WRITE_T2B: begin
                        n_rB = rT;
                  end
                  
                  // WRITE_A2B: rB = rA
                  WRITE_A2B: begin
                        n_rB = rA;
                  end
                  
                  // WRITE_A2U: rU = rA (address register)
                  WRITE_A2U: begin
                        n_rU = rA;
                  end
                  // WRITE_add_rA: rA = fixed add result
                  WRITE_add_rA: begin
                        n_rA = res_addAB;
                  end
                  
                  // WRITE_rA1: rA = rA + 1
                  WRITE_rA1: begin
                        n_rA = rAinc;
                  end
                  
                  // WRITE_rB1: rB = rB + 1
                  WRITE_rB1: begin
                        n_rB = rBinc;
                  end
                  
                  // WRITE_BRAM_U: rU = BRAM read data
                  WRITE_BRAM_U: begin
                        n_rU = r_data;
                  end
                  WRITE_S2U: begin
                        n_rU[15:0] = rS;
                        n_rU[64-1:16] = '0;
                  end
                  
                  WRITE_Info2U: begin
                        n_rU = 64'h3130764d5355544e; //  // "NTUSMv01" (version string)
                  end

                  default: begin
                        // No operation
                  end
            endcase
            
            n_state = s_IDLE;  // Always return to idle after write
      end
      
      //------------------------------------------------------------------------
      // s_TXData: Transmit data bytes to PC via UART
      //------------------------------------------------------------------------
      s_TXData: begin
            case(wstoreState)  // Check store sub-state (with FIFO check)
            
            // STORE_LEN: Transmitting bytes from rU
            STORE_LEN: begin
                  // Extract byte from rU at current position
                  tf_data = rU[txPos*8+:8];   // Get byte from rU
                  n_txPos = txPos + 1'b1;        // Move to next byte
                  
                  // If all bytes transmitted, return to idle
                  if(txPos == txMaxPos) begin
                        n_state = s_IDLE;
                  end
                  
                  tf_write = 1;  // Write byte to TX FIFO
            end
            
            // Default/STORE_WAIT: Hold position
            default: begin
                  n_txPos = txPos;
            end
            endcase
      end
      
      //------------------------------------------------------------------------
      // DEFAULT (s_IDLE): Initialize for next operation
      //------------------------------------------------------------------------
      default: begin
            // Reset all counters and prepare for next command
            n_txPos = 0;                // Reset TX byte position
            n_c_wait = 0;               // Reset wait counter
            n_state = s_Fetch;          // Go to fetch state
            n_storeState = STORE_IDLE;  // Set store state to idle
            n_writeReg   = WRITE_NONE;  // No write operation
            n_fetchState = FETCH_GETOP; // Ready to get opcode
            n_fetchMaxPos = 0;          // No data bytes expected yet
      end
      
endcase
end
always @(posedge CLK) begin
	if (RSTlv1A) begin
            rf_dv <= 0;              // Clear FIFO data valid
            // CP <= 4123;              // Program counter (unused in current design)
            state <= s_IDLE;         // Start in idle state
            fetchState <= FETCH_IDLE;  // Fetch state = idle
            ope_state <= '0;          // No operation
            rPos <= '0;               // Reset byte positions

            // Clear all data registers
            rA <= '0;
            rB <= '0;
            rT <= '0;
            rU <= 'h55; // Checking this value as an version by OP_FETCH1U at the beginning of the testbench simulation for debugging.
            // Clear control registers
            c_wait <= '0;
            txPos <= '0;
            txMaxPos <= '0;
            fetchMaxPos <= '0;
            rPos <= '0;
            fetchState <= '0;
            storeState <= '0;
            opa_c_wait <= '0;
            CMD <= '0;
            
            ag_addr_Param <= '1;
            ag_Param <= '1;
            ag_wen <= '0;
	end      
      //------------------------------------------------------------------------
      // NORMAL OPERATION: Update registers with next values
      //------------------------------------------------------------------------
      else begin
            // FIFO handshake delay
            rf_dv[0] <= rf_req;       // Delay 1: rf_req
            rf_dv[1] <= rf_dv[0];     // Delay 2: used for timing
            
            // Control registers
            opa_c_wait <= n_opa_c_wait;  // Update wait target
            c_wait <= n_c_wait;          // Update wait counter

            // Data registers (with pipeline for FP operations)
            rA <= n_rA;
            rB <= n_rB;
            rT <= n_rT;
            rU <= n_rU;
            CMD <= n_CMD;
            
            // State machine registers
            state <= n_state;            // Update main state
            ope_state <= n_ope_state;    // Update operation code
            fetchState <= n_fetchState;  // Update fetch sub-state
            storeState <= n_storeState;  // Update store sub-state

            // Position counters
            rBRPos <= n_rBRPos;
            fetchMaxPos <= n_fetchMaxPos;
            rPos <= n_rPos;
            txPos <= n_txPos;
            txMaxPos <= n_txMaxPos;

            // Write backend registers
            bwriteReg <= n_bwriteReg;  // Update buffered write op
            writeReg <= n_writeReg;    // Update current write op

            // BRAM interface
            w_data <= n_w_data;      // Update BRAM write data
            addr_out <= n_ci_addr;      // Update BRAM write address
            r_req <= n_r_req;        // Update BRAM read request

            
            ag_addr_Param <= n_ag_addr_Param;
            ag_Param <= n_ag_Param;
            ag_wen <= n_ag_wen;
      end
end

// sending block from fifo to uart unit. This looks so waste. Do I really need such this block intrinsically?
// I guess that fifoblock should be incorpolated into transmitter.
// < I agree with the opinion.

always @(posedge CLK) begin 
      if(RSTlv1A) begin
            tx_dv <= 0;
      end
      else begin
            if(tx_dv[0] | tx_dv[1]) begin
                  tx_dv[0] <= 0;
            end
            else if(tx_OK & ~tf_empty) begin
                  tx_dv[0] <= 1;
            end
            tx_dv[1] <= tx_dv[0];
      end
end
//----------------------------------------------------------------------------
// RX FIFO - Buffers incoming UART data
//----------------------------------------------------------------------------

// Stores received bytes from UART until state machine reads them
	
fifo1	fifo1_inst (
      .clock ( CLK ),
      .data ( rx_data_in ), // Input: byte from HOST interface
      .rdreq ( rf_req ),    // Read request from state machine
      .wrreq ( rx_dv ),     // Write request from HOST interface (when byte received)
      .empty ( rf_empty ),  // High when FIFO is empty
      .full ( rf_full ),    // High when FIFO is full
      .q ( rf_data )        // Output: byte to state machine
);

//----------------------------------------------------------------------------
// TX FIFO - Buffers outgoing data to UART
//----------------------------------------------------------------------------
// Stores bytes to be transmitted until UART is ready

fifo1	fifoW_inst (
      .clock ( CLK ),
      .data ( tf_data ),    // Input: byte from state machine
      .rdreq ( tx_dv[0] ),  // Read request (when UART ready)
      .wrreq ( tf_write ),  // Write request from state machine
      .empty ( tf_empty ),  // High when FIFO is empty
      .full ( tf_full ),    // High when FIFO is full (causes STORE_WAIT)
      .q ( tx_data_out )    // Output: byte to UART transmitter
);


//----------------------------------------------------------------------------
// FIXED-POINT ARITHMETIC UNITS
//----------------------------------------------------------------------------
// These perform integer/fixed-point operations with shorter latency

// Pipeline inputs to match ALU timing
reg [P-1:0] addAX, addBX, resX;
always @(posedge CLK) begin
      RSTlv1A <= RST;
      addAX <= rA;          // Full 64-bit value
      addBX <= rB;          // Full 64-bit value
      addA <= addAX;          // Full 64-bit value
      addB <= addBX;          // Full 64-bit value
      resX <= addA + addB;
      res_addAB <= resX;
end


endmodule
