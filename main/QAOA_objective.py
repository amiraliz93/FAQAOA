from __future__ import annotations
from calendar import c
import numpy as np
from qiskit import transpile
from qiskit.quantum_info import Statevector
from qiskit_aer import Aer
from functools import reduce
from qiskit_aer import AerSimulator
import typing
import networkx as nx
import time
from .Base import choose_simulator, qaoa_simulator_base
from . import parameter_utils
from .parameter_utils import QAOAParameterization
#from .qaoa_circuit_portfolio import measure_circuit
from .Base.precomputation import precompute_vectorized_cpu_parallel
from .Base.maxcut import get_maxcut_terms

# ============================================================================
# QISKIT SIMULATOR BACKEND
# ============================================================================


def _create_qiskit_objective(
    N, precomputed_diagonal_hamiltonian, precomputed_costs,
    terms, precomputed_optimal_bitstrings, parameterization,
    objective, parameterized_circuit, optimization_type
):
    """Create a QAOA objective function using Qiskit as the simulator backend
    
    Args:
        N: Number of qubits
        precomputed_diagonal_hamiltonian: Precomputed diagonal Hamiltonian
        precomputed_costs: Precomputed cost array
        terms: Hamiltonian terms
        precomputed_optimal_bitstrings: Optimal bitstrings for overlap objective
        parameterization: Parameter format for QAOA angles
        objective: Type of objective function ("expectation" or "overlap")
        parameterized_circuit: Optional pre-built circuit
        optimization_type: Whether to minimize or maximize
        
    Returns:
        Callable objective function for optimization
    """
    # Set up simulator
    simulator = AerSimulator(method='statevector')
    
    # Get or create parameterized circuit
    if parameterized_circuit is None:
        from .Base.create_QAOA_circuit import get_parameterized_qaoa_circuit_from_terms        
        # For MaxCut problems with terms
        if terms is not None:
            circuit_creator = lambda p: get_parameterized_qaoa_circuit_from_terms(
                N=N, terms=terms, p=p, save_statevector=True, return_parameter_vectors=False)
        else:
            raise ValueError("Either 'parameterized_circuit' or 'terms' must be provided")
    else:
        # Use provided circuit
        circuit_creator = lambda p: parameterized_circuit
        
    # Prepare cost array for calculations
    if precomputed_costs is None and precomputed_diagonal_hamiltonian is not None:
        costs = precomputed_diagonal_hamiltonian
    elif precomputed_costs is not None:
        costs = precomputed_costs
    elif terms is not None:
        costs = precompute_vectorized_cpu_parallel(terms, 0.0, N)
    else:
        raise ValueError("Either terms or precomputed costs must be provided")
    
    # Process optimal bitstring indices if needed
    optimal_indices = None
    if precomputed_optimal_bitstrings is not None and objective == "overlap":
        optimal_indices = np.array([reduce(lambda a, b: 2 * a + b, x)
                                    for x in precomputed_optimal_bitstrings
        ])
   
    def objective_function(*params):
        # Convert parameters to gamma/beta format
        gamma, beta = parameter_utils.convert_to_gamma_beta(
              *params, parameterization=parameterization)
        
        # Get parameterized circuit with appropriate depth
        p = len(gamma)
        qc = circuit_creator(p)
        
        # Bind the parameters to the circuit
        #parameter_values = []
        #for g, b in zip(gamma, beta):
        #    parameter_values.extend([g, b])
        parameter_values = np.hstack([beta, gamma])
        

        # Run Circuit
        # Transpile circuit for the simulator


        bound_qc = qc.assign_parameters(dict(zip(qc.parameters,
parameter_values)), inplace=False)
        transpiled_qc = transpile(bound_qc, simulator)
        
        t0 = time.perf_counter()
        job = simulator.run(transpiled_qc)
        result = job.result()
        elapsed = time.perf_counter() - t0
        statevector = result.get_statevector()


        print(f"qiskit_compute_sec {elapsed:.9g} s")

        with open("statistics.txt", "a") as fp:
            fp.write("---------------------------------------\n")
            fp.write("  summary of the computation  \n")
            fp.write("---------------------------------------\n")
            fp.write(f"qiskit: {elapsed:.9g}\n")
            fp.write(f"NQ: {int(np.log2(len(statevector)))}\n")
            fp.write(f"NP: {p}\n")
            fp.write(f"NS: {len(statevector)}\n")
        
        # Calculate expectation value <ψ|H|ψ>
        probabilities = np.abs(statevector.data)**2

        # Calculate objective value
        if objective == "expectation":
            expectation = costs.dot(probabilities)
            # Adjust sign based on optimization direction
            return -expectation if optimization_type == "max" else expectation
        
        elif objective == "overlap":
            # Calculate overlap with optimal states
            if optimal_indices is not None:
                overlap = sum(probabilities[idx] for idx in optimal_indices)
            
            # Return 1-overlap for minimization
                return 1.0 - overlap
        else:
            raise ValueError(f"Unknown objective type: {objective}")
    
    return objective_function

# ============================================================================
# MAIN QAOA OBJECTIVE FUNCTION (CPU/GPU/FPGA)
# ============================================================================

def get_qaoa_objective(
    N: int |None = None,
    G: nx.Graph | None = None,
    terms = None, # we define this terms
    precomputed_diagonal_hamiltonian=None, # not define
    precomputed_costs: np.ndarray | None = None,
    precomputed_optimal_bitstrings: np.ndarray | None = None,
    parameterization: str | QAOAParameterization = "theta",
    objective: str = "expectation",
    parameterized_circuit=None,
    simulator: str = "auto", # we define this parameter
    mixer: str = "x",
    initial_state: np.ndarray | None = None,
    n_trotters: int = 1,
    optimization_type="min",
    fpga_config: dict | None = None,
    ) -> typing.Callable:

    """Return QAOA objective to be minimized
 Parameters
    ----------
    N : int
        Number of qubits
    p : int
        Number of QAOA layers (number of parameters will be 2*p)
    parameterization : str
        If parameterization == 'theta', then f takes one parameter (gamma and beta concatenated)
        If parameterization == 'gamma beta', then f takes two parameters (gamma and beta)
        For below Fourier parameters, q=p
        If parameterization == 'freq', then f takes one parameter (fourier parameters u and v concatenated)
        If parameterization == 'u v', then f takes two parameters (fourier parameters u and v)
    objective : str
        If objective == 'expectation', then returns f(theta) = - < theta | C_{LABS} | theta > (minus for minimization)
        If objective == 'overlap', then returns f(theta) = 1 - Overlap |<theta|optimal_bitstring>|^2 (1-overlap for minimization)
    simulator : str
        If simulator == 'auto', implementation is chosen automatically
            (either the fastest CPU simulator or a GPU simulator if CUDA is available)
        If simulator == 'qiskit', implementation in qaoa_qiskit is used
    mixer : str
        If mixer == 'x', then uses the default Pauli X as the mixer
        If mixer == 'xy', then uses the ring-XY as the mixer
    initial_state : np.ndarray
        The initial state for QAOA, default is the uniform superposition state (corresponding to the X mixer)
    n_trotters : int
        Number of Trotter steps in each mixer layer for the xy mixer

    Returns
    -------
    f : callable
        Function returning the negative of expected value of QAOA with parameters theta
"""

# 1. HANDLE MAXCUT GRAPH INPUT
# ============================================

    if G is not None:
        if N is None:
            N = G.number_of_nodes()  # Auto-detect N
        if terms is None:
            terms = get_maxcut_terms(G)  # Auto-generate terms
        if optimization_type == "min":
            optimization_type = "max"  # MaxCut is maximization
    
    if N is None: 
        raise ValueError("N must be specified if G is not provided")
    simulator = simulator.upper()
    # 2. QISKIT SIMULATOR
# ============================================
#  Qiskit edge case
    if simulator == "QISKIT":
        """
        if precomputed_costs is None:
            precomputed_costs = precomputed_diagonal_hamiltonian
           # assert precomputed_costs is not None, f'the precomputed_costs still None {precomputed_costs}'
        g = _get_qiskit_objective(
                parameterized_circuit,
                precomputed_costs,
                precomputed_optimal_bitstrings,
                objective,
                terms,
                parameterization,
                mixer,
                optimization_type=optimization_type,
            )

        #def fq(*args):
            gamma, beta = parameter_utils.convert_to_gamma_beta(*args, parameterization=parameterization)
            return g(gamma, beta)

        return fq
        """
        return _create_qiskit_objective(
            N, precomputed_diagonal_hamiltonian, precomputed_costs,
            terms, precomputed_optimal_bitstrings, parameterization,
            objective, parameterized_circuit, optimization_type
        )
# ============================================

# 3. REGULAR SIMULATOR (CPU/GPU/FPGA)
# ============================================
    if mixer == "x": # for x mixer 
        sim = choose_simulator(name= simulator)(N, terms=terms, costs=precomputed_diagonal_hamiltonian, fpga_config=fpga_config)
    else:
        raise ValueError(f"Unknown mixer type passed to get_qaoa_objective: {mixer}, allowed ['x', 'xy']")
    
    # -- Precomputations
    if precomputed_costs is None:
        precomputed_costs = sim.get_cost_diagonal()

    # Convert optimal bitstrings to indices
    bitstring_loc = None
    if precomputed_optimal_bitstrings is not None and objective != "expectation":
        bitstring_loc = np.array([reduce(lambda a, b: 2 * a + b, x) for x in precomputed_optimal_bitstrings])

# 4. Create objective function
#===== ======================================
    # -- Final function

    def objective_fun(*args):
        gamma, beta = parameter_utils.convert_to_gamma_beta(*args, parameterization=parameterization)

        result = sim.simulate_qaoa(gamma, beta, initial_state, n_trotters=n_trotters)
        if objective == "expectation":
            return sim.get_expectation(result, costs=precomputed_costs, preserve_state=False, optimization_type=optimization_type)

        elif objective == "overlap":
            overlap = sim.get_overlap(result, costs=precomputed_costs, indices=bitstring_loc, preserve_state=False, optimization_type=optimization_type)
            return 1 - overlap
        else:
            raise ValueError(f"Unknown objective: {objective}")

    return objective_fun


