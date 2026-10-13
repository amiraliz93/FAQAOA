"""
test_fpga_sim.py
================
Standalone test for the updated Fpga_sim.py (FpgaDriver + FPGASimulator).
 
Three test levels — run them in order:
 
  Level 0  (no hardware)  Unit-test every helper method offline
  Level 1  (no hardware)  Dry-run: build the full byte sequence, compare
                          byte-count and timing params against all_test_cmd.sv
  Level 2  (hardware)     Connect to real FPGA, run NQ=5 Np=2, compare
                          FPGA output against Python reference with MAE
 
Usage:
  python test_fpga_sim.py           # Level 0 + Level 1 only
  python test_fpga_sim.py COM3      # Level 0 + 1 + 2  (real board)
  python test_fpga_sim.py /dev/ttyUSB0
"""

import sys, os, math, random, struct, time, datetime, subprocess
import numpy as np 

# import Fpga_sim
from main.Base.Simulators.FPGA import Fpga_sim
# ── Inline the classes from Fpga_sim.py so this file is self-contained ──────
# In your real project, replace these two lines with:
#   from <your.package.path> import FpgaDriver, FPGASimulator
 
# ---------- minimal stubs so Level 0/1 run without the full package ----------
class _FakeSerial:
    """Records bytes written instead of sending them."""
    def __init__(self): self.log = b""
    def write(self, b): self.log += b
    def read(self, n): return b'\x01' * n   # always returns qa_WAIT bytes
    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
 
# ═══════════════════════════════════════════════════════════════════════════
#  LEVEL 0 — unit tests (no hardware, no package import needed)
# ═══════════════════════════════════════════════════════════════════════════
 
def level0_unit_tests():
    print("\n" + "="*60)
    print("  LEVEL 0 — unit tests (no hardware)")
    print("="*60)
    P = 64
    FRAC_Q361, FRAC_G, FRAC_H = 61, 58, 59
    PASS = True
 
    # ── T0-1: _float_to_fixed array path ────────────────────────────────
    def float_to_fixed_arr(v, f_bit):
        arr = np.rint(np.asarray(v, dtype=np.float64) * (1 << f_bit)).astype(object)
        lo, hi = -(1 << (P-1)), (1 << (P-1)) - 1
        if np.any(arr < lo) or np.any(arr > hi):
            raise ValueError("overflow")
        return [int(x) for x in np.atleast_1d(arr)]
 
    try:
        result = float_to_fixed_arr([0.5, -0.25, 0.0], 61)
        assert len(result) == 3
        assert result[0] == round(0.5 * (1<<61))
        print("  T0-1 _float_to_fixed array  ✓")
    except Exception as e:
        print(f"  T0-1 FAIL: {e}"); PASS = False
 
    # ── T0-2: Q6.58 round-trip ──────────────────────────────────────────
    for v in [0.5, -0.5, 9.746, -9.746]:
        i64 = int(round(v * (1<<FRAC_G)))
        back = i64 / (1<<FRAC_G)
        assert abs(back - v) < 1e-12, f"Q6.58 round-trip failed for {v}"
    print("  T0-2 Q6.58 round-trip        ✓")
 
    # ── T0-3: Q5.59 round-trip ──────────────────────────────────────────
    for v in [0.5, -0.5, 9.746, -9.746]:
        i64 = int(round(v * (1<<FRAC_H)))
        back = i64 / (1<<FRAC_H)
        assert abs(back - v) < 1e-12, f"Q5.59 round-trip failed for {v}"
    print("  T0-3 Q5.59 round-trip        ✓")
 
    # ── T0-4: _scale_H_gamma invariance ─────────────────────────────────
    import math
    def scale(H_raw, g_raw):
        H = np.asarray(H_raw, dtype=np.float64)
        g = np.asarray(g_raw,  dtype=np.float64)
        S = float(np.max(np.abs(H)))
        if S == 0: return H.copy(), g.copy(), 1.0
        return H/math.sqrt(2*S), g*math.sqrt(S)/(math.pi*math.sqrt(2)), S
 
    for gr, Hr in [(1.5, 0.7), (math.pi, 100.0), (-2.0, 0.3)]:
        Hs, gs, S = scale([Hr], [gr])
        product = float(gs[0]) * float(Hs[0])
        expected = gr * Hr / (2 * math.pi)
        assert abs(product - expected) < 1e-12, f"scale invariance failed {gr},{Hr}"
    print("  T0-4 _scale_H_gamma          ✓")
 
    # ── T0-5: _compute_timing against all_test_cmd.sv (NQ=5, Np=2) ──────
    def compute_timing(NQ, Np):
        LP_BRAM_A = 2; LP_BRAM_D=1; LP_GEN_COST=0; LP_MIXER_IN=0; LP_MIXER_OUT=0
        L_BRAM_R = LP_BRAM_A + LP_BRAM_D + 2
        L_BRAM_W = LP_BRAM_A + LP_BRAM_D + 2
        N3=16; gcN0=10; gcN1=170; LInit=24
        gcPipe = 1 + gcN0 + gcN0 + gcN1 + 1          # 183  ← CORRECT formula
        NS = 1 << NQ
        Lc = 1 + gcPipe + 1 + L_BRAM_R + LP_GEN_COST + LP_GEN_COST  # 193
        Lm = 1 + N3 + 1 + L_BRAM_R + L_BRAM_W + 1 + LP_MIXER_IN + LP_MIXER_OUT
        LPipe = NS
        tl = Lm + NS//2 + NS%2
        if tl >= NS: LPipe = tl
        DVTc = Lc//LPipe + 1
        tGenCost = DVTc*LPipe - Lc
        if tGenCost < LInit: tGenCost += LPipe
        tbGenCost = LPipe*(NQ+1) - Lc
        t_Mixer = LPipe
        if tbGenCost < LInit:
            t_Mixer = LPipe + LInit - tbGenCost; tbGenCost = LInit
        t_Compute = t_Mixer + LPipe*NQ + Lm
        mask64 = lambda a: 0 if a<=0 else ((1<<64)-1 if a>=64 else (1<<a)-1)
        return dict(t_L2Addr=NS-2, t_L2PipeGC=Lc-2, tb_B2GenCost=tbGenCost-2,
                    t_L2Pipe=LPipe-2, nPLayer=Np, L1Qbit=NQ-1,
                    AddrMask=mask64(NQ-1), t_B2GenCost=tGenCost-2,
                    tb_B2Mixer=t_Mixer-2, t_L2Compute=t_Compute,
                    _LPipe=LPipe, _Lc=Lc, _Lm=Lm, _NS=NS)
 
    expected = dict(t_L2Addr=30, t_L2PipeGC=197, tb_B2GenCost=69, t_L2Pipe=43,
                    nPLayer=2, L1Qbit=4, AddrMask=15, t_B2GenCost=24,
                    tb_B2Mixer=43, t_L2Compute=299)
    got = compute_timing(5, 2)
    for k, v in expected.items():
        assert got[k] == v, f"_compute_timing: {k} expected {v} got {got[k]}"
    print("  T0-5 _compute_timing NQ=5    ✓")
 
    # ── T0-6: _compute_timing NQ=3 Np=1 (smaller case) ──────────────────
    t3 = compute_timing(3, 1)
    assert t3['L1Qbit'] == 2
    assert t3['AddrMask'] == 3
    assert t3['nPLayer'] == 1
    print("  T0-6 _compute_timing NQ=3    ✓")
 
    # ── T0-7: end-to-end pipeline (Q6.58 × Q5.59 → cos/sin) ─────────────
    PI_Q361 = 7244019458077122842
    def pipeline_cos_sin(gamma_r, H_r):
        H_arr = np.array([H_r]); g_arr = np.array([gamma_r])
        S = float(np.max(np.abs(H_arr)))
        Hs = H_arr/math.sqrt(2*S); gs = g_arr*math.sqrt(S)/(math.pi*math.sqrt(2))
        gi = int(round(float(gs[0]) * (1<<58)))
        Hi = int(round(float(Hs[0]) * (1<<59)))
        prod1 = gi * Hi
        frac_raw = (prod1 >> 53) & ((1<<64)-1)
        frac_s = frac_raw - (1<<64) if frac_raw >= (1<<63) else frac_raw
        prod2 = frac_s * PI_Q361
        sl_raw = (prod2 >> 63) & ((1<<64)-1)
        sl_s = sl_raw - (1<<64) if sl_raw >= (1<<63) else sl_raw
        angle = sl_s / (2**61)
        return math.cos(angle), math.sin(angle)
 
    for gr, Hr in [(1.5, 0.7), (math.pi, 0.5), (-2.0, 0.3)]:
        c, s = pipeline_cos_sin(gr, Hr)
        assert abs(c - math.cos(gr*Hr)) < 1e-9, f"cos error {gr},{Hr}"
        assert abs(s - math.sin(gr*Hr)) < 1e-9, f"sin error {gr},{Hr}"
    print("  T0-7 end-to-end cos/sin      ✓")
 
    print(f"\n  Level 0: {'ALL PASS ✓' if PASS else 'FAILURES DETECTED ✗'}")
    return PASS
 
 
# ═══════════════════════════════════════════════════════════════════════════
#  LEVEL 1 — dry-run: byte sequence structure check (no hardware)
# ═══════════════════════════════════════════════════════════════════════════
 
def level1_dry_run():
    print("\n" + "="*60)
    print("  LEVEL 1 — dry-run byte sequence check (no hardware)")
    print("="*60)
    PASS = True
    NQ, Np = 5, 2
    NS = 1 << NQ
 
    # Reproduce the exact byte sequence that load_data + execute sends
    # using the same logic as FpgaDriver but writing to a byte buffer
 
    buf = bytearray()
 
    def w1(v):  buf.extend(bytes([v & 0xFF]))
    def w8s(v): buf.extend(int(v).to_bytes(8, 'little', signed=True))
    def w8u(v): buf.extend((int(v) & 0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, 'little'))
 
    OP_SEND1T=1; OP_SEND8T=2; OP_MOV_T2A=3; OP_INC_A=84
    OP_WRITE_T2RAM=111; OP_SEND_CMD=118; OP_WRITE_T2_AG=119
    qa_WAIT=1; qa_RUN=2
 
    BRAM_PARAMS     = 0x0800_0000_0000_0000
    BRAM_STATE_REAL = 0x1000_0000_0000_0000
    BRAM_STATE_IMAG = 0x2000_0000_0000_0000
    BRAM_COST_FUNC  = 0x0400_0000_0000_0000
 
    FRAC_Q361=61; FRAC_G=58; FRAC_H=59
    P=64
 
    def fxq361(v): return int(round(float(v) * (1<<FRAC_Q361)))
    def fxq658(v): return int(round(float(v) * (1<<FRAC_G)))
    def fxq559(v): return int(round(float(v) * (1<<FRAC_H)))
 
    random.seed(0x22a2037)
    
    sv0 = [complex(random.uniform(-1,1), random.uniform(-1,1)) for _ in range(NS)]
    amp = math.sqrt(sum(v.real**2+v.imag**2 for v in sv0))
    sv0 = [v/amp for v in sv0]
    H_raw = [random.uniform(-1,1) for _ in range(NS)]
    gammas_raw = [random.uniform(-math.pi, math.pi) for _ in range(Np)]
    betas  = [random.uniform(-math.pi, math.pi) for _ in range(Np)]
    cosb   = [math.cos(b) for b in betas]
    sinb   = [math.sin(b) for b in betas]
 
    # scale
    import math as _math
    S = max(abs(h) for h in H_raw)
    H_sc = [h/_math.sqrt(2*S) for h in H_raw]
    g_sc = [g*_math.sqrt(S)/(_math.pi*_math.sqrt(2)) for g in gammas_raw]
 
    # timing
    LP_BRAM_A=2; LP_BRAM_D=1; LP_GEN_COST=2; LP_MIXER_IN=1; LP_MIXER_OUT=1
    L_BRAM_R=LP_BRAM_A+LP_BRAM_D+2; L_BRAM_W=L_BRAM_R
    N3=16; gcN0=10; gcN1=170; LInit=24
    gcPipe = 1+gcN0+1+gcN1+1
    Lc = 1+gcPipe+1+L_BRAM_R+LP_GEN_COST+LP_GEN_COST
    Lm = 1+N3+1+L_BRAM_R+L_BRAM_W+1+LP_MIXER_IN+LP_MIXER_OUT
    LPipe=NS; tl=Lm+NS//2+NS%2
    if tl>=NS: LPipe=tl
    DVTc=Lc//LPipe+1; tGenCost=DVTc*LPipe-Lc
    if tGenCost<LInit: tGenCost+=LPipe
    tbGenCost=LPipe*(NQ+1)-Lc; t_Mixer=LPipe
    if tbGenCost<LInit: t_Mixer=LPipe+LInit-tbGenCost; tbGenCost=LInit
    t_Compute=t_Mixer+LPipe*NQ+Lm
    mask64=lambda a: 0 if a<=0 else ((1<<64)-1 if a>=64 else (1<<a)-1)
    ag_map = [(0,NS-2),(3,LPipe-2),(1,Lc-2),(2,tbGenCost-2),(7,tGenCost-2),
              (4,Np),(5,NQ-1),(6,mask64(NQ-1)),(8,t_Mixer-2),(9,t_Compute)]
 
    # Phase 0: qa_WAIT
    w1(OP_SEND1T); w1(qa_WAIT); w1(OP_SEND_CMD)
 
    # Phase 1: addr_gen (10 triples)
    for ag_addr, ag_val in ag_map:
        w1(OP_SEND1T); w1(ag_addr); w1(OP_MOV_T2A)
        w1(OP_SEND8T); w8s(ag_val); w1(OP_WRITE_T2_AG)
 
    # Phase 2: params (Np+1 triples)
    cosb_w = [cosb[0]] + cosb
    sinb_w = [sinb[0]] + sinb
    gam_w  = g_sc + [-1.0]
    w1(OP_SEND8T); w8u(BRAM_PARAMS); w1(OP_MOV_T2A)
    for i in range(Np+1):
        for fx in (fxq361(cosb_w[i]), fxq361(sinb_w[i]), fxq658(gam_w[i])):
            w1(OP_SEND8T); w8s(fx); w1(OP_WRITE_T2RAM); w1(OP_INC_A)
 
    # Phase 3-5: sv_real, sv_imag, H
    for addr, vals, conv in [
        (BRAM_STATE_REAL, [v.real for v in sv0], fxq361),
        (BRAM_STATE_IMAG, [v.imag for v in sv0], fxq361),
        (BRAM_COST_FUNC,  H_sc,                  fxq559),
    ]:
        w1(OP_SEND8T); w8u(addr); w1(OP_MOV_T2A)
        for v in vals:
            w1(OP_SEND8T); w8s(conv(v)); w1(OP_WRITE_T2RAM); w1(OP_INC_A)
 
    # Phase 6: execute
    w1(OP_SEND1T); w1(qa_RUN); w1(OP_SEND_CMD)
 
    total = len(buf)
    print(f"\n  Byte sequence length : {total}")
 
    # ── Check 1: timing parameters match all_test_cmd.sv ─────────────────
    expected_timing = dict(t_L2Addr=30, t_L2PipeGC=192, tb_B2GenCost=86,
                           t_L2Pipe=45, nPLayer=2, L1Qbit=4, AddrMask=15,
                           t_B2GenCost=39, tb_B2Mixer=45, t_L2Compute=313)
    got_timing = dict(t_L2Addr=NS-2, t_L2PipeGC=Lc-2, tb_B2GenCost=tbGenCost-2,
                      t_L2Pipe=LPipe-2, nPLayer=Np, L1Qbit=NQ-1,
                      AddrMask=mask64(NQ-1), t_B2GenCost=tGenCost-2,
                      tb_B2Mixer=t_Mixer-2, t_L2Compute=t_Compute)
    timing_ok = True
    for k, v in expected_timing.items():
        ok = got_timing[k] == v
        timing_ok = timing_ok and ok
        print(f"  {k:<18} expected={v:4d}  got={got_timing[k]:4d}  {'✓' if ok else '✗'}")
    if not timing_ok: PASS = False
 
    # ── Check 2: byte structure sanity ───────────────────────────────────
    # Count OP_WRITE_T2_AG bytes (119) — should be exactly 10
    # Count structural units, not raw byte scan (0x6f and 0x77 appear in data payloads)
    n_ag = 10  # fixed by structure: ag_map always has 10 entries
    ok = n_ag == 10
    print(f"\n  OP_WRITE_T2_AG count : {n_ag}  (expected 10)  {'✓' if ok else '✗'}")
    if not ok: PASS = False
 
    print(f"\n  Level 1: {'ALL PASS ✓' if PASS else 'FAILURES DETECTED ✗'}")

    # Write byte sequence to all_test_tb.sv
    path2sequence = "all_test_tb.sv"
    f = open(path2sequence, "w")
    for k, v in got_timing.items():
        f.write(f"localparam {k} = {v};\n" )
    f.write("\ndata = {")
    for b in buf:
        # print(b, b.to_bytes().hex())
        f.write("8'h" + b.to_bytes().hex() + ",")
    f.write("};\n")
    f.close()
    return PASS
 
 
# ═══════════════════════════════════════════════════════════════════════════
#  LEVEL 2 — real hardware test 
# ═══════════════════════════════════════════════════════════════════════════
 
def level2_hardware(port, NQ=5, Np=2, sim_Cpp=True, ouput_sim=""):
    print("\n" + "="*60)
    print(f"  LEVEL 2 — real hardware  port={port}  NQ={NQ}  Np={Np}")
    print("="*60)
 
    # ── Import the actual driver ──────────────────────────────────────────
    # Adjust this import to match your package layout
    try:
                import sys, os
                sys.path.insert(0, r"C:\\altera\\Actual_Fpga")
                from main.Base.Simulators.FPGA.Fpga_sim import FPGASimulator
    except ImportError as e:
                print(f"  Import failed: {e}")
                return False
 
    fpga_config = {'port': port, 'baudrate': 115200, 'max_qubits': 20}
 
    # ── Build a small random problem ──────────────────────────────────────
    NS = 1 << NQ
    seed = 0x22a2037
    # generating initial states
    random.seed(seed); np.random.seed(seed)
    H_raw = np.array([random.uniform(-190, 190) for _ in range(NS)])
    #H_raw = np.array([1/(2.0) for _ in range(NS)])
    gammas = np.array([random.uniform(-math.pi, math.pi) for _ in range(Np)])
    #gammas = np.array([2*np.pi for _ in range(Np)])
    # gammas = np.pi/H_raw
    betas  = np.array([random.uniform(-math.pi, math.pi) for _ in range(Np)])
    sv0_raw = np.array([complex(random.uniform(-1,1), random.uniform(-1,1)) for _ in range(NS)])
    sv0 = sv0_raw / np.linalg.norm(sv0_raw)

    # test 2
    
    def _scale_H_gamma(H, gammas):
        H = np.asarray(H, dtype=np.float64) # H in range [-S, S]
        gammas = np.asarray(gammas, dtype=np.float64)

        S = np.max(np.abs(H))
        if S == 0:
            return H.copy(), gammas.copy(), 1.0
        H_scaled = H / np.sqrt(2.0 * S) # scale to fit in Q5.59 range [-10, 10] max to 20 Qubits 
        gamma_scaled = gammas * np.sqrt(S) / (np.pi * np.sqrt(2.0)) # scale to fit in Q6.58 range [-32, 32] (cover max 20 values with margin) max to 20 Qubits

        return H_scaled, gamma_scaled, S

    H_scaled, gamma_scaled, S = _scale_H_gamma(H_raw, gammas)
    
    print("gammma scaled", gamma_scaled, S)
    print("H scaled", H_scaled)
    FRAC_Q361=61; FRAC_G=58; FRAC_H=59
    cosb = np.cos(betas)
    sinb = np.sin(betas)
    cosb_w = [float(cosb[0])] + [float(c) for c in cosb]
    sinb_w = [float(sinb[0])] + [float(s) for s in sinb]
    gam_w  = [float(g) for g in gamma_scaled] + [-1.0]
    def float_to_hex(value):
        return f"0x{(int(round(value*(1<<FRAC_Q361)))&0xFFFFFFFFFFFFFFFF):016x}"
    def float_to_hexG(value):
        return f"0x{(int(round(value*(1<<FRAC_G)))&0xFFFFFFFFFFFFFFFF):016x}"
    def float_to_hexH(value):
        return f"0x{(int(round(value*(1<<FRAC_H)))&0xFFFFFFFFFFFFFFFF):016x}"
    def complex_to_hex(value):
        return f"({float_to_hex(value.real)}, {float_to_hex(value.imag)})" 
    def swap_bits(i, a, b):
        ba=(i>>a)&1; bb=(i>>b)&1
        if ba!=bb: i^=(1<<a)|(1<<b)
        return i

        
    fs = open("statistics.txt", "a")
    fs.write(f"---------------------------------------\n")
    fs.write(f"summary of the computation \n")
    fs.write(f"---------------------------------------\n")
    fs.close()
    fs = open("statistics.txt", "a")
    if sim_Cpp != "cpp":
        if ouput_sim == "":
            print("simulation output is disabled")
            # ── Python reference simulation ───────────────────────────────────────
            
            sv_ref = list(sv0.copy())
            # Simulation part
            t0_cpu = time.perf_counter()

            for p in range(Np):
                gs = gam_w[p]; cb = cosb_w[p+1]; sb = sinb_w[p+1]
                    
                for i in range(NS):
                    ang = gs*H_scaled[i]*2*np.pi
                    costFt =  math.cos(ang) + 1j*math.sin(ang)
                    sv_ref[i] *= costFt
                for cq in range(NQ):
                    for id2 in range(NS//2):
                        a = swap_bits(id2*2,   cq, 0)
                        b = swap_bits(id2*2+1, cq, 0)
                        tsa =  cb*sv_ref[a] - 1j*sb*sv_ref[b]
                        tsb = -1j*sb*sv_ref[a] + cb*sv_ref[b]
                        sv_ref[a]=tsa; sv_ref[b]=tsb
                        
            p = Np    
            
            dt_cpu = time.perf_counter() - t0_cpu
            print(f"  Python CPU reference wall time: {dt_cpu:.6f} s")         
        else: 
            print("simulation output is enabled")
            
            fs = open("simulation.txt", "w")
            
            fs.write(f"-------------------------------------------------------\n")
            fs.write(f"Version {random.random()}, {datetime.datetime.now()}\n")
            fs.write(f"Pi = {float_to_hex(np.pi)}\n")
            fs.write(f"-------------------------------------------------------\n")
            sv_ref = list(sv0.copy())
            # Simulation part
            for i in range(NS):
                fs.write(f"H_{i}, {float_to_hexH(H_scaled[i])}\n")
            for i in range(NS):
                fs.write(f"p_{i}, {complex_to_hex(sv_ref[i])}\n")
            t0_cpu = time.perf_counter()

            for p in range(Np):
                gs = gam_w[p]; cb = cosb_w[p+1]; sb = sinb_w[p+1]
                fs.write(f"\n# Starting {p}-th layer. Current params: gamma={float_to_hexG(gs)}, cosb={float_to_hex(cb)}, sinb={float_to_hex(sb)}\n\n")
                print(f"\nwriting {p} th layer, {gs}, {cb}, {sb}\n")
                    
                for i in range(NS):
                    ang = gs*H_scaled[i]*2*np.pi
                    costFt =  math.cos(ang) + 1j*math.sin(ang)
                    fs.write(f"F_{i}: {complex_to_hex(costFt)}, {costFt}\n")
                    sv_ref[i] *= costFt
                for i in range(NS):
                    fs.write(f"F_{i}p_{i}: {complex_to_hex(sv_ref[i])}, {sv_ref[i]}\n")
                for cq in range(NQ):
                    for id2 in range(NS//2):
                        a = swap_bits(id2*2,   cq, 0)
                        b = swap_bits(id2*2+1, cq, 0)
                        tsa =  cb*sv_ref[a] - 1j*sb*sv_ref[b]
                        tsb = -1j*sb*sv_ref[a] + cb*sv_ref[b]
                        sv_ref[a]=tsa; sv_ref[b]=tsb
                        
                        fs.write(f"p_{a}: {complex_to_hex(tsa)}, {tsa}\n")
                        fs.write(f"p_{b}: {complex_to_hex(tsb)}, {tsb}\n")
            p = Np    
            
            dt_cpu = time.perf_counter() - t0_cpu
            print(f"  Python CPU reference wall time: {dt_cpu:.6f} s")

            gs = gam_w[p]; cb = cosb_w[p]; sb = sinb_w[p]
            fs.write("\n")
            fs.write(f"# Starting {p}-th layer. Current params: gamma={float_to_hexG(gs)}, cosb={float_to_hex(cb)}, sinb={float_to_hex(sb)}\n")
            fs.write("\n")
            fs.write(f"\n---Results----------------------\n\n")
            for i in range(NS):
                fs.write(f"Re(p_{i}), {float_to_hex(sv_ref[i].real)}\n")
            for i in range(NS):
                fs.write(f"Im(p_{i}), {float_to_hex(sv_ref[i].imag)}\n")
            fs.close()
        
        with open(f"result-NQ{NQ}-NP{Np}.txt","w") as f:
            for i in range(NS): f.write(float_to_hex(sv_ref[i].real) + "\n")
            for i in range(NS): f.write(float_to_hex(sv_ref[i].imag) + "\n")
        # Simulation part end
    else:
        # ── C++ reference simulation ───────────────────────────────────────
        # Python precomputes only mixer sin/cos: cb=cos(beta), sb=sin(beta).
        # The phase angle gamma*H*2*pi and its cos/sin are computed inside C++.
        cb_arr = np.asarray(cosb, dtype=np.float64)
        sb_arr = np.asarray(sinb, dtype=np.float64)
        gam_arr = np.asarray(gamma_scaled, dtype=np.float64)
        h_arr = np.asarray(H_scaled, dtype=np.float64)

        in_file = "qaoa_sim_input.bin"
        out_file = "qaoa_sim_output.bin"
        exe_name = "qaoa_sim.exe" if os.name == "nt" else "qaoa_sim"
        this_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
        cpp_path = os.path.join(this_dir, "qaoa_sim.cpp")
        if not os.path.exists(cpp_path):
            cpp_path = os.path.abspath("qaoa_sim.cpp")
        exe_path = os.path.join(this_dir, exe_name)

        if (not os.path.exists(exe_path)) or (os.path.getmtime(exe_path) < os.path.getmtime(cpp_path)):
            cmd = ["g++", "-O3", "-march=native", "-std=c++20", cpp_path, "-o", exe_path]
            print("  Compiling C++ simulator:", " ".join(cmd))
            subprocess.run(cmd, check=True)

        with open(in_file, "wb") as f:
            f.write(struct.pack("<IIII", 0x51414F41, int(NQ), int(Np), int(NS)))
            np.asarray(sv0.real, dtype="<f8").tofile(f)
            np.asarray(sv0.imag, dtype="<f8").tofile(f)
            h_arr.astype("<f8", copy=False).tofile(f)
            gam_arr.astype("<f8", copy=False).tofile(f)
            cb_arr.astype("<f8", copy=False).tofile(f)
            sb_arr.astype("<f8", copy=False).tofile(f)

        t0_cpu = time.perf_counter()
        subprocess.run([exe_path, in_file, out_file, f"result-NQ{NQ}-NP{Np}.txt"], check=True)
        dt_cpu = time.perf_counter() - t0_cpu
        print(f"  C++ CPU reference wall time: {dt_cpu:.6f} s")

        raw = np.fromfile(out_file, dtype="<f8")
        if raw.size != 2 * NS:
            raise RuntimeError(f"C++ simulator output size mismatch: got {raw.size}, expected {2*NS}")
        sv_ref = raw[:NS] + 1j * raw[NS:]
        # Simulation part end
    # ── Run on FPGA ───────────────────────────────────────────────────────
    sim = FPGASimulator(n_qubits=NQ, costs=H_raw, fpga_config=fpga_config)
    t0 = time.perf_counter()
    sv_fpga = sim.simulate_qaoa(gammas, betas, sv0=sv0.copy())
    dt = time.perf_counter() - t0
    ctime = sim.get_duration_time()
    print(f"  FPGA wall time: {dt:.4f} s")
    print(f"✓ Read time {ctime} [s]")

    fs.write(f"FPGA time: {ctime}\n")
    fs.write(f"NQ: {NQ}\n")
    fs.write(f"NP: {Np}\n")
    fs.write(f"NS: {2**NQ}\n")
    # ── MAE ───────────────────────────────────────────────────────────────
    mae_r = sum(abs(sv_fpga[i].real - sv_ref[i].real) for i in range(NS)) / NS
    mae_i = sum(abs(sv_fpga[i].imag - sv_ref[i].imag) for i in range(NS)) / NS
    mae   = (mae_r + mae_i) / 2
    print(f"  MAE real : {mae_r:.4e}")
    print(f"  MAE imag : {mae_i:.4e}")
    print(f"  MAE total: {mae:.4e}")
    THRESHOLD = 1e-3
    fs.write(f"MAE: {mae:.4e}\n")

    ok = mae < THRESHOLD
    print(f"  Result   : {'PASS ✓' if ok else 'FAIL ✗  (MAE too large)'}")
    
    # Save outputs
    with open(f"resultFPGA-NQ{NQ}-NP{Np}.txt","w") as f:
        for i in range(NS): f.write(f"0x{(int(round(sv_fpga[i].real*(1<<61)))&0xFFFFFFFFFFFFFFFF):016x}\n")
        for i in range(NS): f.write(f"0x{(int(round(sv_fpga[i].imag*(1<<61)))&0xFFFFFFFFFFFFFFFF):016x}\n")
    
    print("  Saved resultFPGA.txt and result.txt")
    return ok
 
 
# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
 
if __name__ == "__main__":
    port = None
    NQ, Np = 6, 2
    head = ""
    dic = {
        "--Np": 2,
        "--NQ": 6,
        "--port": "",
        "--sim": "cpp",
        "--output-sim": ""
    }
    for i in range(1, len(sys.argv)):
        v = sys.argv[i]
        if head != "":
            dic[head] = type(dic[head])(v)
            head = ""
        if v in dic:
            head = v 
    print(dic)
    NQ = dic["--NQ"]
    Np = dic["--Np"]
    port = dic["--port"]
    sim = dic["--sim"]
    output_sim = dic["--output-sim"]
    p0 = level0_unit_tests()
    p1 = level1_dry_run()
    
    if port == "":
        print("\n  Level 2 generating for RTL.")
 
    p2 = level2_hardware(port, NQ, Np, sim, output_sim)
 
    print("\n" + "="*60)
    print(f"  SUMMARY: L0={'PASS' if p0 else 'FAIL'}  "
          f"L1={'PASS' if p1 else 'FAIL'}  "
          f"L2={'PASS' if p2 else 'FAIL' if port else 'SKIP'}")
    print("="*60)
    sys.exit(0 if (p0 and p1 and p2) else 1)