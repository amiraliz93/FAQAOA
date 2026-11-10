"""
show_results.py - readable tables from results/simple/*.csv

  python show_results.py            all runs
  python show_results.py --today    only today's runs

Prints one line per configuration (repeats averaged), then, for every problem run on both
the FPGA and Aer (same graph, n, p and angles), one comparison line: speed and accuracy.
The same numbers, at full precision, go to results/simple/summary_runs.csv,
summary_compare.csv and summary_optimise.csv.
"""
import argparse
import csv
import datetime
import statistics
from pathlib import Path


OUT = Path(__file__).resolve().parent.parent / "results" / "simple"

def read(name, today):
    path = OUT / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    day = datetime.date.today().isoformat()
    return [r for r in rows if r["time"].startswith(day)] if today else rows


def values(rows, key):
    return [float(r[key]) for r in rows if r.get(key) not in ("", None)]


def mean(rows, key):
    v = values(rows, key)
    return statistics.mean(v) if v else None


def sd(rows, key):
    v = values(rows, key)
    return statistics.stdev(v) if len(v) > 1 else 0.0


def fmt(v, spec):
    return "-" if v is None else format(v, spec)


def write_csv(path, table):
    if table:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)


def sim_of(r):
    return r.get("sim") or "fpga"                    # rows from before --sim existed are FPGA rows


def how(r):
    """FPGA: transfer mode (driver / fast); Aer: device (CPU / GPU)."""
    return (r.get("device") or "CPU") if sim_of(r) == "aer" else (r.get("io") or "driver")


def graph_label(r):
    g = r["graph"] or "-"
    return g + (r.get("degree") or "") if g == "regular" else g


def problem_key(r):
    return (r["mode"], graph_label(r), r.get("graph_seed") or "", int(r["NQ"]), int(r["Np"]))


def show_runs(rows):
    groups = {}
    for r in rows:
        groups.setdefault(problem_key(r) + (sim_of(r), how(r)), []).append(r)
    print(f"\nSINGLE RUNS  (results/simple/runs.csv, {len(rows)} evaluations)\n")
    head = (f"{'sim':5}{'mode':7}{'graph':9}{'n':>3}{'p':>4}{'io/dev':>16}{'runs':>5}  {'counter':>11} {'model?':>6}"
            f"{'T_run ms':>20}{'total s':>13}{'load s':>8}{'read s':>8}{'delta_2':>10}{'ratio':>8}")
    print(head)
    print("-" * len(head))
    table = []
    for (mode, graph, gseed, n, p, sim, io), rs in sorted(groups.items()):
        fpga = sim == "fpga"
        counters = {r["counter"] for r in rs}
        counter = (counters.pop() if len(counters) == 1 else "varies!") if fpga else "-"
        model = ("yes" if all(r["counter"] == r["model_cycles"] for r in rs) else "NO") if fpga else "-"
        t_run, t_run_sd = 1e3 * mean(rs, "T_run_s"), 1e3 * sd(rs, "T_run_s")
        t_eval = mean(rs, "t_eval_s")
        run_txt = f"{t_run:.4f}" + (f" +-{t_run_sd:.4f}" if t_run_sd > 0 else "")
        total = f"{t_eval:.2f}" + (f" +-{sd(rs, 't_eval_s'):.2f}" if len(rs) > 1 else "")
        ratio = mean(rs, "approx_ratio")
        line = {"sim": sim, "mode": mode, "graph": graph, "graph_seed": gseed, "n": n, "p": p, "io_or_device": io,
                "runs": len(rs), "counter": counter, "counter_equals_model": model,
                "T_run_ms": t_run, "T_run_ms_sd": t_run_sd, "T_run_ms_min": 1e3 * min(values(rs, "T_run_s")),
                "t_eval_s_mean": t_eval, "t_eval_s_sd": sd(rs, "t_eval_s"),
                "t_load_s_mean": mean(rs, "t_load_s"), "t_exec_s_mean": mean(rs, "t_exec_s"),
                "t_read_s_mean": mean(rs, "t_read_s"), "delta_2_max": max(values(rs, "delta_2")),
                "delta_inf_max": max(values(rs, "delta_inf")), "approx_ratio": ratio if ratio is not None else "",
                "expectation": mean(rs, "expectation"), "gammas": rs[0]["gammas"]}
        table.append(line)
        print(f"{sim:5}{mode:7}{graph:9}{n:>3}{p:>4}{io:>16}{len(rs):>5}  {counter:>11} {model:>6}{run_txt:>20}"
              f"{total:>13}{fmt(line['t_load_s_mean'], '.2f'):>8}{fmt(line['t_read_s_mean'], '.2f'):>8}"
              f"{line['delta_2_max']:>10.1e}{fmt(ratio, '.4f'):>8}")
    write_csv(OUT / "summary_runs.csv", table)
    print("\ncounter = FPGA cycle count (\"varies!\" if repeats differ); model? = equals the driver's schedule;")
    print("T_run ms = compute time: FPGA counter / 320 MHz, or Aer run() + result() (+- spread over repeats);")
    print("total s = whole evaluation (FPGA: with UART transfer; Aer: with binding and transpile);")
    print("delta_2 = largest difference from the FP64 C++ reference; ratio = Max-Cut approximation ratio;")
    print("io/dev = driver, fast or fast+cost-once for the FPGA; CPU or GPU for Aer")
    return table


def show_compare(table):
    """One line per problem run on both simulators (same graph, n, p and angles)."""
    by_problem = {}
    for t in table:
        by_problem.setdefault((t["mode"], t["graph"], t["graph_seed"], t["n"], t["p"]), []).append(t)
    lines = []
    for key, ts in sorted(by_problem.items()):
        fpga = [t for t in ts if t["sim"] == "fpga"]
        fpga = [t for t in fpga if t["io_or_device"].startswith("fast")] or fpga     # prefer --fast-io
        for a in (t for t in ts if t["sim"] == "aer"):
            if not fpga:
                continue
            f = fpga[0]
            lines.append({"mode": key[0], "graph": key[1], "graph_seed": key[2], "n": key[3], "p": key[4],
                          "aer_device": a["io_or_device"], "fpga_io": f["io_or_device"],
                          # same problem: same angles and the same <cut> (so the same graph) to 1e-9
                          "same_problem": f["gammas"] == a["gammas"] and abs(f["expectation"] - a["expectation"]) < 1e-9,
                          "fpga_T_run_ms": f["T_run_ms"], "aer_T_run_ms": a["T_run_ms"],
                          "aer_T_run_ms_sd": a["T_run_ms_sd"], "speedup_compute": a["T_run_ms"] / f["T_run_ms"],
                          "fpga_t_eval_s": f["t_eval_s_mean"], "aer_t_eval_s": a["t_eval_s_mean"],
                          "speedup_per_evaluation": a["t_eval_s_mean"] / f["t_eval_s_mean"],
                          "fpga_delta_2": f["delta_2_max"], "aer_delta_2": a["delta_2_max"]})
    if not lines:
        return
    print("\nFPGA vs AER ON THE SAME PROBLEM  (speed-up = Aer time / FPGA time; > 1 means the FPGA is faster)\n")
    head = (f"{'graph':9}{'n':>3}{'p':>4}{'aer':>5}{'FPGA ms':>11}{'Aer ms':>11}{'compute x':>11}"
            f"{'FPGA s/ev':>11}{'Aer s/ev':>10}{'per-eval x':>11}{'FPGA d2':>10}{'Aer d2':>10}  same?")
    print(head)
    print("-" * len(head))
    for c in lines:
        print(f"{c['graph']:9}{c['n']:>3}{c['p']:>4}{c['aer_device']:>5}{c['fpga_T_run_ms']:>11.4f}"
              f"{c['aer_T_run_ms']:>11.4f}{c['speedup_compute']:>11.2f}{c['fpga_t_eval_s']:>11.3f}"
              f"{c['aer_t_eval_s']:>10.4f}{c['speedup_per_evaluation']:>11.4f}{c['fpga_delta_2']:>10.1e}"
              f"{c['aer_delta_2']:>10.1e}  {'yes' if c['same_problem'] else 'NO: angles or graph differ'}")
    write_csv(OUT / "summary_compare.csv", lines)
    print("\ncompute x = speed-up on compute time (FPGA counter vs Aer run() + result());")
    print("per-eval x = speed-up per whole evaluation (FPGA with UART transfer, Aer with transpile);")
    print("d2 = delta_2 against the FP64 C++ reference (the 80-bit check uses the data.npz files);")
    print("same? = same angles and the same <cut> on both, i.e. the same problem was run")


def show_optimise(rows):
    print(f"\nOPTIMISER RUNS  (results/simple/optimise_summary.csv, {len(rows)} runs)\n")
    head = (f"{'sim':5}{'graph':9}{'n':>3}{'p':>4}{'io/dev':>16}{'seed':>5}{'evals':>6}{'best ratio':>11}{'at eval':>8}"
            f"{'=C++ to':>10}{'minutes':>9}{'s/eval':>9}{'COBYLA s':>9}")
    print(head)
    print("-" * len(head))
    table = []
    for r in sorted(rows, key=lambda r: (graph_label(r), int(r["NQ"]), int(r["Np"]), sim_of(r), how(r), int(r["seed"]))):
        nfev = int(r["nfev"])
        line = {"sim": sim_of(r), "graph": graph_label(r), "n": int(r["NQ"]), "p": int(r["Np"]), "io_or_device": how(r),
                "seed": int(r["seed"]),
                "evals": nfev, "best_approx_ratio": r["best_approx_ratio"], "best_eval": int(r["best_eval"]) + 1,
                "max_abs_diff_vs_cpp": float(r["max_abs_diff_fpga_cpp"]), "wall_min": float(r["wall_s"]) / 60,
                "t_eval_per_eval_s": float(r["sum_t_eval_s"]) / nfev,
                "T_run_per_eval_s": float(r["sum_T_run_s"]) / nfev, "t_optimiser_s": float(r["t_optimiser_s"])}
        table.append(line)
        ratio = f"{float(r['best_approx_ratio']):.4f}" if r["best_approx_ratio"] else "-"
        print(f"{line['sim']:5}{line['graph']:9}{line['n']:>3}{line['p']:>4}{line['io_or_device']:>16}{line['seed']:>5}"
              f"{nfev:>6}{ratio:>11}{line['best_eval']:>8}{line['max_abs_diff_vs_cpp']:>10.1e}{line['wall_min']:>9.1f}"
              f"{line['t_eval_per_eval_s']:>9.3f}{line['t_optimiser_s']:>9.2f}")
    write_csv(OUT / "summary_optimise.csv", table)
    print("\nbest ratio = best Max-Cut approximation ratio found; =C++ to = largest energy difference from")
    print("the C++ reference over all evaluations; s/eval = whole evaluation (see SINGLE RUNS);")
    print("COBYLA s = time spent in the optimiser itself; io/dev = driver, fast, fast+cost-once")
    print("(cost diagonal sent only at the first evaluation) for the FPGA, CPU or GPU for Aer")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="readable tables from results/simple")
    ap.add_argument("--today", action="store_true", help="only today's runs")
    a = ap.parse_args()
    runs, opts = read("runs.csv", a.today), read("optimise_summary.csv", a.today)
    if runs:
        show_compare(show_runs(runs))
    if opts:
        show_optimise(opts)
    if not runs and not opts:
        print("no results yet in results/simple")