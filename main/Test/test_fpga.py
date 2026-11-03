"""


    run_parity_check(FpgaDriver, NQ=5, Np=2)

It injects a fake serial port into the driver (so connect() is bypassed),
runs the three driver methods, captures every byte written, builds an
INDEPENDENT reference stream from all_test.py's logic, and diffs them.
On mismatch it prints the first differing opcode with context from both sides.
"""

from  ..Base.Simulators.FPGA.Fpga_sim import FpgaDriver

import numpy as np


# --------------------------------------------------------------------------
# Opcode table (must match NEW_smachine.sv / all_test.py)
# --------------------------------------------------------------------------
OP_SEND1T, OP_SEND8T, OP_MOV_T2A = 1, 2, 3
OP_MOV_S2U = 8
OP_FETCH1U, OP_FETCH8U = 60, 61
OP_INC_A = 84
OP_WRITE_T2RAM, OP_READ_RAM2U = 111, 112
OP_SEND_CMD, OP_WRITE_T2_AG = 118, 119
qa_WAIT, qa_RUN = 1, 2

BRAM_PARAMS     = 0x0800_0000_0000_0000
BRAM_STATE_REAL = 0x1000_0000_0000_0000
BRAM_STATE_IMAG = 0x2000_0000_0000_0000
BRAM_COST_FUNC  = 0x0400_0000_0000_0000

_OPNAMES = {
    1: "SEND1T", 2: "SEND8T", 3: "MOV_T2A", 4: "MOV_T2B", 5: "MOV_A2U",
    6: "MOV_A2B", 7: "MOV_Info2U", 8: "MOV_S2U", 9: "MOV_T2P",
    60: "FETCH1U", 61: "FETCH8U", 80: "ADD_B2A", 81: "MUL_B2A",
    84: "INC_A", 111: "WRITE_T2RAM", 112: "READ_RAM2U",
    118: "SEND_CMD", 119: "WRITE_T2_AG",
}


# --------------------------------------------------------------------------
# Fake serial port: records TX, supplies canned RX
# --------------------------------------------------------------------------
class MockSerial:
    def __init__(self):
        self.tx = bytearray()

    def write(self, b):
        self.tx.extend(bytes(b))

    def read(self, n):
        # 1-byte read == status poll -> return qa_WAIT so the loop breaks once.
        # 8-byte read == result fetch -> return zeros (content irrelevant to TX).
        return bytes([qa_WAIT]) if n == 1 else bytes(n)

    def reset_input_buffer(self):  pass
    def reset_output_buffer(self): pass
    def close(self):               pass


# --------------------------------------------------------------------------
# Encoding helpers (match all_test.py exactly)
# --------------------------------------------------------------------------
_FIX_N = 61
_FIX_P = 64


def _op(x):
    return bytes([x])


def _u64(v):
    # addresses + AG register values: positive, < 2**63 -> identical under
    # signed or unsigned, and identical to driver's masked unsigned encoding.
    return (v & ((1 << 64) - 1)).to_bytes(8, "little")


def _fx(x):
    # Q3.61 fixed-point, saturating (all_test.py float_to_fixed) -- identical to
    # the driver's _send_fixed for in-range values.
    scaled = int(round(x * (1 << _FIX_N)))
    lo, hi = -(1 << (_FIX_P - 1)), (1 << (_FIX_P - 1)) - 1
    scaled = max(lo, min(hi, scaled))
    return scaled.to_bytes(8, "little", signed=True)


def _mask64(a):
    return (1 << 64) - 1 if a >= 64 else (1 << a) - 1


# --------------------------------------------------------------------------
# Timing model (independent copy of all_test.py lines 79-136)
# --------------------------------------------------------------------------
def _timing(NQ, Np):
    LP_BRAM_A, LP_BRAM_D, LP_GEN_COST = 2, 1, 2
    LP_MIXER_IN, LP_MIXER_OUT = 1, 1
    L_BRAM_R = L_BRAM_W = LP_BRAM_A + LP_BRAM_D + 2
    N3 = 1 + 10 + 2 + 1 + 1 + 1
    gcN0, gcN1 = 10, 170
    gcPipe = 1 + gcN0 + 1 + gcN1 + 1
    Lc = 1 + gcPipe + 1 + L_BRAM_R + 2 * LP_GEN_COST
    Lm = 1 + N3 + 1 + L_BRAM_R + L_BRAM_W + 1 + LP_MIXER_IN + LP_MIXER_OUT
    LInit = 24
    NS = 1 << NQ
    LPipe = NS
    tl = Lm + NS // 2 + NS % 2
    if tl >= NS:
        LPipe = tl
    DVTc = Lc // LPipe + 1
    tGenCost = DVTc * LPipe - Lc
    if tGenCost < LInit:
        tGenCost += LPipe
    tbGenCost = LPipe * (NQ + 1) - Lc
    t_Mixer = LPipe
    if tbGenCost < LInit:
        t_Mixer = LPipe + LInit - tbGenCost
        tbGenCost = LInit
    t_Compute = t_Mixer + LPipe * NQ + Lm
    return dict(
        t_L2Addr=NS - 2, t_L2Pipe=LPipe - 2, t_L2PipeGC=Lc - 2,
        tb_B2GenCost=tbGenCost - 2, t_B2GenCost=tGenCost - 2,
        nPLayer=Np, L1Qbit=NQ - 1, AddrMask=_mask64(NQ - 1),
        tb_B2Mixer=t_Mixer - 2, t_L2Compute=t_Compute,
    )


# --------------------------------------------------------------------------
# Reference TX stream (faithful to all_test.py data_array + transmit loop)
# --------------------------------------------------------------------------
def build_reference(NQ, Np, H, sv0_re, sv0_im, betas, gammas):
    NS = 1 << NQ
    t = _timing(NQ, Np)
    s = bytearray()

    # 1) park in WAIT
    s += _op(OP_SEND1T) + _op(qa_WAIT) + _op(OP_SEND_CMD)

    # 2) addr_gen config -- all_test.py order (selector, value)
    ag = [
        (0, t["t_L2Addr"]), (3, t["t_L2Pipe"]), (1, t["t_L2PipeGC"]),
        (2, t["tb_B2GenCost"]), (7, t["t_B2GenCost"]), (4, t["nPLayer"]),
        (5, t["L1Qbit"]), (6, t["AddrMask"]), (8, t["tb_B2Mixer"]),
        (9, t["t_L2Compute"]),
    ]
    for sel, val in ag:
        s += _op(OP_SEND1T) + _op(sel) + _op(OP_MOV_T2A)
        s += _op(OP_SEND8T) + _u64(val) + _op(OP_WRITE_T2_AG)

    # 3) params: p+1 triples, redundant first cos/sin, trailing gamma=-1
    cosb = np.cos(np.asarray(betas, float))
    sinb = np.sin(np.asarray(betas, float))
    cosb_w = [float(cosb[0])] + [float(c) for c in cosb]
    sinb_w = [float(sinb[0])] + [float(c) for c in sinb]
    gam_w = [float(g) for g in gammas] + [-1.0]
    s += _op(OP_SEND8T) + _u64(BRAM_PARAMS) + _op(OP_MOV_T2A)
    for k in range(Np + 1):
        for v in (cosb_w[k], sinb_w[k], gam_w[k]):
            s += _op(OP_SEND8T) + _fx(v) + _op(OP_WRITE_T2RAM) + _op(OP_INC_A)

    # 4/5/6) state real, state imag, cost
    for bank, vals in ((BRAM_STATE_REAL, sv0_re),
                       (BRAM_STATE_IMAG, sv0_im),
                       (BRAM_COST_FUNC, H)):
        s += _op(OP_SEND8T) + _u64(bank) + _op(OP_MOV_T2A)
        for i in range(NS):
            s += _op(OP_SEND8T) + _fx(float(vals[i])) + _op(OP_WRITE_T2RAM) + _op(OP_INC_A)

    # 7) run
    s += _op(OP_SEND1T) + _op(qa_RUN) + _op(OP_SEND_CMD)
    # 8) one status poll (HOST_WAIT, breaks on first qa_WAIT)
    s += _op(OP_MOV_S2U) + _op(OP_FETCH1U)
    # 9) back to WAIT
    s += _op(OP_SEND1T) + _op(qa_WAIT) + _op(OP_SEND_CMD)

    # 10/11) read back real, imag
    for bank in (BRAM_STATE_REAL, BRAM_STATE_IMAG):
        s += _op(OP_SEND8T) + _u64(bank) + _op(OP_MOV_T2A)
        for i in range(NS):
            s += _op(OP_READ_RAM2U) + _op(OP_FETCH8U) + _op(OP_INC_A)

    return bytes(s)


# --------------------------------------------------------------------------
# Decoder for human-readable diffs
# --------------------------------------------------------------------------
def decode(stream):
    """Return list of (offset, text). Tracks SEND8T/SEND1T payloads."""
    out, i, n = [], 0, len(stream)
    while i < n:
        op = stream[i]
        name = _OPNAMES.get(op, f"?{op}")
        if op == OP_SEND8T and i + 9 <= n:
            payload = stream[i + 1:i + 9]
            sv = int.from_bytes(payload, "little", signed=True)
            out.append((i, f"SEND8T {payload.hex()}  (int={sv}, fx={sv / (1 << _FIX_N):+.6g})"))
            i += 9
        elif op == OP_SEND1T and i + 2 <= n:
            out.append((i, f"SEND1T 0x{stream[i + 1]:02x} ({stream[i + 1]})"))
            i += 2
        else:
            out.append((i, name))
            i += 1
    return out


def _report_mismatch(actual, reference):
    # first differing byte
    m = min(len(actual), len(reference))
    first = next((k for k in range(m) if actual[k] != reference[k]), m)
    print(f"  lengths: driver={len(actual)}  reference={len(reference)}")
    print(f"  first differing byte at offset {first}")
    da, dr = decode(actual), decode(reference)

    def window(dec):
        idx = next((j for j, (off, _) in enumerate(dec) if off >= first), len(dec) - 1)
        return dec[max(0, idx - 3): idx + 4]

    print("\n  --- DRIVER (around first diff) ---")
    for off, txt in window(da):
        print(f"    @{off:5d}  {txt}")
    print("\n  --- REFERENCE (around first diff) ---")
    for off, txt in window(dr):
        print(f"    @{off:5d}  {txt}")


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def run_parity_check(FpgaDriver, NQ=5, Np=2, seed=12345, verbose=True):
    rng = np.random.default_rng(seed)
    NS = 1 << NQ

    # Deterministic, in-range inputs (so neither side saturates/raises).
    H = rng.uniform(-1.0, 1.0, NS)
    sv0 = rng.normal(size=NS) + 1j * rng.normal(size=NS)
    sv0 /= np.linalg.norm(sv0)
    betas = rng.uniform(-np.pi / 4, np.pi / 4, Np)
    gammas = rng.uniform(-1.0, 1.0, Np)
    sv0_re = [sv0[i].real for i in range(NS)]
    sv0_im = [sv0[i].imag for i in range(NS)]
    cosb = np.cos(betas)
    sinb = np.sin(betas)

    # Build the driver and inject the fake port (bypass connect()).
    drv = FpgaDriver({"port": "mock", "baudrate": 115200, "timeout": 1})
    drv.ser = MockSerial()
    drv.connected = True

    drv.load_data(H, sv0_re, sv0_im, gammas, betas, cosb, sinb)
    drv.execute(Np)
    drv.read_result(NS)
    actual = bytes(drv.ser.tx)

    reference = build_reference(NQ, Np, H, sv0_re, sv0_im, betas, gammas)

    ok = actual == reference
    if verbose:
        print(f"[parity] NQ={NQ} Np={Np}  driver={len(actual)}B  reference={len(reference)}B")
        if ok:
            print("[parity] PASS - byte-for-byte identical to all_test.py")
        else:
            print("[parity] FAIL")
            _report_mismatch(actual, reference)
    return ok


if __name__ == "__main__":
    print("Import this module and call run_parity_check(FpgaDriver).")
    run_parity_check(FpgaDriver, NQ=5, Np=2)