# report of various comparison

This report describes comparison between qiskit on CPU and FPGA with our implementation. 

Basic specifications are,

CPU: Ryzen 9950X, 5.7 GHz, 32 MB cache memory, 16 cores
FPGA: Stratix 5, 320 MHz

We set the performance configuration of CPU at its maximum one. On Windows, power schedule was set to best performance, and in firmware configuration of motherboard, the power consumption setting was set to auto, where the CPU will consume as much power as possible on the system. 

fixP-N.svg is a result of comparison between qiskit and FPGA on various parameters of number of qbits N=1, N=2,...,16. Number of layers are 1 for all case. In this graph qiskit@$x$GHz means a result on the CPU run at the frequence of $x$ GHz. Each frequency is archived from UEFI configuration menu of the Motherboard. We can FPGA outperforms qiskit on all situation, despite its relatively low frequence (5.7 GHz vs 0.32 GHz). It is supposed due to the overhead to run the pipeline of the CPU. FPGA have no such overhead because it is implemented so that it does not waste clocks during computations. We can observe there is no increase at N = 2,3,4,5 for the FPGA. It is a result of non-stopping pipeline implementation, where in the case of N less than 6, the pipeline frequently has a chance it must wait to flush its contents. Decrease of the computation time for qiskit around N=14 is suppose to be a result by the paralell implementation of qiskit, where it may enable its parallelization when it have N greater than 14.

CN-P.svg is the comparison on $P=1,2,....,32, N=4,6,10,12,14,16$, to see the effect of increasing $P$. FPGA$N$ means the result by FPGA for number of qbits $N$. So for qiskit$N$. Theoretically, all the graph must be linear with a gradient of one. However, most of qiskit's result are not linear. It is supposed to be a result of the same overhead as mentioned in the result of fixP-N.svg. As an overall tendency, we can observe all the curves converges into linear lines as P increases. The tendency is consistent with the theoretical expectation.

During the Here is the comparison on energy consumption.  We measured following power consumption.

C_i: power consumption by CPU when it is idle state.
F_i: power consumption by FPGA when it is idle state.
C_c: power consumption by CPU when it is doing the computation.
F_c: power consumption by FPGA when it is doing the computation.
C_p: estimated power consumption by CPU for the computation.
F_p: estimated power consumption by FPGA for the computation.

We have following equations.

C_p = C_c - C_i, F_p = F_c - F_i.

To calculate C_i, C_c, we record the power consumption 8 times, and averaged those observations to get C_i, C_c. For F_c, F_i we took the same procedure. Then we got the following result.

C_p: 31.2 W
F_p: 4.0 W

CPU consumes much more power, despite of its lower performance than that of FPGA. It is clear that FPGA is more power efficient. Please also note that the FPGA we utilized was released in 2012, while the CPU we utlized was releaesd in 2025. Generally older devices has much lower power efficiency than new ones. Therefore, the result shows high potential of the FPGA implementation to the power efficient computation.