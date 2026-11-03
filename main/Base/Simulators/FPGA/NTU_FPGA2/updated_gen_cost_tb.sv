`timescale 1ns / 1ns

// Amir Alizadeh created at Nottingham Trent University.
module updated_gen_cost_tb ();


// Declare signals to connect to the UART module
reg RST;
reg CLK;

// Clock / wait parameters
parameter integer CLOCKWIDTH = 3; // period in ns (timescale 1ns/1ns)
localparam integer CLOCKWIDTH_HALF = (CLOCKWIDTH + 1) / 2; // safe half (round up)
localparam integer CYCLES_50 = 50;
localparam integer CYCLES_WAIT = 100;
localparam integer CLOCKWIDTH50 = CLOCKWIDTH * CYCLES_50; // 50 cycles in ns
localparam integer WAITINTERVAL = CLOCKWIDTH * CYCLES_WAIT;  // 100 cycles in ns
parameter P=64;
localparam N = 1 + 185 + 1; // estimated latency (cycles) of whole pipeline

parameter samples = 20;
// DUT signal
reg  [P-1:0]  gamma; // gamma
reg  [P-1:0]  H;     // sin beta

localparam logic [63:0] gamma_vec [0:samples-1] = '{
  64'h1d7c48859fafd400, 64'hdeda21fbecd70000, 64'h3bdb36833c0a4000, 64'h2e1e2b087d5b9000,
  64'h23b31b9be9eca800, 64'h0514fe67a69b1c00, 64'h4df828e461616000, 64'he7e99f6720c0d400,
  64'hfefccf540d38b800, 64'h4389643d4e602800, 64'hea64d2090faf6c00, 64'h00ede364c0196800,
  64'h3a9371bdcb485000, 64'h3b9227b2d3ba0800, 64'hc10f319ce78b4400, 64'h35b7626a24311000,
  64'h11ef7f1a09c24800, 64'h4732ee62c0788800, 64'hc0fe1541ce007000, 64'hf720510f4af7e000
};

localparam logic [63:0] H_vec [0:samples-1] = '{
  64'hfc58a25612fe7400, 64'heaa6037c125d7000, 64'h2e24dc518f4ccc00, 64'h49a68d516d034000,
  64'hc9abd256d9b19a00, 64'he04af4edf97a6000, 64'hcc08d73e9b8e3800, 64'he4e152476038c000,
  64'h016844891e2f3800, 64'head8beef6e14f800, 64'h4df1dc8d8bea9000, 64'h391d7515c568f800,
  64'h26e2b289cf8f3c00, 64'h0b3e66a0a5e68800, 64'h2d66d689697ac000, 64'h2e16946716078400,
  64'h41e421a30c833800, 64'hc4cea76a47471400, 64'h406a88a25f538000, 64'h4c653dabdb5d2800
};
//reg  [P-1:0]  exact_sol_cos; // exact result
//reg  [P-1:0]  exact_sol_sin; // exat result from python

wire signed [P-1:0]  Hr_o; 
wire signed [P-1:0]  Hi_o;


//wire int_sin_sign = Hi_o[P-1]; 
//wire [2:0] int_sin = Hi_o[P-1:60]; // 3 int part
//wire [60:0] frac_sin = Hi_o[60:0]; // 61 frac part


//  DUT instantiation

updated_gen_cost #(.P(P)) cogen (
      .CLK(CLK),
      .gamma(gamma), // cos gamma
      .H(H),
      .Hr_o(Hr_o),
      .Hi_o(Hi_o)
);


always #CLOCKWIDTH_HALF CLK <= ~CLK;
integer i;


integer measured_latency;
integer maxwait;
integer margin;
reg signed [P-1:0] prev_Hr;
reg signed [P-1:0] prev_Hi;
// initialasation and latency measurement

//gamma={"64'h1d7c48859fafd400", "64'hdeda21fbecd70000", "64'h3bdb36833c0a4000", "64'h2e1e2b087d5b9000", "64'h23b31b9be9eca800", "64'h0514fe67a69b1c00", "64'h4df828e461616000", "64'he7e99f6720c0d400", "64'hfefccf540d38b800", "64'h4389643d4e602800", "64'hea64d2090faf6c00", "64'h00ede364c0196800", "64'h3a9371bdcb485000", "64'h3b9227b2d3ba0800", "64'hc10f319ce78b4400", "64'h35b7626a24311000", "64'h11ef7f1a09c24800", "64'h4732ee62c0788800", "64'hc0fe1541ce007000", "64'hf720510f4af7e000"};H={"64'hfc58a25612fe7400", "64'heaa6037c125d7000", "64'h2e24dc518f4ccc00", "64'h49a68d516d034000", "64'hc9abd256d9b19a00", "64'he04af4edf97a6000", "64'hcc08d73e9b8e3800", "64'he4e152476038c000", "64'h016844891e2f3800", "64'head8beef6e14f800", "64'h4df1dc8d8bea9000", "64'h391d7515c568f800", "64'h26e2b289cf8f3c00", "64'h0b3e66a0a5e68800", "64'h2d66d689697ac000", "64'h2e16946716078400", "64'h41e421a30c833800", "64'hc4cea76a47471400", "64'h406a88a25f538000", "64'h4c653dabdb5d2800"}

integer cycle_counter;
// free-running cycle counter
always @(posedge CLK) begin
  cycle_counter <= cycle_counter + 1;
end

//`include "gen_cost_tb_in.sv" // this file contains the test vectors for gamma and H (in hex format) and expected results (cos, sin, cos2, sin2 in hex format)
initial begin 
      
      CLK <= 0;
      RST <= 1;
      cycle_counter = 0;
      gamma <= 64'h0;
      H <= 64'h0;
      i <= 0;
      @(posedge CLK);

      // apply reset hold cycles
      repeat (10) @(posedge CLK);
      RST <= 0; // not connected to DUT (kept for legacy/test control)

      // apply test vector
      for (i = 0; i <samples ; i = i + 1) begin
        gamma <= gamma_vec[i];
        H <= H_vec[i];
            @(posedge CLK);
      end

      // Measure pipeline latency in cycles by watching DUT outputs
      measured_latency = 0;
      maxwait = 5000; // safety timeout in cycles
      margin = 5; // conservative margin to add


      // wait additional margin cycles to be safe
      if (measured_latency == 0) begin
           // fallback: use estimated N
           $display("Using estimated N = %0d (no change detected)", N);
           repeat (N + 10) @(posedge CLK);
      end else begin
           repeat (measured_latency + margin) @(posedge CLK);
      end

      $stop;

end
endmodule