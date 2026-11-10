"""
qaoa_experiment.py - one QAOA experiment on the FPGA or on Qiskit Aer, checked against the C++ reference.

Run it from the project folder, like fpga_sim_test.py:

  python qaoa_experiment.py --mode random --NQ 16 --Np 1 --port COM5
  python qaoa_experiment.py --mode graph --graph regular --degree 3 --NQ 8 --Np 4 --port COM5
  python qaoa_experiment.py --mode graph --NQ 8 --Np 2 --port COM5 --optimise --budget 100 --seed 1
  python qaoa_experiment.py --mode graph --graph regular --degree 3 --NQ 8 --Np 4 --sim aer --repeats 5

--mode random : the test problem of fpga_sim_test.py (same seed, same numbers).
--mode graph  : Max-Cut on a graph, starting from |+>. Choose the graph with
                --graph regular | complete | erdos | file and its options.
--optimise    : COBYLA tunes the angles, with the FPGA doing every evaluation.
--fast-io     : send the commands to the board in blocks and leave out bytes that change
                nothing (see FastIODriver); without it the repository's driver is used unchanged.
--sim aer     : the same Max-Cut problem (same graph and angles) on Qiskit Aer instead of the
                FPGA, timed by your objective in main/QAOA_objective.py (simulator="qiskit",
                as q2test.py uses it). --device CPU (default); GPU is kept open for later
                (needs a GPU build of qiskit-aer; not tested). No board is needed.

Results go to results/simple/ (python show_results.py prints them as tables):
  runs.csv          one row per evaluation (column sim = fpga or aer; times, counter, error vs C++)
  optimise.csv      one row per optimiser evaluation (with --optimise)
  statistics.txt    "FPGA time" blocks in the format of fpga_sim_test.py and, with --sim aer,
                    the "qiskit:" blocks that QAOA_objective.py writes
  <run folder>/     resultFPGA-*.txt and result-*.txt (hex, as before), data.npz and
                    driver.log (the driver's messages; add --verbose to see them on screen)

Angles are in the FPGA convention: each layer multiplies amplitude i by
exp(+i*gamma*eps_i), then applies exp(-i*beta*X) to every qubit. For Aer they are
converted (see run_aer), so both simulators compute the same state.
"""
import argparse
import csv
import datetime
import functools
import hashlib
import io
import math
import os
import pickle
import random
import re
import struct
import subprocess
import time
from contextlib import chdir, nullcontext, redirect_stdout
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.optimize import minimize

from main.Base.maxcut import get_maxcut_terms
from main.Base.precomputation import precompute_vectorized_cpu_parallel
from main.Base.Simulators.FPGA.Fpga_sim import FPGASimulator, FpgaDriver

HERE = Path(__file__).resolve().parent
FPGA_DIR = HERE / "main" / "Base" / "Simulators" / "FPGA"
OUT = HERE / "results" / "simple"
DRIVER_LOG = None        # set in main(): the driver's messages go to driver.log unless --verbose


def driver_messages():
    """Send the driver's console messages to driver.log instead of the screen."""
    return redirect_stdout(DRIVER_LOG) if DRIVER_LOG else nullcontext()


# ---------------------------------------------------------------- 1. problem
def make_graph(args):
    if args.graph == "regular":
        G = nx.random_regular_graph(args.degree, args.NQ, seed=args.graph_seed)
    elif args.graph == "complete":
        G = nx.complete_graph(args.NQ)
    elif args.graph == "erdos":
        G = nx.gnp_random_graph(args.NQ, args.edge_prob, seed=args.graph_seed)
    else:  # "file": a pickled networkx graph, e.g. graph_14_unweighted.pkl
        with open(args.graph_file, "rb") as f:
            G = pickle.load(f)
    return nx.convert_node_labels_to_integers(G, ordering="sorted")   # node j = qubit j


def make_problem(args):
    """Returns cost diagonal eps, start state sv0, angles gammas and betas, graph (or None)."""
    if args.mode == "random":      # copied from fpga_sim_test.level2_hardware
        NS = 1 << args.NQ
        random.seed(0x22a2037)
        eps = np.array([random.uniform(-190, 190) for _ in range(NS)])
        gammas = np.array([random.uniform(-math.pi, math.pi) for _ in range(args.Np)])
        betas = np.array([random.uniform(-math.pi, math.pi) for _ in range(args.Np)])
        sv0 = np.array([complex(random.uniform(-1, 1), random.uniform(-1, 1)) for _ in range(NS)])
        return eps, sv0 / np.linalg.norm(sv0), gammas, betas, None

    G = make_graph(args)
    n = G.number_of_nodes()
    eps = np.asarray(precompute_vectorized_cpu_parallel(get_maxcut_terms(G), 0.0, n), dtype=float)
    sv0 = np.full(1 << n, 1 / np.sqrt(1 << n), dtype=complex)
    # one (gamma, beta) pair per layer: the first layers are the same for every Np
    u = np.random.default_rng(args.angle_seed).uniform(size=(args.Np, 2))
    return eps, sv0, np.pi * u[:, 0], (np.pi / 2) * u[:, 1], G


# ---------------------------------------------------------------- 2. C++ reference
def cpp_exe():
    """Build qaoa_sim.cpp if needed (same flags as fpga_sim_test.py); called before any timing."""
    exe = FPGA_DIR / ("qaoa_sim.exe" if os.name == "nt" else "qaoa_sim")
    src = FPGA_DIR / "qaoa_sim.cpp"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(["g++", "-O3", "-march=native", "-std=c++20", str(src), "-o", str(exe)], check=True)
    return exe


def cpp_reference(sim, eps, sv0, gammas, betas, folder):
    """qaoa_sim.cpp with the same inputs and file format as fpga_sim_test.py."""
    exe = cpp_exe()
    NS, p = len(eps), len(gammas)
    n = NS.bit_length() - 1
    H_s, g_s, _ = sim._scale_H_gamma(eps, gammas)          # the driver's own scaling
    with open(folder / "qaoa_sim_input.bin", "wb") as f:
        f.write(struct.pack("<IIII", 0x51414F41, n, p, NS))
        for a in (sv0.real, sv0.imag, H_s, g_s, np.cos(betas), np.sin(betas)):
            np.asarray(a, dtype="<f8").tofile(f)
    t0 = time.perf_counter()
    subprocess.run([str(exe), "qaoa_sim_input.bin", "qaoa_sim_output.bin", f"result-NQ{n}-NP{p}.txt"],
                   cwd=folder, check=True, capture_output=True)
    t_cpp = time.perf_counter() - t0
    raw = np.fromfile(folder / "qaoa_sim_output.bin", dtype="<f8")
    return raw[:NS] + 1j * raw[NS:], t_cpp


# ---------------------------------------------------------------- 3. FPGA
def add_timers(drv, T):
    """Time each driver step; the driver itself is unchanged."""
    for name in ("load_data", "execute", "read_result"):
        def timed(*a, _f=getattr(drv, name), _name=name, **k):
            t0 = time.perf_counter()
            out = _f(*a, **k)
            T[_name] = time.perf_counter() - t0
            return out
        setattr(drv, name, timed)


def run_fpga(sim, T, gammas, betas, sv0):
    T.clear()
    sim.fpga.counter = None
    t0 = time.perf_counter()
    with driver_messages():
        state = sim.simulate_qaoa(gammas, betas, sv0=sv0.copy())     # as in fpga_sim_test.py
    T["eval"] = time.perf_counter() - t0
    if sim.fpga.counter is None:
        raise RuntimeError("no result read back from the FPGA (see driver.log in the run folder)")
    return state


class FastIODriver(FpgaDriver):
    """The repository's driver with faster transfer (--fast-io). The driver builds its usual
    command stream; only the way the PC sends it changes:
      load_data   : all bytes collected and sent in one write, instead of one write
                    (plus a 0.2 ms pause) per opcode or 8-byte value;
      read_result : the read requests for WINDOW amplitudes are sent together and the
                    8*WINDOW reply bytes read at once, instead of one round trip per amplitude.
    The FPGA's RX and TX FIFOs hold 256 bytes each (fifo1.v); a window of 16 amplitudes
    needs 48 request bytes and 128 reply bytes.

    Bytes that would not change anything on the board are left out (control_interface.sv:
    WRITE_T2RAM writes rT to BRAM[rA] and INC_A changes only rA, so rT keeps its value):
      - "SEND8T value" when register rT already holds that value. A constant start state
        such as |+> then costs 2 bytes per amplitude (WRITE_T2RAM, INC_A) instead of 11;
      - with keep_cost = True (optimiser runs), the cost diagonal when it is the same as
        the one loaded before: the board keeps it between runs.
    The board ends up with the same memory contents as with the repository's driver."""
    WINDOW = 16
    keep_cost = False

    def load_data(self, H, *rest):
        same_cost = self.keep_cost and np.array_equal(H, getattr(self, "_last_cost", None))
        self._batch, self._rT, self._after, self._value = bytearray(), None, None, None
        self._skip_cost, self._skip_rest = same_cost, False
        try:
            ok = super().load_data(H, *rest)           # the driver builds its usual stream
            self._flush_value()
        finally:
            data, self._batch = bytes(self._batch), None
        self.ser.write(data)
        self.ser.flush()                               # wait until every byte has left the PC
        if ok:
            self._last_cost = np.array(H, copy=True)
        return ok

    def _write_bytes(self, data):
        if getattr(self, "_batch", None) is None:      # not loading: send as the driver does
            return super()._write_bytes(data)
        if self._skip_rest:                            # cost diagonal already on the board
            return
        if self._after == self.OP_SEND8T:              # data = the 8-byte value for rT: hold it until
            self._after, self._value = None, data      # the next command shows how it is used
            return
        if self._value is not None:
            # A bank address is followed by MOV_T2A, a data word by WRITE_T2RAM, so a data word
            # equal to the cost-bank address (|+> at n = 6 is 2^58 in Q3.61) is not mistaken for it.
            if (self._skip_cost and data[0] == self.OP_MOV_T2A
                    and self._value == self.BRAM_COST_FUNC.to_bytes(8, "little")):
                self._skip_rest = True                 # the cost bank is the last part of load_data
                return
            self._flush_value()
        if self._after == self.OP_SEND1T:              # data = the 1-byte value after SEND1T
            self._after = None
        elif data[0] == self.OP_SEND8T:
            self._after = self.OP_SEND8T               # hold the opcode until the value is known
            return
        elif data[0] == self.OP_SEND1T:
            self._after, self._rT = self.OP_SEND1T, None
        elif data[0] not in (self.OP_WRITE_T2RAM, self.OP_INC_A, self.OP_MOV_T2A):
            self._rT = None                            # any other command: assume rT may change
        self._batch += data

    def _flush_value(self):
        """Send a held SEND8T value, unless register rT already holds it."""
        value, self._value = self._value, None
        if value is not None and value != self._rT:
            self._batch += bytes([self.OP_SEND8T]) + value
            self._rT = value

    def read_result(self, n_states):
        result = np.zeros(n_states, dtype=np.complex128)
        for bank, scale in ((self.BRAM_STATE_REAL, 1), (self.BRAM_STATE_IMAG, 1j)):
            self._send_opcode(self.OP_SEND8T)
            self._send_int64(bank)
            self._send_opcode(self.OP_MOV_T2A)
            for start in range(0, n_states, self.WINDOW):
                k = min(self.WINDOW, n_states - start)
                self.ser.write(bytes([self.OP_READ_RAM2U, self.OP_FETCH8U, self.OP_INC_A]) * k)
                d = self.ser.read(8 * k)
                if len(d) != 8 * k:
                    raise RuntimeError(f"expected {8 * k} bytes from the FPGA, got {len(d)}")
                result[start:start + k] += scale * (np.frombuffer(d, dtype="<i8") / float(1 << self.FIX_N))
        # cycle counter, exactly as in FpgaDriver.read_result
        self._send_opcode(self.OP_SEND8T)
        self._send_int64(self.BRAM_COUNTER)
        self._send_opcode(self.OP_MOV_T2A)
        self._send_opcode(self.OP_READ_RAM2U)
        self._send_opcode(self.OP_FETCH8U)
        self.counter = self._fetch_ui64()
        self.ctime = self.counter / self.BoardFrequency
        return result


def model_cycles(t, n, p):
    """Counter predicted from the driver's schedule (sim.fpga.t_params):
    start-up wait + p layers + pipeline drain (L_m) + 14 fixed cycles."""
    wait = t["t_B2GenCost"] + 2 + t["_Lc"]
    layer = t["tb_B2Mixer"] + 2 + n * t["_LPipe"]
    return wait + p * layer + t["_Lm"] + 14


# ---------------------------------------------------------------- 3b. Qiskit Aer (--sim aer)
def aer_objective(G, device):
    """Your Aer objective: get_qaoa_objective(simulator="qiskit") from main/QAOA_objective.py,
    called as q2test.py calls it. Each call binds the angles and transpiles, then times
    run() + result() (printed as qiskit_compute_sec, written to statistics.txt as "qiskit:"),
    and returns -<cut>. Its AerSimulator keeps the Aer defaults (threads, fusion)."""
    import main.QAOA_objective as qo
    if device != "CPU":                 # GPU kept open for later: needs a GPU build of qiskit-aer
        qo.AerSimulator = functools.partial(qo.AerSimulator, device=device)
    return qo.get_qaoa_objective(G=G, simulator="qiskit", parameterization="gamma beta")


def run_aer(obj, T, gammas, betas):
    """One timed Aer evaluation; returns <cut>. Qiskit's circuit applies exp(-i*(gamma_Q/2)*H),
    so the FPGA's gamma is passed as gamma_Q = -2*gamma; beta is the same in both."""
    out = io.StringIO()
    T.clear()
    t0 = time.perf_counter()
    with redirect_stdout(out), chdir(OUT):      # its statistics.txt goes to results/simple/
        value = obj(-2 * np.asarray(gammas), np.asarray(betas))
    T["eval"] = time.perf_counter() - t0
    T["run"] = float(re.search(r"qiskit_compute_sec (\S+) s", out.getvalue()).group(1))
    return -value


def aer_state(G, gammas, betas, device):
    """Final Aer state for the accuracy check: one extra, untimed run of the same circuit,
    built with your get_qaoa_circuit_from_terms (the same gates as the objective's circuit).
    The circuit leaves out the constant term c of the Max-Cut Hamiltonian, so its state
    differs from the FPGA's by the global phase exp(i*c*sum(gamma)), which is put back here."""
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    from main.Base.create_QAOA_circuit import get_qaoa_circuit_from_terms
    terms = get_maxcut_terms(G)
    qc = get_qaoa_circuit_from_terms(G.number_of_nodes(), terms, -2 * np.asarray(gammas), np.asarray(betas))
    backend = AerSimulator(method="statevector", device=device)
    state = np.asarray(backend.run(transpile(qc, backend)).result().get_statevector())
    c = sum(coef for coef, qubits in terms if len(qubits) == 0)
    return state * np.exp(1j * c * np.sum(gammas))


def aer_times(T):
    """Aer's T_run = run() + result(); the rest of the evaluation (binding, transpile) is T_io."""
    return {"T_run_s": T["run"], "t_eval_s": T["eval"], "t_io_s": T["eval"] - T["run"]}


# ---------------------------------------------------------------- 4. results
def compare(state, ref, eps, maxcut):
    d = state - ref
    prob = np.abs(state) ** 2
    out = {"delta_2": np.linalg.norm(d), "delta_inf": np.max(np.abs(d)),
           "mae": 0.5 * (np.mean(np.abs(d.real)) + np.mean(np.abs(d.imag))),   # MAE of fpga_sim_test
           "expectation": np.dot(eps, prob), "expectation_cpp": np.dot(eps, np.abs(ref) ** 2)}
    # Max-Cut only (left empty for the random problem, so every row has the same columns)
    out["approx_ratio"] = out["expectation"] / eps.max() if maxcut else ""
    out["p_best_cut"] = prob[eps == eps.max()].sum() if maxcut else ""
    return out


def append_csv(path, row):
    """Append one row. Only the header line is read, so this stays fast as the file grows
    (reading the whole file every evaluation slowed optimiser runs by 20-40 ms per
    evaluation). If the columns have changed (e.g. a newer version of this script), the
    file is rewritten once with the new columns; old rows keep their values."""
    header = None
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), None)
    columns = list(row) if header is None else header + [k for k in row if k not in header]
    if header == columns:
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=columns, restval="").writerow(row)
        return
    old = []
    if header is not None:
        with open(path, newline="", encoding="utf-8") as f:
            old = list(csv.DictReader(f))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="")
        w.writeheader()
        w.writerows(old)
        w.writerow(row)


def write_hex(path, state):
    """Same format as resultFPGA-NQ*-NP*.txt from fpga_sim_test.py."""
    with open(path, "w") as f:
        for v in np.concatenate([state.real, state.imag]):
            f.write(f"0x{(int(round(v * (1 << 61))) & 0xFFFFFFFFFFFFFFFF):016x}\n")


@functools.lru_cache(maxsize=None)          # computed once per run, not at every evaluation
def code_id():
    """Short fingerprint of the driver, the C++ reference, the Aer objective and this script."""
    h = hashlib.sha256()
    for f in (FPGA_DIR / "Fpga_sim.py", FPGA_DIR / "qaoa_sim.cpp", HERE / "main" / "QAOA_objective.py",
              HERE / "main" / "Base" / "create_QAOA_circuit.py", Path(__file__)):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def row_start(args, n, p):
    graph, aer = args.mode == "graph", args.sim == "aer"
    if aer:
        import qiskit_aer
    return {"time": datetime.datetime.now().isoformat(timespec="seconds"), "note": args.note,
            "code_id": code_id(), "mode": args.mode, "graph": args.graph if graph else "",
            "degree": args.degree if graph and args.graph == "regular" else "",
            "graph_seed": args.graph_seed if graph and args.graph in ("regular", "erdos") else "",
            "NQ": n, "Np": p,
            "io": "" if aer else ("fast" + ("+cost-once" if args.optimise else "")) if args.fast_io else "driver",
            "sim": args.sim, "device": args.device if aer else "",
            "aer_version": qiskit_aer.__version__ if aer else ""}


def times(T, sim):
    t_run = sim.get_duration_time()                 # counter / 320 MHz
    return {"counter": sim.fpga.counter, "T_run_s": t_run, "t_load_s": T["load_data"],
            "t_exec_s": T["execute"], "t_read_s": T["read_result"], "t_eval_s": T["eval"],
            "t_io_s": T["eval"] - t_run}


# ---------------------------------------------------------------- 5. main
def main():
    ap = argparse.ArgumentParser(description="QAOA on the FPGA, checked against qaoa_sim.cpp")
    ap.add_argument("--mode", choices=["random", "graph"], default="graph")
    ap.add_argument("--NQ", type=int, default=8, help="qubits (ignored for --graph file)")
    ap.add_argument("--Np", type=int, default=1, help="QAOA layers")
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--note", default="", help="conditions to record, e.g. latency timer, board, bitstream")
    ap.add_argument("--graph", choices=["regular", "complete", "erdos", "file"], default="regular")
    ap.add_argument("--degree", type=int, default=3)
    ap.add_argument("--edge-prob", type=float, default=0.5)
    ap.add_argument("--graph-seed", type=int, default=1)
    ap.add_argument("--graph-file", default=None)
    ap.add_argument("--angle-seed", type=int, default=7)
    ap.add_argument("--optimise", action="store_true")
    ap.add_argument("--budget", type=int, default=100, help="optimiser evaluations")
    ap.add_argument("--seed", type=int, default=1, help="optimiser starting point")
    ap.add_argument("--verbose", action="store_true", help="show the driver's messages on screen")
    ap.add_argument("--fast-io", action="store_true", help="faster transfer to and from the board (FastIODriver)")
    ap.add_argument("--sim", choices=["fpga", "aer"], default="fpga", help="aer: Qiskit Aer via QAOA_objective.py")
    ap.add_argument("--device", choices=["CPU", "GPU"], default="CPU", help="Aer device (GPU kept open, untested)")
    args = ap.parse_args()

    eps, sv0, gammas, betas, G = make_problem(args)
    n, p, maxcut, aer = len(eps).bit_length() - 1, args.Np, G is not None, args.sim == "aer"
    if aer and not maxcut:
        raise SystemExit("--sim aer needs --mode graph: QAOA_objective.py builds the Aer circuit from Max-Cut terms")
    if np.max(np.abs(eps)) >= 512:
        raise SystemExit("max|eps| >= 512 does not fit the driver's Q5.59 scaling")
    if n > 18 and not aer:
        raise SystemExit("the current bitstream holds at most 18 qubits")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = OUT / f"{stamp}_{args.mode}_n{n}_p{p}{'_opt' if args.optimise else ''}{'_aer' if aer else ''}"
    folder.mkdir(parents=True)
    cpp_exe()                                   # compile the C++ reference now, not inside a timed loop
    global DRIVER_LOG
    if not args.verbose:
        DRIVER_LOG = open(folder / "driver.log", "w", encoding="utf-8")
    what = f"Max-Cut, {args.graph} graph" if maxcut else "random problem (fpga_sim_test)"
    where = f"Aer {args.device}" if aer else "FPGA" + (", fast I/O" if args.fast_io else "")
    print(f"\n=== {what}, n={n}, p={p}, {where}{', COBYLA' if args.optimise else ''}"
          f"  ->  results/simple/{folder.name}")

    with driver_messages():
        sim = FPGASimulator(n_qubits=n, costs=eps, fpga_config={"port": args.port, "baudrate": 115200, "max_qubits": 20})
        if args.fast_io:
            sim.fpga = FastIODriver(fpga_config=sim.fpga_config)
        T = {}
        add_timers(sim.fpga, T)
        if not aer:                             # Aer needs no board; sim is then used only for the C++ scaling
            sim.connected = sim.fpga.connect()  # connect once, outside the timed evaluations
    if not aer and not sim.connected:
        raise SystemExit(f"could not connect to the FPGA on {args.port} (see {folder.name}/driver.log)")
    obj = aer_objective(G, args.device) if aer else None

    try:
        if args.optimise:
            optimise(args, sim, T, eps, sv0, n, p, maxcut, folder, obj)
        else:
            ref, _ = cpp_reference(sim, eps, sv0, gammas, betas, folder)
            if aer:
                state = aer_state(G, gammas, betas, args.device)     # untimed, for the accuracy check
                with redirect_stdout(io.StringIO()), chdir(folder):   # one untimed warm-up call (the
                    obj(-2 * gammas, betas)                           # first call is slower); not logged
            for r in range(args.repeats):
                if aer:
                    run_aer(obj, T, gammas, betas)
                    tm = aer_times(T)
                else:
                    state = run_fpga(sim, T, gammas, betas, sv0)
                    tm = {**times(T, sim), "model_cycles": model_cycles(sim.fpga.t_params, n, p)}
                row = row_start(args, n, p)
                row.update(repeat=r, **tm, **compare(state, ref, eps, maxcut), gammas=list(gammas),
                           betas=list(betas), folder=folder.name)
                append_csv(OUT / "runs.csv", row)
                if not aer:
                    write_hex(folder / f"resultFPGA-NQ{n}-NP{p}-r{r}.txt", state)
                    with open(OUT / "statistics.txt", "a") as f:      # old format, for the plot scripts
                        f.write("---------------------------------------\nsummary of the computation \n"
                                "---------------------------------------\n"
                                f"FPGA time: {row['T_run_s']}\nNQ: {n}\nNP: {p}\nNS: {1 << n}\nMAE: {row['mae']:.4e}\n")
                show_run(row, r, args.repeats, maxcut)
            np.savez(folder / "data.npz", eps=eps, sv0=sv0, gammas=gammas, betas=betas,
                     **{"state_aer" if aer else "state_fpga": state}, state_cpp=ref,
                     edges=np.array(list(G.edges())) if maxcut else np.zeros((0, 2)))
    finally:
        with driver_messages():
            if not aer:
                sim.fpga.disconnect()
        if DRIVER_LOG:
            DRIVER_LOG.close()


def show_run(row, r, repeats, maxcut):
    """One readable block per evaluation (all values are also in runs.csv)."""
    print(f"  repeat {r + 1}/{repeats}")
    if row["sim"] == "aer":
        print(f"    time      Aer {1e3 * row['T_run_s']:.4f} ms (run + result, {row['device']}); "
              f"{row['t_eval_s']:.3f} s in total with binding and transpile")
    else:
        ok = "matches the model" if row["counter"] == row["model_cycles"] else f"MODEL SAYS {row['model_cycles']:,}"
        print(f"    counter   {row['counter']:,} cycles ({ok}) = {1e3 * row['T_run_s']:.4f} ms on the FPGA")
        print(f"    time      {row['t_eval_s']:.2f} s in total: load {row['t_load_s']:.2f} s, "
              f"run {row['t_exec_s']:.2f} s, read back {row['t_read_s']:.2f} s")
    print(f"    accuracy  delta_2 = {row['delta_2']:.2e}, delta_inf = {row['delta_inf']:.2e} "
          f"({row['sim'].upper()} vs C++)")
    if maxcut:
        print(f"    Max-Cut   <cut> = {row['expectation']:.4f}, approximation ratio = {row['approx_ratio']:.4f}")


def optimise(args, sim, T, eps, sv0, n, p, maxcut, folder, obj=None):
    """COBYLA (as in q2test.py) with the FPGA (or Aer, when obj is given) computing every
    evaluation; each point is also computed on the C++ reference to show both give the same energy."""
    sim.fpga.keep_cost = True        # with --fast-io: send the cost diagonal only once
    rng = np.random.default_rng(args.seed)
    x0 = np.concatenate([rng.uniform(0, np.pi, p), rng.uniform(0, np.pi / 2, p)])
    log = []
    t_start = time.perf_counter()

    def objective(x):
        if obj is None:
            state = run_fpga(sim, T, x[:p], x[p:], sv0)
            E, tm = float(np.dot(eps, np.abs(state) ** 2)), times(T, sim)
        else:
            E, tm = float(run_aer(obj, T, x[:p], x[p:])), aer_times(T)
        ref, t_cpp = cpp_reference(sim, eps, sv0, x[:p], x[p:], folder)
        E_cpp = float(np.dot(eps, np.abs(ref) ** 2))
        row = row_start(args, n, p)
        row.update(seed=args.seed, eval=len(log), **tm, t_cpp_s=t_cpp, expectation=E,
                   expectation_cpp=E_cpp, abs_diff=abs(E - E_cpp),
                   approx_ratio=E / eps.max() if maxcut else "", gammas=list(x[:p]), betas=list(x[p:]))
        append_csv(OUT / "optimise.csv", row)
        log.append(row)
        if len(log) == 1 or len(log) % 10 == 0:                     # progress every 10 evaluations
            print(f"  eval {len(log):3d}: <cost> = {E:.6f} (C++ {E_cpp:.6f}), {row['t_eval_s']:.2f} s")
        return -E if maxcut else E        # Max-Cut is maximised

    res = minimize(objective, x0, method="COBYLA", options={"maxiter": args.budget})
    wall = time.perf_counter() - t_start
    best = max(log, key=lambda r: r["expectation"]) if maxcut else min(log, key=lambda r: r["expectation"])
    sum_eval = sum(r["t_eval_s"] for r in log)
    sum_cpp = sum(r["t_cpp_s"] for r in log)
    summary = row_start(args, n, p)
    summary.update(seed=args.seed, budget=args.budget, nfev=len(log), message=str(res.message),
                   best_expectation=best["expectation"], best_approx_ratio=best["approx_ratio"],
                   best_eval=best["eval"], wall_s=wall, sum_t_eval_s=sum_eval,
                   sum_T_run_s=sum(r["T_run_s"] for r in log), sum_t_cpp_s=sum_cpp,
                   t_optimiser_s=wall - sum_eval - sum_cpp,          # time spent in COBYLA itself
                   max_abs_diff_fpga_cpp=max(r["abs_diff"] for r in log), folder=folder.name)
    append_csv(OUT / "optimise_summary.csv", summary)
    ratio = f", approximation ratio {best['approx_ratio']:.4f}" if maxcut else ""
    print(f"  done: {len(log)} evaluations in {wall / 60:.1f} min; best <cost> = {best['expectation']:.6f}"
          f" at evaluation {best['eval'] + 1}{ratio}")
    print(f"        {args.sim.upper()} and C++ agree to {summary['max_abs_diff_fpga_cpp']:.1e} at every point; "
          f"time in COBYLA itself {summary['t_optimiser_s']:.2f} s")


if __name__ == "__main__":
    main()