`timescale 1ns / 1ns
// program, split uart functionality to reduce the simulation time
// employment of block design.
// implement all brams.

// todo
// test transmission
// todo 2026, 1, 1.
// set maxAddr, using 64
// set NQbits, using 65
// test mixer, we need theoretical value for this test bench. I need to write some python code

module top1cmd_tb ();

// Declare signals to connect to the UART module
reg RST;
reg CLK;
wire rx_dv;
wire [7:0] rx_data_out;
reg [7:0] tx_data_in;
reg tx_dv;
wire [31:0] o_Status;
reg tx_OK;
parameter CLOCKWIDTH = 10;
parameter CLOCKWIDTH_HALF = 5;
localparam CLOCKWIDTH500   = CLOCKWIDTH*50;
localparam CMD_WAIT        = CLOCKWIDTH*20;
localparam TIME_WAIT_TB    = CLOCKWIDTH*50;
localparam TIME_WAIT_QAOA  = CLOCKWIDTH*100;
localparam N_MAX_WAIT      = 512;
// we need transmitter and receiver to tset state machine (ntu_smachine)
top1 top 
(
   .CLK(CLK),        // Connect to your system clock wire
   .RST(RST),        // Connect to your system reset wire
   .tx_OK(tx_OK),
   .tx_en(rx_dv),
   .tx_data_out(rx_data_out),
   .rx_data_in(tx_data_in),
   .rx_dv(tx_dv),
   .o_Status(o_Status)         // Connect to the wire for the received byte
);


always
begin
      #CLOCKWIDTH_HALF;
      CLK <= ~CLK; // clock generation, half period
end

`include "all_test_cmd.sv"  // The contents of the file will be expanded here.
//`include "new_test_cmd.sv"
localparam OP_NONE = 0; // Send: 1, Res: 0.
localparam OP_SEND1T = 1; // Send: 0, Res: 1.
localparam OP_SEND8T = 2; // Send: 0, Res: 1.
localparam OP_MOV_T2A = 3; // Send: 1, Res: 0.
localparam OP_MOV_T2B = 4; // Send: 1, Res: 0.
localparam OP_MOV_A2U = 5; // Send: 1, Res: 0.
localparam OP_MOV_A2B = 6; // Send: 0, Res: 1.
localparam OP_MOV_Info2U = 8'd7;   // send firmware version info
localparam OP_MOV_S2U    = 8'd8;   // status value to rU.
localparam OP_FETCH1U = 60; // Send: 0, Res: 8.
localparam OP_FETCH8U = 61; // Send: 0, Res: 8.
localparam OP_ADD_B2A = 80; // Send: 0, Res: 0.
localparam OP_MUL_B2A = 81; // Send: 0, Res: 0.
localparam OP_ADDFP_B2A = 82; // Send: 0, Res: 0.
localparam OP_MULFP_B2A = 83; // Send: 0, Res: 0.
localparam OP_INC_A = 84; // Send: 0, Res: 0.
localparam OP_WRITE_T2RAM = 111; // Send: 0, Res: 0.
localparam OP_READ_RAM2U = 112; // Send: 0, Res: 0.
localparam OP_SEND_CMD = 118; // Send: 0, Res: 0. see qa_INIT, qa_WAIT, qa_RUN in qaoa_system.sv
localparam HOST_WAIT  = 254;  // 

localparam qa_WAIT = 1;
localparam qa_RUN = 2;
localparam qa_MIXER = 4;
localparam qa_COST = 8;
localparam qa_INIT = 16;

integer fd;
reg [63:0] fp64;
reg [63:0] None8;
reg [63:0] rx64 = 0;
reg [7:0] recState;
reg [7:0] recCount;
reg [7:0] txCount;
integer i;
integer j;
integer k;
integer t;
reg validRead;
string filename;
always @(posedge CLK) begin
      if(recState == 1) begin
            if(recCount != 8)begin
                  if(rx_dv) begin
                        rx64[recCount*8+:8] <= rx_data_out;
                        recCount <= recCount + 1;
                  end
            end
            else begin
                  recCount <= 0;
                  recState <= 0;
            end
      end
end
initial begin 
      tx_dv <= 0;
      tx_OK <= 1;
      tx_data_in <= 0;
      recCount <= 0;
      recState <= 0;
      txCount <=  0;
      validRead <= 0;

      fp64 = 64'he000_0000_0000_0000; // -1
      None8 = 64'd0;

      #CMD_WAIT;
      #CLOCKWIDTH500;
      for(t = 0;t<2;t=t+1) begin 
      $display("Starting the %d-th computation", t);
      filename = $sformatf("result_sim%0d.txt",t);
      fd= $fopen(filename, "w");
      validRead <= 0;

      for (i = 0; i <ND ; i = i + 1) begin
            tx_data_in <= data_array[i];
            // $fdisplay(fd, "Processing %d -th, data= %d", i, data_array[i]);
            if(txCount != 0) begin 
                  // need to wait until the data flushed.
                  tx_dv <= 1;
                  txCount <= txCount -1;
                  #CLOCKWIDTH;
                  tx_dv <= 0;
                  #CMD_WAIT;
            end
            else if(data_array[i] == OP_SEND8T) begin 
                  txCount <= 8;
                  tx_dv <= 1;
                  #CLOCKWIDTH;
                  tx_dv <= 0;
                  #CMD_WAIT;
            end
            else if(data_array[i] == OP_SEND1T) begin 
                  txCount <= 1;
                  tx_dv <= 1;
                  #CLOCKWIDTH;
                  tx_dv <= 0;
                  #CMD_WAIT;

            end
            else if(data_array[i] == HOST_WAIT) begin
                  validRead <= 1;
                  for(j = 0; j < N_MAX_WAIT; j = j + 1) begin
                        tx_data_in <= OP_MOV_S2U;
                        tx_dv <= 1;
                        # CLOCKWIDTH;
                        tx_dv <= 0;
                        # CMD_WAIT;
                        recCount <= 0;
                        recState <= 1;
                        tx_dv <= 1;
                        tx_data_in <= OP_FETCH8U;
                        # CLOCKWIDTH;
                        tx_dv <= 0;
                        for(k = 0; k < N_MAX_WAIT; k = k + 1) begin
                              #CMD_WAIT;
                              if(k == N_MAX_WAIT -1) begin 
                                    $fwrite(fd, "waiting time out %d\n", k);
                              end
                              if(recState == 0) begin 
                                    break;
                              end 
                        end

                        if(rx64[7:0] == qa_WAIT) begin
                              break;
                        end
                        # CMD_WAIT;
                  end
            end
            else if(data_array[i] == OP_FETCH8U) begin
                  recCount <= 0;
                  recState <= 1;
                  tx_dv <= 1;
                  # CLOCKWIDTH;
                  tx_dv <= 0;
                  for(k = 0; k < N_MAX_WAIT; k = k + 1) begin
                        #CMD_WAIT;
                        if(k == N_MAX_WAIT -1) begin 
                              $fwrite(fd, "waiting time out %d\n", k);
                        end
                        if(recState == 0) begin 
                              break;
                        end 
                  end
                  if(validRead) begin 
                        $fwrite(fd, "0x%016h\n", rx64);
                  end
            end
            else begin
                  tx_dv <= 1;
                  #CLOCKWIDTH;
                  tx_dv <= 0;
                  #CMD_WAIT;
            end
      end



      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      #CMD_WAIT;
      $display("finished the %d-th computation", t);
      $fclose(fd);
      end
      $stop;
end
// Initialize signals
initial begin
      RST <= 1; // Reset active-high
      CLK <= 0;
      // Apply reset
      #CMD_WAIT;
      RST <= 0;


      // End simulation
end

endmodule
