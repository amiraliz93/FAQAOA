#!/usr/bin/env python3
import argparse
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter


def power_of_ten_formatter(y, pos):
    """Show left y-axis labels exactly as 10^i for integer i."""
    if y <= 0:
        return ""
    exponent = int(round(math.log10(y)))
    if math.isclose(y, 10 ** exponent, rel_tol=1e-10, abs_tol=0.0):
        return rf"$10^{{{exponent}}}$"
    return ""


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Plot average cputime and FPGA time against NQ with faint average ± std bands "
            "on the left log y-axis, cpu/FPGA ratio on a second right y-axis, major plus "
            "secondary y-axis grid lines, and legend below the graph."
        )
    )
    parser.add_argument("input_csv", help="Input CSV file, e.g. statistics_summary.csv")
    parser.add_argument(
        "output_svg",
        nargs="?",
        default="out.svg",
        help="Output SVG file.",
    )
    parser.add_argument("--exp-min", type=int, default=None, help="Optional minimum left y-axis exponent.")
    parser.add_argument("--exp-max", type=int, default=None, help="Optional maximum left y-axis exponent.")
    parser.add_argument("--alpha", type=float, default=0.18, help="Transparency of std bands. Default: 0.18")
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv)
    required = ["NQ", "cputime.ave", "cputime.std", "FPGA_time.ave", "FPGA_time.std", "cpu/FPGA"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    x = pd.to_numeric(df["NQ"], errors="coerce").to_numpy(dtype=float)
    series = [("cputime", "cputime.ave", "cputime.std"), ("FPGA_time", "FPGA_time.ave", "FPGA_time.std")]

    fig, ax_time = plt.subplots()
    positive_values_for_limits = []
    handles, labels = [], []

    for label, ave_col, std_col in series:
        ave = pd.to_numeric(df[ave_col], errors="coerce").to_numpy(dtype=float)
        std = pd.to_numeric(df[std_col], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(x) & np.isfinite(ave) & (ave > 0)
        if not mask.any():
            continue

        line, = ax_time.plot(x[mask], ave[mask], marker="o", label=f"{label}.ave")
        color = line.get_color()
        handles.append(line)
        labels.append(f"{label}.ave")
        positive_values_for_limits.extend(ave[mask].tolist())

        std_clean = np.where(np.isfinite(std), std, 0.0)
        lower = ave - std_clean
        upper = ave + std_clean
        band_mask = mask & np.isfinite(lower) & np.isfinite(upper) & (upper > 0)
        if band_mask.any() and np.any(std_clean[band_mask] > 0):
            positive_candidates = np.concatenate([ave[mask], upper[band_mask]])
            positive_candidates = positive_candidates[positive_candidates > 0]
            min_positive = positive_candidates.min() if positive_candidates.size else ave[mask].min()
            lower_clipped = np.maximum(lower[band_mask], min_positive * 1e-3)
            band = ax_time.fill_between(
                x[band_mask], lower_clipped, upper[band_mask],
                color=color, alpha=args.alpha, linewidth=0, label=f"{label}.ave ± std"
            )
            handles.append(band)
            labels.append(f"{label}.ave ± std")
            positive_values_for_limits.extend(lower_clipped.tolist())
            positive_values_for_limits.extend(upper[band_mask].tolist())

    if not positive_values_for_limits:
        raise ValueError("No positive average values were found to plot on a logarithmic axis.")

    ax_time.set_yscale("log", base=10)
    data_exp_min = math.floor(math.log10(min(v for v in positive_values_for_limits if v > 0)))
    data_exp_max = math.ceil(math.log10(max(positive_values_for_limits)))
    exp_min = data_exp_min if args.exp_min is None else args.exp_min
    exp_max = data_exp_max if args.exp_max is None else args.exp_max
    if exp_min > exp_max:
        raise ValueError("exp_min must be <= exp_max")

    exponents = list(range(exp_min, exp_max + 1))
    yticks = [10.0 ** i for i in exponents]
    ax_time.set_ylim(10.0 ** exp_min, 10.0 ** exp_max)
    ax_time.yaxis.set_major_locator(FixedLocator(yticks))
    ax_time.yaxis.set_major_formatter(FuncFormatter(power_of_ten_formatter))
    ax_time.yaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10) * 0.1))
    ax_time.yaxis.set_minor_formatter(NullFormatter())

    ax_ratio = ax_time.twinx()
    ratio = pd.to_numeric(df["cpu/FPGA"], errors="coerce").to_numpy(dtype=float)
    ratio_mask = np.isfinite(x) & np.isfinite(ratio)
    if ratio_mask.any():
        ratio_line, = ax_ratio.plot(x[ratio_mask], ratio[ratio_mask], marker="s", linestyle="--", label="cpu/FPGA")
        handles.append(ratio_line)
        labels.append("cpu/FPGA")
        ratio_min, ratio_max = ratio[ratio_mask].min(), ratio[ratio_mask].max()
        margin = 0.05 * (ratio_max - ratio_min) if ratio_max > ratio_min else 0.1
        ax_ratio.set_ylim(ratio_min - margin, ratio_max + margin)

    nq_values = sorted(pd.Series(x).dropna().unique())
    ax_time.set_xticks(nq_values)
    ax_time.grid(True, which="major", axis="y")
    ax_time.grid(True, which="minor", axis="y", alpha=0.3)
    ax_time.grid(True, which="major", axis="x")

    ax_time.set_xlabel("number of qbits")
    ax_time.set_ylabel(r"$\log_{10}(\mathrm{time}/[s])$")
    ax_ratio.set_ylabel("cpu/FPGA")
    ax_time.set_title("Execution time and cpu/FPGA ratio vs number of qbits")

    # Put the legend outside the graph region, centered below the axes.
    # The subplots_adjust call reserves space at the bottom, avoiding overlap.
    fig.subplots_adjust(bottom=0.27)
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.02),
        ncol=2,
        frameon=True,
    )

    fig.savefig(args.output_svg, format="svg", bbox_inches="tight")


if __name__ == "__main__":
    main()
