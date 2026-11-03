#!/usr/bin/env python3

import re
import math
import statistics
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter

xAxis = "NP"
xTitle = "Number of layers"
def power_of_ten_formatter(y, pos):
    if y <= 0:
        return ""

    e = int(round(math.log10(y)))

    if math.isclose(y, 10**e, rel_tol=1e-10):
        return rf"$10^{{{e}}}$"

    return ""


def parse_statistics(path):
    records = []

    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"

    pattern = re.compile(
        rf"^(NQ|NP|NS|cputime|qiskit1.6GHz|qiskit3.2GHz|qiskit@5.7GHz|FPGA time|MAE):\s*({number})"
    )

    current = None

    with open(path, "r", encoding="utf-8") as f:

        for line in f:
            line = line.strip()

            if "summary of the computation" in line:

                if (
                    current is not None
                    and {"NQ", "NP", "NS"} <= current.keys()
                ):
                    records.append(current)

                current = {}
                continue

            if current is None:
                continue

            m = pattern.match(line)

            if not m:
                continue

            key, value = m.group(1), m.group(2)

            if key in ("NQ", "NP", "NS"):
                current[key] = int(float(value))

            elif key == "cputime":
                current["cputime"] = float(value)

            elif key == "qiskit1.6GHz":
                current["qiskit1.6GHz"] = float(value)

            elif key == "qiskit3.2GHz":
                current["qiskit3.2GHz"] = float(value)

            elif key == "qiskit@5.7GHz":
                current["qiskit@5.7GHz"] = float(value)

            elif key == "FPGA time":
                current["FPGA_time"] = float(value)

            elif key == "MAE":
                current["MAE"] = float(value)

    if (
        current is not None
        and {"NQ", "NP", "NS"} <= current.keys()
    ):
        records.append(current)

    return records


def make_summary(records, sample_std=False):
    groups = defaultdict(
        lambda: {
            "cputime": [],
            "qiskit1.6GHz": [],
            "qiskit3.2GHz": [],
            "qiskit@5.7GHz": [],
            "FPGA_time": [],
            "MAE": [],
        }
    )

    for r in records:

        N = r[xAxis]

        for key in (
            "cputime",
            "qiskit1.6GHz",
            "qiskit3.2GHz",
            "qiskit@5.7GHz",
            "FPGA_time",
            "MAE",
        ):
            if key in r:
                groups[N][key].append(r[key])

    rows = []

    for N in sorted(groups):

        row = {}
        row[xAxis] = N

        for metric in (
            "cputime",
            "qiskit1.6GHz",
            "qiskit3.2GHz",
            "qiskit@5.7GHz",
            "FPGA_time",
            "MAE",
        ):

            vals = groups[N][metric]

            if not vals:
                row[f"{metric}.ave"] = np.nan
                row[f"{metric}.std"] = np.nan
                continue

            row[f"{metric}.ave"] = statistics.mean(vals)

            if sample_std:
                row[f"{metric}.std"] = (
                    statistics.stdev(vals)
                    if len(vals) > 1 else 0.0
                )
            else:
                row[f"{metric}.std"] = (
                    statistics.pstdev(vals)
                    if len(vals) > 1 else 0.0
                )

        fpga = row["FPGA_time.ave"]

        if (
            np.isfinite(fpga)
            and fpga > 0
            and np.isfinite(row["cputime.ave"])
        ):
            row["FPGA/CPU@3.2GHz"] = fpga/row["cputime.ave"] 
        else:
            row["FPGA/CPU@3.2GHz"] = np.nan

        if (
            np.isfinite(fpga)
            and fpga > 0
            and np.isfinite(row["qiskit1.6GHz.ave"])
        ):
            row["FPGA/qiskit@1.6GHz"] = fpga/row["qiskit1.6GHz.ave"]
        else:
            row["FPGA/qiskit@1.6GHz"] = np.nan

        rows.append(row)

    return pd.DataFrame(rows)


def plot_summary(df, output_svg,
                 exp_min=None,
                 exp_max=None,
                 alpha=0.18):

    x = pd.to_numeric(
        df[xAxis],
        errors="coerce"
    ).to_numpy(dtype=float)

    fig, ax_time = plt.subplots()

    handles = []
    labels = []

    positive_values = []

    series = [
        ("qiskit1.6GHz", "qiskit1.6GHz.ave", "qiskit1.6GHz.std"),
        ("qiskit3.2GHz", "qiskit3.2GHz.ave", "qiskit3.2GHz.std"),
        ("qiskit@5.7GHz", "qiskit@5.7GHz.ave", "qiskit@5.7GHz.std"),
        ("FPGA_time", "FPGA_time.ave", "FPGA_time.std")
    ]
    makers = {
        "qiskit1.6GHz": "x",
        "qiskit3.2GHz": "o",
        "qiskit@5.7GHz": "s",
        "FPGA_time": "+",
    }
    labelsd = {
        "qiskit1.6GHz": "qiskit@1.6GHz",
        "qiskit3.2GHz": "qiskit@3.2GHz",
        "qiskit@5.7GHz": "qiskit@5.7GHz",
        "FPGA_time": "FPGA",
    }

    for label, ave_col, std_col in series:

        ave = pd.to_numeric(
            df[ave_col],
            errors="coerce"
        ).to_numpy(dtype=float)

        std = pd.to_numeric(
            df[std_col],
            errors="coerce"
        ).to_numpy(dtype=float)

        mask = (
            np.isfinite(x)
            & np.isfinite(ave)
            & (ave > 0)
        )

        if not mask.any():
            continue

        line, = ax_time.plot(
            x[mask],
            ave[mask],
            marker=makers[label],
            label=f"{labelsd[label]}",
            linewidth = 0.5
        )

        color = line.get_color()

        handles.append(line)
        labels.append(f"{labelsd[label]}")

        positive_values.extend(
            ave[mask].tolist()
        )

        std = np.where(
            np.isfinite(std),
            std,
            0.0
        )

        lower = ave - std
        upper = ave + std

        band_mask = (
            mask
            & np.isfinite(lower)
            & np.isfinite(upper)
            & (upper > 0)
        )

        if (
            band_mask.any()
            and np.any(std[band_mask] > 0)
        ):

            min_positive = np.min(
                np.concatenate(
                    [
                        ave[mask],
                        upper[band_mask]
                    ]
                )
            )

            lower_clip = np.maximum(
                lower[band_mask],
                min_positive * 1e-3
            )

            # band = ax_time.fill_between(
            #     x[band_mask],
            #     lower_clip,
            #     upper[band_mask],
            #     color=color,
            #     alpha=alpha,
            #     linewidth=0
            # )

            # handles.append(band)
            # labels.append(
            #     f"{labelsd[label]} ± std"
            # )

            # positive_values.extend(
            #     lower_clip.tolist()
            # )

            # positive_values.extend(
            #     upper[band_mask].tolist()
            # )

    if not positive_values:
        raise RuntimeError(
            "No positive values found."
        )

    ax_time.set_yscale(
        "log",
        base=10
    )

    data_exp_min = math.floor(
        math.log10(
            min(v for v in positive_values if v > 0)
        )
    )

    data_exp_max = math.ceil(
        math.log10(max(positive_values))
    )

    exp_min = (
        data_exp_min
        if exp_min is None
        else exp_min
    )

    exp_max = (
        data_exp_max
        if exp_max is None
        else exp_max
    )

    yticks = [
        10.0**i
        for i in range(exp_min, exp_max + 1)
    ]

    ax_time.set_ylim(
        10.0**exp_min,
        10.0**exp_max
    )

    ax_time.yaxis.set_major_locator(
        FixedLocator(yticks)
    )

    ax_time.yaxis.set_major_formatter(
        FuncFormatter(
            power_of_ten_formatter
        )
    )

    ax_time.yaxis.set_minor_locator(
        LogLocator(
            base=10,
            subs=np.arange(2, 10) * 0.1
        )
    )

    ax_time.yaxis.set_minor_formatter(
        NullFormatter()
    )

    # ax_ratio = ax_time.twinx()

    # ratio_values = []

    # ratio_series = [
    #    # ("FPGA/qiskit@1.6GHz", ":", "^"),
    # ]

    # for name, linestyle, marker in ratio_series:

    #     ratio = pd.to_numeric(
    #         df[name],
    #         errors="coerce"
    #     ).to_numpy(dtype=float)

    #     mask = (
    #         np.isfinite(x)
    #         & np.isfinite(ratio)
    #     )

    #     if not mask.any():
    #         continue

    #     line, = ax_ratio.plot(
    #         x[mask],
    #         ratio[mask],
    #         linestyle=linestyle,
    #         marker=marker,
    #         label=name
    #     )

    #     handles.append(line)
    #     labels.append(name)

    #     ratio_values.extend(
    #         ratio[mask].tolist()
    #     )

    # if ratio_values:

    #     ratio_min = 0 # min(ratio_values)
    #     ratio_max = max(ratio_values)

    #     margin = (
    #         0.05 * (ratio_max - ratio_min)
    #         if ratio_max > ratio_min
    #         else 0.1
    #     )

    #     ax_ratio.set_ylim(
    #         ratio_min - margin,
    #         ratio_max + margin
    #     )

    ax_time.set_xticks(
        sorted(
            pd.Series(x)
            .dropna()
            .unique()
        )
    )

    ax_time.grid(
        True,
        which="major",
        axis="y"
    )

    ax_time.grid(
        True,
        which="minor",
        axis="y",
        alpha=0.3
    )

    ax_time.grid(
        True,
        which="major",
        axis="x"
    )

    ax_time.set_xlabel(
        xTitle
    )

    ax_time.set_ylabel(
        "$\log_{10}(t/\mathrm{s})$"
    )

    # ax_ratio.set_ylabel(
    #     "ratio to FPGA"
    # )


    fig.subplots_adjust(
        bottom=0.30
    )

    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.02),
        ncol=4,
        frameon=True,
    )

    fig.savefig(
        output_svg,
        format="svg",
        bbox_inches="tight"
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Read statistics.txt and generate SVG directly."
        )
    )

    parser.add_argument(
        "input_file",
        help="statistics.txt"
    )

    parser.add_argument(
        "output_svg",
        nargs="?",
        default="out.svg"
    )

    parser.add_argument(
        "--sample-std",
        action="store_true"
    )

    parser.add_argument(
        "--exp-min",
        type=int,
        default=None
    )

    parser.add_argument(
        "--exp-max",
        type=int,
        default=None
    )

    parser.add_argument(
        "--alpha",
        type=float,
        default=0.18
    )

    args = parser.parse_args()

    records = parse_statistics(
        args.input_file
    )

    if not records:
        raise RuntimeError(
            "No summary blocks found."
        )

    df = make_summary(
        records,
        sample_std=args.sample_std
    )

    plot_summary(
        df,
        args.output_svg,
        exp_min=args.exp_min,
        exp_max=args.exp_max,
        alpha=args.alpha
    )


if __name__ == "__main__":
    main()