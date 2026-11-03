`timescale 1ns / 1ns
// Amir Alizadeh - Hiroki Shibata, NTU and Tokyo Metropollitan University, created at Nottingham Trent University.

// Total local cycle is 192 - each mul (10) - frac(1) - cordic (170) - some registe (11)- (1+9+1+9+1+170+1) - total 192 cycles.

// data input registe -> mul1 (X=γ×H) → frac_extra (XF) + mul2(XF* np.pi) -> slicer → CORDIC input
// new_gamma must be in format Q6.58 and new_H must be Q5.59 format (for slicer) 

module updated_gen_cost
  #(
  parameter P=64) // width of additional information
  (
   input  CLK, // all ports
   input  [P-1:0]  gamma, // new_gamma must be in format Q6.58
   input  [P-1:0]   H,  // Q5.59
   output signed [P-1:0]  Hr_o, // real part of e^(i gamma H)
   output signed [P-1:0]  Hi_o // Img part of e^(i gamma H)
);

localparam N0 = 8; // latency new test_mul 10 cycles
localparam N1 = 170; // latency of CORDIC
localparam Pipe = 1+7+1+7+1+N1+1;

// parameter for slcier updated for new gamma nad H
localparam int IG = 6; // int of new_gamma format Q6.58
localparam int IH  = 5; // it means h in fomat Q5.59
localparam int FRAC_G = P - IG;            // 58 for Q6.58
localparam int FRAC_H = P - IH;            // 59 for Q5.59
localparam int BP     = FRAC_G + FRAC_H;   // 117  (binary point of prod1)
localparam signed [P-1:0] PI_Q361 = 64'sd7244019458077122842; //PI_Q361 =  64'sd7244019458077122560;    // == round(pi * 2^61)

// new product for reminder 
wire signed [2*P-1:0] prod1;   // γ0 * H0   (turns; value = prod1 * 2^-117)
wire signed [P-1:0]   frac_q;  // centred signed fraction as Q1.63
wire signed [2*P-1:0] prod2;   // frac_w * π

wire signed [P-1:0]   angle;   // Q3.61 in [-π, π)

reg signed [2*P-1:0] frac_in;
reg signed [P-1:0] mul1_in;
reg signed [P-1:0] mul1_in2;
reg signed [P-1:0] mul2_in;
reg signed [P-1:0] mul2_in2;
reg signed [2*P-1:0] slicer_in; 
reg signed [P-1:0] cordic_in;
// --------------------

reg signed [P-1:0]  cordic_c_out;
reg signed [P-1:0]  cordic_s_out;

// output of the IPs
wire signed [P-2:0] cordic_cos_out;
wire signed [P-2:0] cordic_sin_out;
wire signed [P-1:0]  slicer_out; // slicer output to cordic input

// this mul should do x = \gamma' * H'
Mul_64_FixedP new_mul(    
      .CLK(CLK),
      .a(mul1_in), // H input of multiplier
      .b(mul1_in2),
      .q(prod1)
);

// get fraction bit of  x - get the bit range [116: 53] - interpreted as signed Q1.63
frac_extract #(.P(P), .BP(BP)) fx (.CLK(CLK), .a(prod1), .q(frac_q));

// multiply -> Xf * np.pi 
// frac_q = signed Q1.63 and pi = Q3.61 - it represent 2 * centract_frac(x) where x = gamma * H
// 61 +63 fract bit need to be Q3.61 (124 - 61 = 63 bit fract)
Mul_64_FixedP mul2 (
    .CLK(CLK),
    .a(frac_q),
    .b(PI_Q361),
    .q(prod2)
);


mul_slice #(
	.P(P),
      .IA(1),
      .IB(3),
      .IOUT(3)
) slicer (
      .CLK(CLK),
      .a(prod2),   // output of multiplier
      .q(slicer_out)   // input of cordic
      );
		
// cordic input is (signed Q3.61 radians​) (1 bit sign , 3 bit int, 61 frac) - [-4, 4) range]
// But the valid CORDIC angle range is [-pi, pi]
// CORDIC outpu is signed 63-bit (1 bit sign, 2 bit int, 61 frac) - [-2, 2) range.
CORDIC_64_fixedP inst_cordic(
      	.a(cordic_in),  //  input (it is H*gamma) wire width = [63:0] 
            .areset(1'b0),
		.c(cordic_cos_out),         // output is 63 bits - [62:0] , cos - 61 frac and 2 int
		.clk(CLK),       // clk.clk         
		.s(cordic_sin_out)          //  output is 63 bits [62:0] , sin 61 frac and 2 int
	);


always @(posedge CLK) begin
      
      integer i;

      mul1_in <= gamma;
      mul1_in2 <= H;	
      frac_in <= prod1;
      mul2_in <= frac_q;
      mul2_in2 <= PI_Q361;
      slicer_in <= prod2; // input of slicer is the output 
      cordic_in <= slicer_out; // input of cordic is the output of multiplier after N0 cycles.
      // sign-extend it to 64 bits - this do Q2.61, 63-bit into Q3.61, 64-bit
      cordic_c_out <= {{1{cordic_cos_out[P-2]}}, cordic_cos_out}; // sign extend to 64 bit
      cordic_s_out <= {{1{cordic_sin_out[P-2]}}, cordic_sin_out};
end

assign Hr_o = cordic_c_out; 
assign Hi_o = cordic_s_out; 
endmodule

