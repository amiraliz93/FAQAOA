`timescale 1ns / 1ns


module frac_extract #(parameter int P =64, parameter int BP = 117)(
    input CLK,
    input signed [2*P-1:0] a, // 128-bit product 
    output signed [P-1:0] q // Q1.63 = 2 * centred fraction in [-1, 1)
);

    reg signed [P-1:0] qreg;
    always @(posedge CLK) 
        
        qreg <= a[BP-1:BP -P]; // bits [BP-1: BP-P] = [116: 53]
    
    assign q = qreg;
endmodule