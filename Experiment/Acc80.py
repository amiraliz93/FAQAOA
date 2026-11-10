"""
acc80_csv.py - 80-bit accuracy check of one qaoa_experiment.py run; appends 5 rows to a CSV.

  python3 acc80_csv.py <run folder>/data.npz results/simple/accuracy_80bit.csv

Recomputes the run's circuit in 80-bit extended precision (np.longdouble, 64-bit significand)
and reports delta_2 / delta_inf of the FPGA and C++ states against two references:
  datapath   - the inputs each simulator actually received (FPGA: the fixed-point words the
               driver sends, phase as an exact integer product; C++: the driver's FP64 values)
  end_to_end - the problem as specified (theta = gamma * eps), so host rescaling is included
plus the FPGA state divided by its own norm (fpga_renormalised, end to end).
Needs Linux or macOS on x86: on Windows np.longdouble is only FP64, and the assert below stops it.
"""
import sys, math
import numpy as np
from fractions import Fraction
LD = np.longdouble
assert np.finfo(LD).eps < 1e-18
PI = LD("3.14159265358979323846264338327950288")
z = np.load(sys.argv[1], allow_pickle=False)
eps, sv0, g, b = z["eps"], z["sv0"], z["gammas"], z["betas"]
n = int(round(math.log2(eps.size)))
S = float(np.max(np.abs(eps)))
Hs = eps / np.sqrt(2.0 * S); gs = g * np.sqrt(S) / (np.pi * np.sqrt(2.0))          # driver's FP64 scaling
fx = lambda v, f: np.array([int(x) for x in np.rint(np.asarray(v, np.float64) * float(1 << f))], dtype=object)
fxH, fxG = fx(Hs, 59), fx(gs, 58)
cb, sb = np.cos(b), np.sin(b)
def mixer(re, im, c, s):
    for q in range(n):
        R = re.reshape(-1, 2, 1 << q); I = im.reshape(-1, 2, 1 << q)
        ar, br, ai, bi = R[:, 0].copy(), R[:, 1].copy(), I[:, 0].copy(), I[:, 1].copy()
        R[:, 0] = c * ar + s * bi; I[:, 0] = c * ai - s * br
        R[:, 1] = s * ai + c * br; I[:, 1] = -s * ar + c * bi
    return re, im
def run(re0, im0, phase, c, s):
    re, im = re0.astype(LD).copy(), im0.astype(LD).copy()
    for k in range(len(g)):
        cp, sp = phase(k)
        re, im = re * cp - im * sp, re * sp + im * cp
        re, im = mixer(re, im, c[k], s[k])
    return re, im
def ph_scaled(k):
    a = LD(float(gs[k])) * Hs.astype(LD) * (2 * PI); return np.cos(a), np.sin(a)
def ph_fixed(k):
    r = (fxH * int(fxG[k])) % (1 << 117); r = np.where(r >= (1 << 116), r - (1 << 117), r)
    hi = np.array([int(x) >> 58 for x in r], dtype=np.int64); lo = np.array([int(x) & ((1 << 58) - 1) for x in r], dtype=np.int64)
    a = PI * ((hi.astype(LD) * LD(2) ** 58 + lo.astype(LD)) * LD(2) ** -116); return np.cos(a), np.sin(a)
def ph_problem(k):
    a = LD(float(g[k])) * eps.astype(LD); return np.cos(a), np.sin(a)
t61 = LD(2) ** 61
refs = {
  "scaled inputs (FP64 values given to C++)": run(sv0.real, sv0.imag, ph_scaled, cb.astype(LD), sb.astype(LD)),
  "fixed inputs (words sent to the FPGA)": run(fx(sv0.real, 61).astype(LD) / t61 if False else np.array([LD(int(x)) for x in fx(sv0.real, 61)]) / t61,
                                               np.array([LD(int(x)) for x in fx(sv0.imag, 61)]) / t61, ph_fixed,
                                               np.array([LD(int(x)) for x in fx(cb, 61)]) / t61, np.array([LD(int(x)) for x in fx(sb, 61)]) / t61),
  "problem as specified (theta = gamma*eps)": run(sv0.real, sv0.imag, ph_problem, np.cos(b.astype(LD)), np.sin(b.astype(LD))),
}
def d2(st, ref):
    rr, ri = ref; return float(np.sqrt(((st.real.astype(LD) - rr) ** 2 + (st.imag.astype(LD) - ri) ** 2).sum()))
def dinf(st, ref):
    rr, ri = ref; return float(np.sqrt(((st.real.astype(LD) - rr) ** 2 + (st.imag.astype(LD) - ri) ** 2).max()))
import csv, os
out = sys.argv[2]
problem = "random" if np.abs(sv0.imag).max() > 0 else "maxcut-regular3"
rows = []
own = {"fpga": "fixed inputs (words sent to the FPGA)", "cpp": "scaled inputs (FP64 values given to C++)"}
for sim, key in (("fpga", "state_fpga"), ("cpp", "state_cpp")):
    st = z[key]
    for refname, refkey in (("datapath", own[sim]), ("end_to_end", "problem as specified (theta = gamma*eps)")):
        rows.append({"problem": problem, "n": n, "p": len(g), "simulator": sim, "reference": refname,
                     "delta_2": d2(st, refs[refkey]), "delta_inf": dinf(st, refs[refkey])})
    if sim == "fpga":                      # renormalised FPGA state, end to end
        nrm = float(np.sqrt((np.abs(st.astype(np.clongdouble)) ** 2).sum()))
        rows.append({"problem": problem, "n": n, "p": len(g), "simulator": "fpga_renormalised", "reference": "end_to_end",
                     "delta_2": d2(st / nrm, refs["problem as specified (theta = gamma*eps)"]),
                     "delta_inf": dinf(st / nrm, refs["problem as specified (theta = gamma*eps)"])})
new = not os.path.exists(out)
with open(out, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    if new: w.writeheader()
    w.writerows(rows)
print(problem, n, len(g), "done")