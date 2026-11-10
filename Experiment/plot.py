"""
plot.py - thesis figures from the FPGA / Qiskit Aer re-run

    python plot.py                     # reads ..\\results\\simple (or .\\results\\simple) next to this script
    python plot.py path\\to\\simple      # or any results folder

Inputs (results folder)
    runs.csv              one row per single evaluation (FPGA and Aer)                 fig1-fig4
    optimise.csv          one row per optimiser evaluation                             fig4, fig7
    optimise_summary.csv  one row per optimiser run                                    fig6, fig7
    accuracy_80bit.csv    errors against the 80-bit reference (acc80 analysis)         fig5
    cnp_digitised.csv     optional: values digitised from the published CN-P figure    grey reference in fig2, fig3

Outputs (results folder\\figures)
    figN_*.pdf (vector, for LaTeX), figN_*.png (300 dpi) and figN_*.csv (every plotted number, for the text)

    fig1_fpga_runtime    cycle counter against the schedule model; cycles per layer against (n + 1) 2^n
    fig2_compute_time    compute time per circuit T_run, FPGA vs Aer (complete and 3-regular graphs)
    fig3_speedup         compute speed-up T_run(Aer) / T_run(FPGA)
    fig4_time_per_eval   whole evaluation T_eval against compute only T_run; compute share omega
    fig5_accuracy        delta_2 against the 80-bit reference: random instance and 3-regular Max-Cut
    fig6_optimiser       best approximation ratio within the COBYLA budget, FPGA vs Aer, per n
    fig7_optimiser_loop  FPGA vs Aer seed by seed; best-so-far against evaluations and evaluation time

Uses only numpy and matplotlib. A figure whose data are missing is skipped with a message.
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------- settings
F_CLK = 320e6
DEPTHS = (1, 32)            # depths shown in fig2-fig4
BUDGET = "100"              # optimiser budget shown in fig6-fig7
LOOP_CASE = (8, 2)          # (n, p) of the progress panels in fig7
AER_TIMING_FROM = ""        # use only Aer timing rows logged at or after this time, e.g. "2026-11-08"; "" = all
EXCLUDE = {                 # (folder, repeat): reason. Dropped from transfer-time plots only (counter and state still count)
    ("20261106-135414_random_n12_p32", "4"): "Windows sleep during the transfer",
}

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else next(
    (d for d in (HERE.parent / "results" / "simple", HERE / "results" / "simple") if d.exists()),
    HERE.parent / "results" / "simple")
FIG = OUT / "figures"

STYLE = {"fpga": dict(color="#2a78d6", marker="o", label="FPGA"),
         "aer": dict(color="#eb6834", marker="s", label="Qiskit Aer (CPU)"),
         "cpp": dict(color="#1baf7a", marker="^", label="C++ (FP64)")}
INK, GREY, LIGHT = "#0b0b0b", "#52514e", "#a9a8a4"
P_COLOURS = {1: "#2a78d6", 2: "#1baf7a", 3: "#8a4fd8"}
N_MARKERS = {8: "o", 10: "s", 12: "^", 16: "D"}

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "mathtext.fontset": "stix",
    "font.size": 9, "axes.labelsize": 9, "legend.fontsize": 7.5, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": GREY, "axes.labelcolor": INK,
    "xtick.color": GREY, "ytick.color": GREY, "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.5,
    "lines.linewidth": 1.3, "lines.markersize": 4.5, "legend.frameon": False, "savefig.bbox": "tight"})


# ---------------------------------------------------------------- data helpers
def load(name):
    path = OUT / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sim(r):
    return r.get("sim") or "fpga"                  # rows written before --sim existed are FPGA rows


def num(r, key):
    v = r.get(key)
    return float(v) if v not in ("", None) else None


def n_p(r):
    return int(r["NQ"]), int(r["Np"])


def grouped(rows, key, value):
    """{key(r): [value(r), ...]} for the rows that have a value."""
    out = defaultdict(list)
    for r in rows:
        v = value(r)
        if v is not None:
            out[key(r)].append(v)
    return out


def med_range(values):
    v = np.asarray(values, float)
    return float(np.median(v)), float(v.min()), float(v.max())


def excluded(r):
    return (r.get("folder", ""), r.get("repeat", "")) in EXCLUDE


def fpga_model(n, p):
    """Closed-form schedule model, valid for 8 <= n <= 16 (the counter equals it in every measured run)."""
    return (p * (n + 1) * 2 ** n + 2 ** n + 43) / F_CLK if 8 <= n <= 16 else None


def fpga_times(runs):
    """{(n, p): T_run} from every FPGA row; the counter does not depend on the problem."""
    return {k: float(np.median(v)) for k, v in
            grouped([r for r in runs if sim(r) == "fpga"], n_p, lambda r: num(r, "T_run_s")).items()}


def aer_timing_rows(runs):
    return [r for r in runs if sim(r) == "aer" and r["time"] >= AER_TIMING_FROM]


class Table:
    """Collects the plotted numbers and writes them next to the figure."""
    def __init__(self, *header):
        self.header, self.rows = header, []

    def add(self, *row):
        self.rows.append(row)

    def save(self, name):
        with open(FIG / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.header)
            w.writerows(self.rows)


def save(fig, name, table=None):
    FIG.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=300)
    plt.close(fig)
    if table is not None:
        table.save(name)
    print(f"  wrote figures/{name}.pdf, .png" + (" and .csv" if table is not None else ""))


def panel(ax, text):
    ax.set_title(text, loc="left", fontsize=9, color=INK)


def n_axis(ax, ns):
    ns = sorted(ns)
    ax.set_xticks([n for n in ns if n % 2 == 0] if len(ns) > 8 else ns)   # even n only when crowded
    ax.set_xlabel("Number of qubits $n$")


def log2_p_axis(ax, ps=(1, 8, 16, 32)):
    ax.set_xscale("log", base=2)
    ax.set_xticks(ps)
    ax.set_xticklabels([str(p) for p in ps])
    ax.minorticks_off()
    ax.set_xlabel("QAOA depth $p$")


# ---------------------------------------------------------------- audit (printed before any figure)
def audit(runs, opt_eval, opt_sum):
    print("\nData audit")
    fp = [r for r in runs if sim(r) == "fpga"]
    bad = [r for r in fp if r.get("model_cycles") and r["counter"] != r["model_cycles"]]
    print(f"  FPGA single evaluations: {len(fp)}; cycle counter = schedule model in {len(fp) - len(bad)}")
    for r in bad:
        print(f"    MISMATCH {r['folder']} repeat {r['repeat']}: counter {r['counter']}, model {r['model_cycles']}")
    for (folder, rep), why in EXCLUDE.items():
        if any(r.get("folder") == folder and r.get("repeat") == rep for r in runs):
            print(f"  excluded from transfer times: {folder} repeat {rep} ({why})")
    # unexplained transfer-time outliers
    g = defaultdict(list)
    for r in runs:
        if num(r, "t_eval_s") is not None and not excluded(r):
            g[(sim(r), r["mode"], r["graph"], r.get("io", ""), r["NQ"], r["Np"])].append(r)
    for rows in g.values():
        m = np.median([num(r, "t_eval_s") for r in rows])
        for r in rows:
            if num(r, "t_eval_s") > 1.5 * m and num(r, "t_eval_s") - m > 1.0:
                print(f"  WARNING transfer outlier: {r['folder']} repeat {r['repeat']} t_eval {num(r, 't_eval_s'):.1f} s "
                      f"(median {m:.1f} s) - add it to EXCLUDE with the reason if it is not a real measurement")
    # Aer batches: the conditions behind every Aer timing must be stated in the thesis
    batches = defaultdict(list)
    for r in runs:
        if sim(r) == "aer":
            batches[(r["graph"], r["time"][:10], r.get("note", ""))].append(r)
    for (graph, day, note), rows in sorted(batches.items()):
        used = "used" if rows[0]["time"] >= AER_TIMING_FROM else "NOT used (before AER_TIMING_FROM)"
        flag = "  <- note not recorded: CPU configuration unknown" if (not note or note.startswith("$")) else ""
        print(f"  Aer batch {graph:8s} {day} {rows[0]['time'][11:16]}-{rows[-1]['time'][11:16]}: {len(rows)} rows, "
              f"note '{note}', {used}{flag}")
    if opt_sum:
        s = defaultdict(set)
        for r in opt_sum:
            if r.get("budget") == BUDGET:
                s[(sim(r), r["NQ"], r["Np"])].add(int(r["seed"]))
        for k in sorted(s, key=lambda k: (k[0], int(k[1]), int(k[2]))):
            print(f"  optimiser {k[0]:4s} n={k[1]:>2} p={k[2]}: seeds {sorted(s[k])}")
    print()


# ---------------------------------------------------------------- fig1: FPGA runtime model
def fig_fpga_runtime(runs):
    fp = [r for r in runs if sim(r) == "fpga" and r.get("counter")]
    if not fp:
        print("  fig1 skipped: no FPGA rows")
        return
    tab = Table("panel", "problem", "n", "p", "counter_cycles", "model_cycles", "T_run_s")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.6), gridspec_kw={"width_ratios": [1.25, 1]})
    fig.subplots_adjust(wspace=0.3)
    # (a) T_run against n: measured counter (markers) and schedule model (lines)
    for p, shade in zip(DEPTHS, ("#7fb0ea", "#1d5fae")):
        for prob, mk, face in (("random", "o", shade), ("graph", "^", "white")):
            pts = sorted({(int(r["NQ"]), int(r["counter"]), int(r["model_cycles"])) for r in fp
                          if r["mode"] == prob and int(r["Np"]) == p})
            if not pts:
                continue
            a1.plot([q[0] for q in pts], [q[1] / F_CLK for q in pts], ls="none", marker=mk, color=shade, mfc=face,
                    label=f"$p={p}$, {'random instance' if prob == 'random' else 'Max-Cut'}")
            for q in pts:
                tab.add("a", prob, q[0], p, q[1], q[2], q[1] / F_CLK)
        model = sorted({(int(r["NQ"]), int(r["model_cycles"])) for r in fp if int(r["Np"]) == p})
        a1.plot([m[0] for m in model], [m[1] / F_CLK for m in model], color=shade, lw=0.9, zorder=0)
    a1.set_yscale("log")
    a1.axvspan(1.5, 7.5, color="#f1f0ec", zorder=-1, lw=0)
    a1.text(4.5, 0.17, "padded schedule", transform=a1.get_xaxis_transform(), ha="center", va="center", fontsize=7, color=GREY)
    n_axis(a1, {int(r["NQ"]) for r in fp})
    a1.set_ylabel("FPGA compute time $T_\\mathrm{run}$ (s)")
    panel(a1, "(a) counter (markers), model (lines)")
    a1.legend(loc="upper left", fontsize=7)
    # (b) cycles per layer / 2^n from a straight-line fit in p, against the ideal n + 1 sweeps
    byn = defaultdict(dict)
    for r in fp:
        byn[int(r["NQ"])][int(r["Np"])] = int(r["counter"])
    ns, per, worst = [], [], 0.0
    for n in sorted(byn):
        if len(byn[n]) < 2:
            continue
        ps = np.array(sorted(byn[n]), float)
        cs = np.array([byn[n][int(p)] for p in ps], float)
        slope, icpt = np.polyfit(ps, cs, 1)
        worst = max(worst, float(np.max(np.abs(cs - (slope * ps + icpt)))))
        ns.append(n), per.append(slope / 2 ** n)
        tab.add("b", "any", n, ";".join(str(int(p)) for p in ps), round(slope, 3), (n + 1) * 2 ** n, "")
    if ns:
        nn = np.arange(min(ns), max(ns) + 1)
        a2.plot(nn, nn + 1, color=GREY, lw=0.9, ls="--", label="ideal: $n+1$ sweeps of $2^n$")
        a2.plot(ns, per, ls="none", **{**STYLE["fpga"], "label": "measured (fit over $p$)"})
        n_axis(a2, ns)
        a2.set_ylabel("Cycles per layer $/\\,2^n$")
        panel(a2, "(b) cycles per QAOA layer")
        a2.legend(loc="upper left", fontsize=7)
        print(f"  fig1: counter linear in p for n = {ns} (largest residual {worst:.0f} cycles); "
              f"cycles per layer / 2^n = {[round(float(x), 2) for x in per]}")
    save(fig, "fig1_fpga_runtime", tab)


# ---------------------------------------------------------------- fig2 and fig3: compute time against Aer
def aer_series(aer, graph, p):
    g = grouped([r for r in aer if r["graph"] == graph and int(r["Np"]) == p], lambda r: int(r["NQ"]),
                lambda r: num(r, "T_run_s"))
    return {n: med_range(v) + (len(v),) for n, v in sorted(g.items())}


def published_aer(p):
    pub = load("cnp_digitised.csv")
    return {int(r["NQ"]): float(r["T_run_s"]) for r in pub if r["series"] == "aer" and int(r["Np"]) == p}


def fig_compute_time(runs):
    aer = aer_timing_rows(runs)
    if not aer:
        print("  fig2/fig3 skipped: no Aer rows (after AER_TIMING_FROM)")
        return
    ft = fpga_times(runs)
    tab = Table("p", "simulator", "graph", "n", "T_run_median_s", "T_run_min_s", "T_run_max_s", "repeats", "source")
    fig, axes = plt.subplots(1, len(DEPTHS), figsize=(6.3, 2.6), sharey=True)
    for ax, p, letter in zip(axes, DEPTHS, "ab"):
        ns = sorted({n for (n, q) in ft if q == p})
        ax.plot(ns, [ft[(n, p)] for n in ns], ls="-", **{**STYLE["fpga"], "label": "FPGA (any problem)"})
        for n in ns:
            tab.add(p, "fpga", "any", n, ft[(n, p)], "", "", "", "counter")
        for graph, ls, face, lab in (("complete", "-", None, "complete graph $K_n$"), ("regular", "--", "white", "3-regular graph")):
            s = aer_series(aer, graph, p)
            if s:
                x = list(s)
                m, lo, hi = (np.array([s[n][i] for n in x]) for i in range(3))
                ax.errorbar(x, m, yerr=[m - lo, hi - m], ls=ls, color=STYLE["aer"]["color"], marker="s",
                            mfc=face or STYLE["aer"]["color"], capsize=2, elinewidth=0.8, label=f"Aer, {lab}")
                for n in x:
                    tab.add(p, "aer", graph, n, *s[n], "run() + result()")
        pub = published_aer(p)
        if pub:
            ax.plot(list(pub), list(pub.values()), ls="none", marker="x", color=LIGHT, ms=4,
                    label="Aer, $K_n$, published figure")
            for n, t in pub.items():
                tab.add(p, "aer", "complete", n, t, "", "", "", "CN-P figure (digitised)")
        ax.set_yscale("log")
        n_axis(ax, sorted(set(ns) | {int(r["NQ"]) for r in aer}))
        panel(ax, f"({letter}) $p = {p}$")
    axes[0].set_ylabel("Compute time per circuit $T_\\mathrm{run}$ (s)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=2)
    save(fig, "fig2_compute_time", tab)


def fig_speedup(runs):
    aer = aer_timing_rows(runs)
    if not aer:
        return
    ft = fpga_times(runs)
    tab = Table("p", "graph", "n", "speedup_median", "speedup_min", "speedup_max", "fpga_time_from")
    fig, axes = plt.subplots(1, len(DEPTHS), figsize=(6.3, 2.5), sharey=True)
    modelled = set()
    for ax, p, letter in zip(axes, DEPTHS, "ab"):
        for graph, ls, face, lab in (("complete", "-", INK, "complete graph $K_n$"), ("regular", "--", "white", "3-regular graph")):
            s = aer_series(aer, graph, p)
            xs, m, lo, hi = [], [], [], []
            for n, (med, mn, mx, _) in s.items():
                t = ft.get((n, p)) or fpga_model(n, p)
                if not t:
                    continue
                if (n, p) not in ft:
                    modelled.add((n, p))
                xs.append(n), m.append(med / t), lo.append(mn / t), hi.append(mx / t)
                tab.add(p, graph, n, med / t, mn / t, mx / t, "counter" if (n, p) in ft else "model")
            if xs:
                m, lo, hi = np.array(m), np.array(lo), np.array(hi)
                ax.errorbar(xs, m, yerr=[m - lo, hi - m], ls=ls, color=INK, marker="o", mfc=face, capsize=2,
                            elinewidth=0.8, label=lab)
        pub = published_aer(p)
        if pub:
            xs = [n for n in pub if (ft.get((n, p)) or fpga_model(n, p))]
            ax.plot(xs, [pub[n] / (ft.get((n, p)) or fpga_model(n, p)) for n in xs], ls="none", marker="x",
                    color=LIGHT, ms=4, label="$K_n$, published Aer values")
        ax.axhline(1, color=GREY, lw=0.8, ls=":")
        ax.set_yscale("log")
        ax.text(0.03, 1.08, "parity", transform=ax.get_yaxis_transform(), fontsize=7, color=GREY, va="bottom")
        n_axis(ax, {int(r["NQ"]) for r in aer})
        panel(ax, f"({letter}) $p = {p}$")
    axes[0].set_ylabel("Speed-up $T_\\mathrm{run}^\\mathrm{Aer}/T_\\mathrm{run}^\\mathrm{FPGA}$")
    axes[0].legend(loc="lower left", bbox_to_anchor=(0.0, 0.1), fontsize=7)
    if modelled:
        print(f"  fig3: FPGA time from the closed-form model at (n, p) = {sorted(modelled)} (no FPGA run there)")
    save(fig, "fig3_speedup", tab)


# ---------------------------------------------------------------- fig4: whole evaluation against compute
def fig_time_per_eval(runs, opt_eval):
    mc = [r for r in runs if r["graph"] == "regular" and not excluded(r)]
    fpga_mc = [r for r in mc if sim(r) == "fpga" and r.get("io", "").startswith("fast")]
    aer_mc = [r for r in aer_timing_rows(runs) if r["graph"] == "regular"]
    if not fpga_mc or not aer_mc:
        print("  fig4 skipped: needs 3-regular Max-Cut rows from the FPGA (--fast-io) and from Aer")
        return
    tab = Table("panel", "series", "n", "p", "median_s_or_ratio", "min", "max", "count")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.7))
    p0 = DEPTHS[0]

    def line(ax, rows, key, style, ls, face, lab, p=p0, tag=None):
        g = grouped([r for r in rows if int(r["Np"]) == p], lambda r: int(r["NQ"]), key)
        if not g:
            return
        x = sorted(g)
        st = [med_range(g[n]) for n in x]
        ax.plot(x, [s[0] for s in st], ls=ls, color=style["color"], marker=style["marker"],
                mfc=face or style["color"], label=lab)
        for n, s in zip(x, st):
            tab.add("a" if ax is a1 else "b", tag or lab, n, p, *s, len(g[n]))

    t_eval = lambda r: num(r, "t_eval_s")
    t_run = lambda r: num(r, "T_run_s")
    rnd = [r for r in runs if sim(r) == "fpga" and r["mode"] == "random" and r.get("io", "").startswith("fast")
           and not excluded(r)]
    loop = [r for r in opt_eval if sim(r) == "fpga" and r.get("eval") not in ("0", None)]   # cost diagonal already loaded
    fs, as_ = STYLE["fpga"], STYLE["aer"]
    line(a1, rnd, t_eval, {**fs, "marker": "o"}, "-", "white", "FPGA $T_\\mathrm{eval}$, random instance (complex start)")
    line(a1, fpga_mc, t_eval, {**fs, "marker": "^"}, "-", None, "FPGA $T_\\mathrm{eval}$, Max-Cut ($|+\\rangle$ sent once)")
    line(a1, loop, t_eval, {**fs, "marker": "D"}, "-", None, "FPGA $T_\\mathrm{eval}$, optimiser loop (cost diagonal once)")
    line(a1, aer_mc, t_eval, as_, "-", None, "Aer $T_\\mathrm{eval}$ (incl. binding and transpile)")
    line(a1, fpga_mc, t_run, fs, "--", "white", "FPGA $T_\\mathrm{run}$ (compute only)")
    line(a1, aer_mc, t_run, as_, "--", "white", "Aer $T_\\mathrm{run}$ (compute only)")
    a1.set_yscale("log")
    n_axis(a1, {int(r["NQ"]) for r in fpga_mc + aer_mc + rnd})
    a1.set_ylabel("Time per evaluation (s)")
    panel(a1, f"(a) time per evaluation, $p = {p0}$")
    # (b) compute share omega = T_run / T_eval, same problem for both simulators
    omega = lambda r: (num(r, "T_run_s") / num(r, "t_eval_s")) if num(r, "t_eval_s") else None
    for p, ls, face in ((DEPTHS[0], "-", None), (DEPTHS[-1], "--", "white")):
        line(a2, fpga_mc, omega, fs, ls, face, f"FPGA, $p={p}$", p=p, tag=f"omega FPGA p={p}")
        line(a2, aer_mc, omega, as_, ls, face, f"Aer, $p={p}$", p=p, tag=f"omega Aer p={p}")
    a2.set_yscale("log")
    n_axis(a2, {int(r["NQ"]) for r in fpga_mc + aer_mc})
    a2.set_ylabel("Compute share $\\omega = T_\\mathrm{run}/T_\\mathrm{eval}$")
    panel(a2, "(b) compute share")
    a2.legend(loc="upper left", bbox_to_anchor=(0.0, 0.64), fontsize=7, ncol=2)
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=2)
    fig.subplots_adjust(wspace=0.35)
    save(fig, "fig4_time_per_eval", tab)


# ---------------------------------------------------------------- fig5: accuracy against the 80-bit reference
def fig_accuracy(acc):
    if not acc:
        print("  fig5 skipped: no accuracy_80bit.csv")
        return
    tab = Table("problem", "n", "p", "simulator", "reference", "delta_2", "delta_inf")
    for r in acc:
        tab.add(r["problem"], r["n"], r["p"], r["simulator"], r["reference"], r["delta_2"], r.get("delta_inf", ""))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.7), sharey=True)
    # (a) random instance, n = 16: both references for the FPGA and for FP64 C++
    rnd = [r for r in acc if r["problem"] == "random"]
    for s in ("fpga", "cpp"):
        for ref, ls, face, what in (("end_to_end", "-", None, "end-to-end"), ("datapath", "--", "white", "datapath")):
            g = grouped([r for r in rnd if r["simulator"] == s and r["reference"] == ref], lambda r: int(r["p"]),
                        lambda r: num(r, "delta_2"))
            if g:
                x = sorted(g)
                a1.plot(x, [np.mean(g[p]) for p in x], ls=ls, color=STYLE[s]["color"], marker=STYLE[s]["marker"],
                        mfc=face or STYLE[s]["color"], label=f"{STYLE[s]['label']}, {what}")
    pp = np.array([1, 32])
    a1.plot(pp, 2.06e-15 * pp, color=GREY, lw=0.8, ls=":", label="FPGA norm loss, $2.06\\times10^{-15}$ per layer")
    log2_p_axis(a1)
    a1.set_yscale("log")
    a1.set_ylabel("$\\delta_2$ against the 80-bit reference")
    panel(a1, "(a) random instance, $n = 16$")
    a1.legend(loc="lower right", fontsize=6.5)
    # (b) 3-regular Max-Cut, end-to-end, against p for every n with at least two depths
    mc = [r for r in acc if r["problem"].startswith("maxcut") and r["reference"] == "end_to_end"]
    depths = defaultdict(set)
    for r in mc:
        depths[int(r["n"])].add(int(r["p"]))
    ns = [n for n in sorted(depths) if len(depths[n]) >= 2]
    skipped = [n for n in sorted(depths) if len(depths[n]) < 2]
    if skipped:
        print(f"  fig5: Max-Cut n = {skipped} have one depth only; in fig5_accuracy.csv, not plotted")
    styles = ["-", "--", "-.", ":"]
    for s, lab, face in (("fpga", "FPGA", None), ("fpga_renormalised", "FPGA, renormalised", "white"), ("cpp", "C++ (FP64)", None)):
        st = STYLE["fpga"] if s.startswith("fpga") else STYLE[s]
        for i, n in enumerate(ns):
            g = {int(r["p"]): num(r, "delta_2") for r in mc if r["simulator"] == s and int(r["n"]) == n}
            if g:
                x = sorted(g)
                a2.plot(x, [g[p] for p in x], ls=styles[i % 4], color=st["color"], marker=st["marker"],
                        mfc=face or st["color"], label=lab if i == 0 else None)
    a2.plot(pp, 2.06e-15 * pp, color=GREY, lw=0.8, ls=":")
    if len(ns) > 1:
        for i, n in enumerate(ns):      # line-style key for n
            a2.plot([], [], ls=styles[i % 4], color=GREY, label=f"$n = {n}$")
    log2_p_axis(a2)
    panel(a2, "(b) 3-regular Max-Cut" + (f", $n = {ns[0]}$" if len(ns) == 1 else "") + ", end-to-end")
    a2.legend(loc="lower right", fontsize=6.5)
    a2.tick_params(labelleft=True)
    save(fig, "fig5_accuracy", tab)


# ---------------------------------------------------------------- fig6 and fig7: optimiser loop
def paired_runs(opt_sum):
    """{(n, p, seed): {"fpga": row, "aer": row}} for the runs at BUDGET that both simulators completed."""
    pairs = defaultdict(dict)
    for r in opt_sum:
        if r.get("budget") == BUDGET and r.get("best_approx_ratio"):
            pairs[(int(r["NQ"]), int(r["Np"]), int(r["seed"]))][sim(r)] = r
    return {k: v for k, v in pairs.items() if "fpga" in v and "aer" in v}


def fig_optimiser(opt_sum):
    pairs = paired_runs(opt_sum)
    if not pairs:
        print("  fig6 skipped: no optimiser runs at the budget from both simulators")
        return
    ns = sorted({k[0] for k in pairs})
    tab = Table("n", "p", "simulator", "seeds", "mean", "sd", "min", "max")
    fig, axes = plt.subplots(1, len(ns), figsize=(6.3, 2.5), sharey=True, squeeze=False)
    rng = np.random.default_rng(0)
    for ax, n, letter in zip(axes[0], ns, "abcdef"):
        ps = sorted({k[1] for k in pairs if k[0] == n})
        for s, dx, face in (("fpga", -0.12, None), ("aer", 0.12, "white")):
            m, sd = [], []
            for p in ps:
                v = np.array([float(pairs[k][s]["best_approx_ratio"]) for k in pairs if k[:2] == (n, p)])
                ax.plot(p + dx + rng.uniform(-0.04, 0.04, len(v)), v, ls="none", marker=".", ms=2.5,
                        color=STYLE[s]["color"], alpha=0.45)
                m.append(v.mean()), sd.append(v.std(ddof=1) if len(v) > 1 else 0.0)
                tab.add(n, p, s, len(v), v.mean(), sd[-1], v.min(), v.max())
            ax.errorbar(np.array(ps) + dx, m, yerr=sd, ls="-", capsize=2, elinewidth=0.8, color=STYLE[s]["color"],
                        marker=STYLE[s]["marker"], mfc=face or STYLE[s]["color"], label=STYLE[s]["label"].split(" (")[0])
        seeds = len([k for k in pairs if k[:2] == (n, ps[0])])
        ax.set_xticks(ps)
        ax.set_xlabel("QAOA depth $p$")
        panel(ax, f"({letter}) $n = {n}$ ({seeds} seeds)")
    axes[0][0].set_ylabel(f"Best approximation ratio\nwithin {BUDGET} COBYLA evaluations")
    axes[0][0].legend(loc="lower right", fontsize=7)
    save(fig, "fig6_optimiser", tab)


def best_so_far(rows):
    """Running best approximation ratio and cumulative evaluation time for one run's evaluation log."""
    rows = sorted(rows, key=lambda r: int(r["eval"]))
    ar = np.maximum.accumulate([num(r, "approx_ratio") for r in rows])
    t = np.cumsum([num(r, "t_eval_s") for r in rows])
    return np.arange(1, len(rows) + 1), ar, t


def fig_optimiser_loop(opt_sum, opt_eval):
    pairs = paired_runs(opt_sum)
    if not pairs or not opt_eval:
        print("  fig7 skipped: needs paired optimiser runs and optimise.csv")
        return
    # evaluation log of each paired run: its rows logged within that run's wall time (drops test runs with the same key)
    span = {}
    for k, v in pairs.items():
        for s, r in v.items():
            end = datetime.fromisoformat(r["time"])
            span[(s,) + k] = (end - timedelta(seconds=float(r["wall_s"]) + 5), end + timedelta(seconds=5))
    logs = defaultdict(list)
    for r in opt_eval:
        key = (sim(r), int(r["NQ"]), int(r["Np"]), int(r["seed"]))
        if key in span and span[key][0] <= datetime.fromisoformat(r["time"]) <= span[key][1]:
            logs[key].append(r)
    # seed-by-seed agreement and identical paths
    tab = Table("n", "p", "seed", "best_fpga", "best_aer", "difference", "path_identical", "split_at_eval")
    identical, diffs = 0, []
    for k in sorted(pairs):
        f, a = sorted(logs[("fpga",) + k], key=lambda r: int(r["eval"])), sorted(logs[("aer",) + k], key=lambda r: int(r["eval"]))
        split = None
        for i in range(min(len(f), len(a))):
            xf = np.array(json.loads(f[i]["gammas"]) + json.loads(f[i]["betas"]))
            xa = np.array(json.loads(a[i]["gammas"]) + json.loads(a[i]["betas"]))
            if np.max(np.abs(xf - xa)) > 1e-6:
                split = i
                break
        if split is None and len(f) != len(a):
            split = min(len(f), len(a))
        identical += split is None
        bf, ba = float(pairs[k]["fpga"]["best_approx_ratio"]), float(pairs[k]["aer"]["best_approx_ratio"])
        diffs.append(bf - ba)
        tab.add(*k, bf, ba, bf - ba, split is None, "" if split is None else split)
    diffs = np.array(diffs)
    print(f"  fig7: {len(pairs)} paired runs; identical parameter paths in {identical}; "
          f"FPGA - Aer best ratio: mean {diffs.mean():+.1e}, largest |difference| {np.abs(diffs).max():.1e}")
    fig = plt.figure(figsize=(6.3, 2.35))
    a1 = fig.add_subplot(1, 3, 1)
    a2 = fig.add_subplot(1, 3, 2)
    a3 = fig.add_subplot(1, 3, 3, sharey=a2)
    # (a) FPGA against Aer, one point per seed
    for (n, p, seed), v in pairs.items():
        a1.plot(float(v["aer"]["best_approx_ratio"]), float(v["fpga"]["best_approx_ratio"]), ls="none",
                marker=N_MARKERS.get(n, "o"), color=P_COLOURS.get(p, GREY), mfc="none", ms=4, mew=0.8)
    lo = min(min(float(v[s]["best_approx_ratio"]) for s in v) for v in pairs.values()) - 0.01
    hi = max(max(float(v[s]["best_approx_ratio"]) for s in v) for v in pairs.values()) + 0.01
    a1.plot([lo, hi], [lo, hi], color=GREY, lw=0.8, ls=":")
    a1.set_xlim(lo, hi), a1.set_ylim(lo, hi)
    hp = [a1.plot([], [], ls="none", marker="o", color=c, mfc="none", label=f"$p={p}$")[0]
          for p, c in P_COLOURS.items() if any(k[1] == p for k in pairs)]
    hn = [a1.plot([], [], ls="none", marker=mk, color=GREY, mfc="none", label=f"$n={n}$")[0]
          for n, mk in N_MARKERS.items() if any(k[0] == n for k in pairs)]
    a1.add_artist(a1.legend(handles=hp, loc="upper left", fontsize=6.5, handletextpad=0.2))
    a1.legend(handles=hn, loc="lower right", fontsize=6.5, handletextpad=0.2)
    a1.set_xlabel("Aer, best ratio"), a1.set_ylabel("FPGA, best ratio")
    panel(a1, "(a) same seed and budget")
    # (b), (c) best-so-far for LOOP_CASE against evaluations and against cumulative evaluation time.
    # A run that stopped early (trust region converged) keeps its best value up to the longest run.
    n, p = LOOP_CASE
    seeds = sorted({k[2] for k in pairs if k[:2] == (n, p)})
    for s in ("fpga", "aer"):
        curves = [best_so_far(logs[(s, n, p, sd)]) for sd in seeds if logs[(s, n, p, sd)]]
        if not curves:
            continue
        m = max(len(c[0]) for c in curves)
        A = np.array([np.pad(c[1], (0, m - len(c[1])), mode="edge") for c in curves])
        T = np.array([np.pad(c[2], (0, m - len(c[2])), constant_values=np.nan) for c in curves])
        for c in curves:
            a2.plot(c[0], c[1], color=STYLE[s]["color"], lw=0.4, alpha=0.35)
            a3.plot(c[2], c[1], color=STYLE[s]["color"], lw=0.4, alpha=0.35)
        a2.plot(np.arange(1, m + 1), np.median(A, axis=0), color=STYLE[s]["color"], lw=1.5,
                label=STYLE[s]["label"].split(" (")[0])
        a3.plot(np.nanmedian(T, axis=0), np.median(A, axis=0), color=STYLE[s]["color"], lw=1.5)
        per_eval = np.nanmedian(np.diff(T, axis=1))
        print(f"  fig7: n={n}, p={p}, {s}: {len(curves)} seeds, median time per evaluation {per_eval:.3f} s, "
              f"median best ratio within {m} evaluations {np.median(A[:, -1]):.4f}")
    a2.set_xlabel("COBYLA evaluation"), a2.set_ylabel("Best-so-far ratio")
    a2.legend(loc="lower right", fontsize=7)
    panel(a2, f"(b) $n={n}$, $p={p}$ ({len(seeds)} seeds)")
    a3.set_xscale("log")
    a3.set_xlabel("Cumulative evaluation time (s)")
    a3.tick_params(labelleft=False)
    panel(a3, "(c) against evaluation time")
    fig.subplots_adjust(wspace=0.4)
    save(fig, "fig7_optimiser_loop", tab)


if __name__ == "__main__":
    runs, opt_eval, opt_sum, acc = load("runs.csv"), load("optimise.csv"), load("optimise_summary.csv"), load("accuracy_80bit.csv")
    print(f"{OUT}: {len(runs)} single evaluations, {len(opt_sum)} optimiser runs "
          f"({len(opt_eval)} evaluations), {len(acc)} accuracy rows")
    audit(runs, opt_eval, opt_sum)
    fig_fpga_runtime(runs)
    fig_compute_time(runs)
    fig_speedup(runs)
    fig_time_per_eval(runs, opt_eval)
    fig_accuracy(acc)
    fig_optimiser(opt_sum)
    fig_optimiser_loop(opt_sum, opt_eval)