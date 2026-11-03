# This is part of my PhD project, Develping a hybrid Quantum Computational Platform 
## QAOA Simulator (CPU/GPU) — Max‑Cut Focus

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![DOI](https://img.shields.io/badge/DOI-pending-orange)]()


### Progress
- [x] CPU/NumPy reference backend
- [x] GPU/CuPy backend (core rotations)
- [x] Vectorized grid evaluation for (β, γ)
- [x] Unit tests parity CPU↔GPU
- [x] Optional FPGA backend behind the same interface
- [ ] Add Bayesian Optimiser MAVE-BO

A modular Quantum Approximate Optimization Algorithm (QAOA) toolkit with clean separation between objective functions, circuit builders, and simulation backends. The repository currently supports pure‑Python/NumPy and GPU (CuPy/CUDA) execution, with precomputation helpers to accelerate diagonal cost phases. It is designed for research workflows (experiments, notebooks) and for future extension (e.g., FPGA or other accelerators).
This project consists of different QAOA simulations based on Qiskit, using a GPU and, in the future FPGA

## Highlights
- Problem‑first design: clear Max‑Cut objective modules, extensible to other Ising/QUBO problems.
- Pluggable simulators: switch between Python/NumPy and GPU (CuPy) without changing experiment code.
- Precomputation utilities: cache diagonal Hamiltonian factors and rotation tables for faster sweeps.
- Simple API surface: one place to define parameters (β, γ), one call to evaluate the objective.
- Research‑friendly: notebooks and a minimal test script to reproduce small cases quickly.

## Core Concepts

### Use‑case matrix (what to run, where to look)
| Goal                                             | Input(s)                   | Recommended Backend                 | Key Modules/Files                                                                                                 | Example call                           | Output                   |
| ------------------------------------------------ | -------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------- | ------------------------ |
| **Single Max-Cut value** for a small graph (p=1) | `networkx.Graph`, `(β, γ)` | **CPU/NumPy** (fast dev)            | `main/QAOA_Objective_max_cut.py`, `main/Base/qaoa_circuit_maxcut.py`, `main/Simulators/python/QAOA_simulator.py`  | `obj.evaluate(sim_cpu, betas, gammas)` | Scalar expectation value |
| **Grid scan** over `(β, γ)` (heatmap)            | graph, arrays of β & γ     | **CPU** (≤1k points), **GPU** (≫1k) | `parameter_utils.py`, `Simulators/precomputation/numpy_vectorized.py` or `Simulators/precomputation/gpu_numba.py` | loop or vectorized `evaluate`          | 2D array (β×γ)           |
| **Benchmark CPU vs GPU**                         | fixed graph & schedule     | **Both**                            | CPU & GPU simulators; `Base/qaoa_simulator_base.py`                                                               | time `evaluate` on each backend        | timing table/plot        |
| **Large graph (n≥20) diag-cost test**            | graph, γ sweep             | **GPU** + **precompute**            | `Simulators/GPU/*`, `Simulators/precomputation/*`                                                                 | precompute phases → run                | scalar(s) per γ          |
| **Notebook exploration**                         | Jupyter                    | **CPU first**                       | `main/Test/*.ipynb`                                                                                               | run cells                              | printed metrics/plots    |
| **Unit sanity test**                             | none                       | **CPU**                             | `main/Test/test_qaoa.py`                                                                                          | `python -m main.Test.test_qaoa`        | pass/fail + value        |


### Objective layer (main/QAOA_objective.py, main/QAOA_Objective_max_cut.py)
- Defines cost Hamiltonian and expectation for Max‑Cut.
- Provides an evaluate(sim, betas, gammas) entry‑point that:
  - builds the p‑layer circuit via circuit utilities,
  - executes on the selected simulator,
  - returns the objective value (e.g., expected cut weight).
 
### Circuit layer((main/Base/qaoa_circuit1.py, qaoa_circuit_maxcut.py))
- Assembles the layered QAOA circuit (Hadamards → [Cost(γ), Mixer(β)] × p → measurement/expectation).
- The Max‑Cut variant uses the graph structure to apply ZZ phase rotations on edges.
### Simulator (main/simulators/...)
- CPU (Python/NumPy): reference implementation, easiest to debug.
- GPU (CuPy/CUDA): accelerates rotations/state updates; some kernels live in furx.cu.
- FPGA: implementing QAOA on FPGA Board
- Precomputation helpers: optionally compute diagonal terms or rotation tables once per (β, γ) to reduce per‑iteration cost.

### Base scaffolding (main/Base/qaoa_simulator_base.py)
- A lightweight interface that concrete simulators implement (state init, layer application, expectation, dtype/precision).
### MaxCut
Coming soon
### Configuration & Tips
Coming soon

## Highlights
- Problem‑first design: clear Max‑Cut objective modules, extensible to other Ising/QUBO problems.
- Pluggable simulators: switch between Python/NumPy and GPU (CuPy) without changing experiment code.
- Precomputation utilities: cache diagonal Hamiltonian factors and rotation tables for faster sweeps.
- Simple API surface: one place to define parameters (β, γ), one call to evaluate the objective.
- Research‑friendly: notebooks and a minimal test script to reproduce small cases quickly.

## Core Concepts

Creating a virtual environment, as some libraries require a specific version, could lead to a dependency conflict. 
### Use‑case matrix (what to run, where to look)
| Goal                                             | Input(s)                   | Recommended Backend                 | Key Modules/Files                                                                                                 | Example call                           | Output                   |
| ------------------------------------------------ | -------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------- | ------------------------ |
| **Single Max-Cut value** for a small graph (p=1) | `networkx.Graph`, `(β, γ)` | **CPU/NumPy** (fast dev)            | `main/QAOA_Objective_max_cut.py`, `main/Base/qaoa_circuit_maxcut.py`, `main/Simulators/python/QAOA_simulator.py`  | `obj.evaluate(sim_cpu, betas, gammas)` | Scalar expectation value |
| **Grid scan** over `(β, γ)` (heatmap)            | graph, arrays of β & γ     | **CPU** (≤1k points), **GPU** (≫1k) | `parameter_utils.py`, `Simulators/precomputation/numpy_vectorized.py` or `Simulators/precomputation/gpu_numba.py` | loop or vectorized `evaluate`          | 2D array (β×γ)           |
| **Benchmark CPU vs GPU**                         | fixed graph & schedule     | **Both**                            | CPU & GPU simulators; `Base/qaoa_simulator_base.py`                                                               | time `evaluate` on each backend        | timing table/plot        |
| **Large graph (n≥20) diag-cost test**            | graph, γ sweep             | **GPU** + **precompute**            | `Simulators/GPU/*`, `Simulators/precomputation/*`                                                                 | precompute phases → run                | scalar(s) per γ          |
| **Notebook exploration**                         | Jupyter                    | **CPU first**                       | `main/Test/*.ipynb`                                                                                               | run cells                              | printed metrics/plots    |
| **Unit sanity test**                             | none                       | **CPU**                             | `main/Test/test_qaoa.py`                                                                                          | `python -m main.Test.test_qaoa`        | pass/fail + value        |


### Objective layer (main/QAOA_objective.py, main/QAOA_Objective_max_cut.py)
- Defines cost Hamiltonian and expectation for Max‑Cut.
- Provides an evaluate(sim, betas, gammas) entry‑point that:
  - builds the p‑layer circuit via circuit utilities,
  - executes on the selected simulator,
  - returns the objective value (e.g., expected cut weight).
 
### Circuit layer((main/Base/qaoa_circuit1.py, qaoa_circuit_maxcut.py))
- Assembles the layered QAOA circuit (Hadamards → [Cost(γ), Mixer(β)] × p → measurement/expectation).
- The Max‑Cut variant uses the graph structure to apply ZZ phase rotations on edges.
### Simulator (main/simulators/...)
- CPU (Python/NumPy): reference implementation, easiest to debug.
- GPU (CuPy/CUDA): accelerates rotations/state updates; some kernels live in furx.cu.
- FPGA: implementing QAOA on FPGA Board
- Precomputation helpers: optionally compute diagonal terms or rotation tables once per (β, γ) to reduce per‑iteration cost.

### Base scaffolding (main/Base/qaoa_simulator_base.py)
- A lightweight interface that concrete simulators implement (state init, layer application, expectation, dtype/precision).
### MaxCut
Coming soon
### Configuration & Tips
Coming soon

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Code                        │
└─────────────────────┬───────────────────────────────────────┘
                      │
         ┌────────────▼────────────┐
         │  QAOA_Objective_max_cut │ ◄── Problem Definition
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │   qaoa_circuit_maxcut   │ ◄── Circuit Builder
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────────────────┐
         │      Simulator Interface            │
         └─┬──────────────────────────────────┬┘
           │                                  │
    ┌──────▼──────┐                  ┌───────▼────────┐
    │ CPU/NumPy   │                  │  GPU/CuPy      │
    │ Simulator   │                  │  Simulator     │
    └─────────────┘                  └────────────────┘
```


## How to install 

### 1. Create a Virtual Environment
Creating a virtual environment, as some libraries require a specific version, could lead to a dependency conflict. 
```bash
python -m venv qokit
source qokit/bin/activate
pip install -U pip

```
```
### 2. Install from GitHub
Then, need to clone the repository 
```bash
git clone https://github.com/amiraliz93/QAOAHP.git
cd main/
# Install in editable mode
pip install -e
**Or install directly from GitHub:**
Or  if you are using GitHub Desktop, use this:
https://github.com/amiraliz93/QAOAHP.git

## Install dependencies
pip install -U pip
pip install -r requirements.txt
```
### GPU (optional)
- Install CuPy that matches your CUDA toolkit (e.g., cupy-cuda12x).
- Verify with python -c "import cupy; print(cupy.__version__)".

## Gallery
<p align="center">

</p>

### FPGA
To re-generate the result presented at QAI conference, first write FPGA program defined in Golden_TOP.qpf into TR5 FPGA board under the directory main/Base/Simulators/FPGA/NTU_FPGA2/. To compile it, you need Quartus Prime Standard Edition version 25.x provided by ALtera (FPGA productor). Then run `stats.py` at the stop directory, after connecting FPGA on `COM3` via UART. If you connected on different port, please replace `COM3` in stats.py. 

`stats.py` will typically require python3 of version 11.3. Please prepare virtual environment if you need that. requirements.txt should list all the required library to run the script.

We prepared comparison on qiskit. To run the task of fair comparison by qiskit against our implementation on FPGA, run `stats_qiskit.py`. 

All the result will be written in `statistics.txt`. If you newly start recording the statistics, first delete `statistics.txt` so that it will not include any old results. Both results of either `stats_qiskit.py` or `stats.py` will be written in the same `statistics.txt` at the directory where you run those scripts. The file name `statistics.txt` is hard coded. If you want to change it, look into the source code of python modules in the project just by searching the word statistics.txt.

`plot_statistics.py` will generate a graph of comparison in SVG format into `out.svg`. This script is mostly generated by AI. 

### How to Cite
If this code contributes to published work, please reference the repository and your commit/tag. A BibTeX stub can be added once a preprint is available.
## Acknowledgements
This project is adapted from [QOkit](https://github.com/jpmorganchase/QOKit/tree/main), 
#### // Copyright: JP Morgan Chase & Co
which is licensed under the Apache-2.0 License.
