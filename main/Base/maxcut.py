"""
Helper functions for the Maximum Cut (MaxCut) problem
"""
from .qaoa_simulator_base import TermsType
import numpy as np
import networkx as nx
from .create_QAOA_circuit import get_parameterized_qaoa_circuit_from_terms, get_qaoa_circuit_from_terms
from typing import Sequence
from qiskit import QuantumRegister, ClassicalRegister


def maxcut_obj(x: np.ndarray, w: np.ndarray) -> float:
    """Compute the value of a cut.
    Args:
        x (numpy.ndarray): binary string as numpy array.
        w (numpy.ndarray): adjacency matrix returned by get_adjacency_matrix
    Returns:
        float: value of the cut.
    """
    X = np.outer(x, (1 - x))
    return np.sum(w * X)  # type: ignore



def get_maxcut_terms(G: nx.Graph) -> TermsType:
    """Get terms corresponding to cost function value
    It converts the MaxCut objective to the form of a cost Hamiltonia
    .. math::
        C(z) = sum_{(i,j)} w_ij * (1 - s_i s_j) / 2

    Terms follow:
        C(z) = total_w/2 - sum_{(i,j)} (w_ij/2) Z_i Z_j

    Args:
        G: MaxCut problem graph
    Returns:
        terms to be used in the simulation ( return directly maxcut so optimiser need to )
    """

    nodelist = list(G.nodes())
    idx = {node: i for i, node in enumerate(nodelist)}

    terms = []
    total_w = 0.0
    for u, v, data in G.edges(data=True):
        w = float(data.get("weight", 1.0))
        terms.append((-w / 2.0, (idx[u], idx[v])))
        total_w += w

    terms.append((total_w / 2.0, tuple()))

    return terms



def get_adjacency_matrix(G: nx.Graph, nodelist=None, dtype=float) -> np.ndarray:
    """Get adjacency matrix to be used in maxcut_obj
    Args:
        G (nx.Graph) : graph
    Returns:
        w (numpy.ndarray): adjacency matrix
    """
    if nodelist is None:
        nodelist = list(G.nodes())
    return nx.to_numpy_array(G, nodelist=nodelist, dtype=dtype)



def get_parameterized_qaoa_circuit(
    G: nx.Graph, p: int, save_statevector: bool = True, qr: QuantumRegister = None, cr: ClassicalRegister = None, return_parameter_vectors: bool = False
):
    """Generates a parameterized circuit for weighted MaxCut on graph G.
    This version is recommended for long circuits

    Parameters
    ----------
    G : networkx.Graph
        Graph to solve MaxCut on
    p : int
        Number of QAOA layers (number of parameters will be 2*p)
    save_statevector : bool, default True
        Add save state instruction to the end of the circuit
    qr : qiskit.QuantumRegister, default None
        Registers to use for the circuit.
        Useful when one has to compose circuits in a complicated way
        By default, G.number_of_nodes() registers are used
    cr : qiskit.ClassicalRegister, default None
        Classical registers, useful if measuring
        By default, no classical registers are added
    return_parameter_vectors : bool, default False
        Return ParameterVector for betas and gammas

    Returns
    -------
    qc : qiskit.QuantumCircuit
        Parameterized quantum circuit implementing QAOA
        Parameters are two ParameterVector sorted alphabetically
        (beta first, then gamma). To bind:
        qc.bind_parameters(np.hstack([angles['beta'], angles['gamma']]))
    """
    terms = get_maxcut_terms(G)
    N = G.number_of_nodes()
    return get_parameterized_qaoa_circuit_from_terms(
        N=N, terms=terms[:-1], p=p, save_statevector=save_statevector, qr=qr, cr=cr, return_parameter_vectors=return_parameter_vectors
    )

def get_qaoa_circuit(G: nx.Graph, gammas: Sequence, betas: Sequence, save_statevector: bool = True, qr: QuantumRegister = None, cr: ClassicalRegister = None):
    """Generates a circuit for weighted MaxCut on graph G.
    Parameters
    ----------
    G : networkx.Graph
        Graph to solve MaxCut on
    beta : list-like
        QAOA parameter beta
    gamma : list-like
        QAOA parameter gamma
    save_statevector : bool, default True
        Add save state instruction to the end of the circuit
    qr : qiskit.QuantumRegister, default None
        Registers to use for the circuit.
        Useful when one has to compose circuits in a complicated way
        By default, G.number_of_nodes() registers are used
    cr : qiskit.ClassicalRegister, default None
        Classical registers, useful if measuring
        By default, no classical registers are added
    Returns
    -------
    qc : qiskit.QuantumCircuit
        Quantum circuit implementing QAOA
    """

    terms = get_maxcut_terms(G)
    N = G.number_of_nodes()
    return get_qaoa_circuit_from_terms(N=N, terms=terms[:-1], gammas=gammas, betas=betas, save_statevector=save_statevector, qr=qr, cr=cr)
