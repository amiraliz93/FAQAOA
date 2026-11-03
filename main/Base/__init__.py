
import numba.cuda
from .qaoa_simulator_base import Sim_Base
from .Simulators.python.QAOA_simulator import QAOAFURXSimulator, ParamType, CostsType, TermsType
from .Simulators.FPGA.Fpga_sim import FPGASimulator

try:
    from .Simulators.GPU.qaoa_simulatorbase import QAOAFURXSimulatorGPU
except ImportError:
    QAOAFURXSimulatorGPU = None

Simulators = {
    "x": {
       # "c": QAOAFURXSimulatorC,
        "PYTHON": QAOAFURXSimulator,
        "FPGA": FPGASimulator,
        #"gpumpi": QAOAFURXSimulatorGPUMPI,
    }
}

if QAOAFURXSimulatorGPU is not None:
    Simulators["x"]["GPU"] = QAOAFURXSimulatorGPU


def choose_simulator(name="auto", mixer_type="x", **kwargs):
    """Choose QAOA simulator implementation.
    Args:
        name: "auto", "python", "gpu", or "fpga"
        mixer_type: Type of mixer (default "x")
    """
    name = name.upper()
    if name != "auto":
        if name.upper() not in Simulators[mixer_type]:
            raise ValueError(f" Unknown simulator: {name}. Available: {list(Simulators[mixer_type].keys())}")
        return Simulators[mixer_type][name]
    
    # Auto-select: check GPU availability
    if numba.cuda.is_available() and "gpu" in Simulators[mixer_type]:
        return Simulators[mixer_type]["gpu"]

    return Simulators[mixer_type]["python"]
    
   # print(get_available_simulators("x"))
   # return get_available_simulators("x")[0]