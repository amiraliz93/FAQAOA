#!/usr/bin/env python3

import math
import re
from collections import defaultdict

import numpy as np
import matplotlib.pyplot as plt

from matplotlib.ticker import (
    FixedLocator,
    FuncFormatter,
    LogLocator,
    NullFormatter,
)

INPUT_FILE = "statistics.txt"
OUTPUT_FILE = "CN-P.svg"

BLOCK_HEADER = "summary of the computation"

# Fields used for grouping/metadata only.
EXCLUDED_KEYS = {"NQ", "NP", "NS", "MAE", "cputime"}


def parse_value(value_text):
    """
    Extract the first numeric value from a string.

    Examples:
        "1.2 s"      -> 1.2
        "2.4e-06"    -> 2.4e-06
        "123 xyz"    -> 123.0
    """
    m = re.search(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
        value_text,
    )

    if m is None:
        return None

    return float(m.group(0))


def parse_blocks(filename):
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    parts = text.split(BLOCK_HEADER)

    blocks = []

    for part in parts[1:]:
        block = {}

        for line in part.splitlines():
            line = line.strip()

            if ":" not in line:
                continue

            key, value = line.split(":", 1)

            key = key.strip()
            value = value.strip()

            num = parse_value(value)

            if num is not None:
                block[key] = num

        if "NQ" in block and "NP" in block:
            blocks.append(block)

    return blocks


def power_of_ten_formatter(x, pos):
    if x <= 0:
        return ""

    exp = round(math.log10(x))

    if math.isclose(
        x,
        10.0**exp,
        rel_tol=1e-12,
        abs_tol=0.0,
    ):
        return rf"$10^{{{int(exp)}}}$"

    return ""


def main():
    blocks = parse_blocks(INPUT_FILE)

    # Collect all plot-target records X.
    x_names = set()

    for block in blocks:
        for key in block:
            if key not in EXCLUDED_KEYS:
                x_names.add(key)

    #
    # L_{X,N,P}
    #
    values = defaultdict(list)

    for block in blocks:
        N = int(block["NQ"])
        P = int(block["NP"])

        for X in x_names:
            if X in block:
                values[(X, N, P)].append(block[X])

    fig, ax = plt.subplots(figsize=(8, 6))

    series_keys = sorted(
        {
            (X, N)
            for (X, N, P) in values.keys()
        },
        key=lambda t: (t[0], t[1]),
    )

    positive_values = []
    dicN = {}
    dicN[str(5)] = "x"
    dicN[str(10)] = "o"
    dicN[str(16)] = "s"
    codN = {}
    codN["FPGA"] = "x"
    codN["qiskit"] = "s"

    col2 = {}
    col2["FPGA"] = [
        '#0000ff', '#0000ee', '#0000dd', '#0000cc', 
        '#0000bb', '#0000aa', '#000099', '#000088', 
        '#000077', '#000066', '#000055', '#000044', 
        '#000033', '#000022', '#000011', '#000000'
    ]
    col2["qiskit"] = [
        '#ff0000', '#f90303', '#f30606', '#ed0808', 
        '#e70b0b', '#e10e0e', '#db1111', '#d51414', 
        '#cf1616', '#c91919', '#c31c1c', "#8d1616", 
        '#b72222', "#7a2020", "#6b1111", "#3a0000"
    ]
    for X, N in series_keys:
        p_values = sorted(
            {
                P
                for (x, n, P) in values.keys()
                if x == X and n == N
            }
        )

        xs = []
        ys = []

        for P in p_values:
            L = values[(X, N, P)]

            if not L:
                continue

            A = sum(L) / len(L)

            xs.append(P)
            ys.append(A)

            if A > 0:
                positive_values.append(A)

        if xs:
            ax.plot(
                xs,
                ys,
                marker=codN[X],
                label=X + str(N),
                linewidth = 0.5,
                color = col2[X][N-1]
            )

    #
    # Axis titles
    #
    ax.set_xlabel("$\log_{10}(P)$")
    ax.set_ylabel("$\log_{10}(t/\mathrm{s})$")

    #
    # Log10 y-axis
    #
    ax.set_yscale(
        "log",
        base=10,
    )
    ax.set_xscale(
        "log",
        base=10,
    )

    if positive_values:
        data_exp_min = math.floor(
            math.log10(min(positive_values))
        )

        data_exp_max = math.ceil(
            math.log10(max(positive_values))
        )

        yticks = [
            10.0**i
            for i in range(
                data_exp_min,
                data_exp_max + 1,
            )
        ]

        ax.set_ylim(
            10.0**data_exp_min,
            10.0**data_exp_max,
        )

        ax.yaxis.set_major_locator(
            FixedLocator(yticks)
        )

        ax.yaxis.set_major_formatter(
            FuncFormatter(
                power_of_ten_formatter
            )
        )

        ax.yaxis.set_minor_locator(
            LogLocator(
                base=10,
                subs=np.arange(2, 10) * 0.1,
            )
        )

        ax.yaxis.set_minor_formatter(
            NullFormatter()
        )

    #
    # Grid
    #
    ax.grid(
        which="major",
        axis="y",
        linestyle="-",
        linewidth=0.8,
    )

    ax.grid(
        which="minor",
        axis="y",
        linestyle=":",
        linewidth=0.5,
    )

    ax.grid(
        which="major",
        axis="x",
        linestyle="-",
        linewidth=0.8,
    )

    ax.legend(loc="lower center",ncol=6,bbox_to_anchor=(0.5, -0.3),frameon=True,)
    
    # ax.legend(
    #     handles,
    #     labels,
    #     loc="lower center",
    #     bbox_to_anchor=(0.5, 0.02),
    #     ncol=4,
    #     frameon=True,
    # )

    fig.tight_layout()

    plt.savefig(
        OUTPUT_FILE,
        format="svg",
    )


if __name__ == "__main__":
    main()