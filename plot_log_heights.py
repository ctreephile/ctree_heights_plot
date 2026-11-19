#!/usr/bin/env python3
"""
Logarithmic Horizontal Axis Heights Plotter (Log-Linear Straight-Line Visualizer).

Demonstrates and visualizes the mathematical theorem in `docs/HANDOFF.md` Section 3(3):
  - For any seed `a` not divisible by `d = p - 1`, the geometric progression
    `n_k = a * d^k` (k = 0, 1, 2, ...) satisfies:
        h(n_k) = h(a) + k = log_d(n_k) + C_a,   where C_a = h(a) - log_d(a).
  - When plotted with a logarithmic horizontal axis x = log_d(N) (or log10(N)),
    every logarithmic curve in the standard plot transforms into an EXACT
    parallel straight line of slope 1 (in base d), and nodes that share the
    same expansion jump count `K` form dense parallel straight-line highways
    separated vertically by ΔC ≈ 1 + log_d(p).

Generates:
  1. `data/p5/log_linear_comparison_p5_3_2_1.png`:
     Side-by-side comparison of Linear-X vs. Log-X for p=5, Q=[_, 3, 2, 1]
     with highlighted straight-line spines `n_k = a * 4^k`.
  2. `data/p5/log_linear_showcase_p3_p4_p5.png`:
     Multi-system showcase (p=3 `3n+1`, p=4 `Q=[_,2,1]`, p=5 `Q=[_,3,2,1]`,
     and an egalitarian p=5 system) on log-scaled horizontal axes.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from backend.engine import (
    DEFAULT_PALETTE,
    canonicalize_cycle,
    format_loop_label,
    step_pq,
    validate_pq,
)


def evaluate_system_points(
    p: int,
    q_norm: List[Optional[int]],
    max_n: int = 100000,
    max_steps: int = 10000,
) -> Dict[str, Any]:
    """Evaluate n = 1..max_n for any (p, Q) and return loops and step arrays."""
    v = validate_pq(p, q_norm)
    if not v["valid"]:
        raise ValueError(f"Invalid (p={p}, Q={q_norm}): {v['errors']}")
    q_clean = v["q_normalized"]
    d = p - 1

    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops_by_min: Dict[int, Dict[str, Any]] = {}
    next_lid = 1

    for start_n in range(1, max_n + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_idx: Dict[int, int] = {}
        curr = start_n
        while curr not in steps_cache and curr not in path_idx and len(path) <= max_steps:
            path_idx[curr] = len(path)
            path.append(curr)
            curr = step_pq(curr, p, d, q_clean)

        if curr in steps_cache:
            tlid, bst = steps_cache[curr]
            plen = len(path)
            if tlid == 0 or bst < 0:
                for val in path:
                    steps_cache[val] = (0, -1)
            else:
                for idx, val in enumerate(path):
                    steps_cache[val] = (tlid, bst + (plen - idx))
        elif curr in path_idx:
            cstart = path_idx[curr]
            rcycle = path[cstart:]
            cmembers = canonicalize_cycle(rcycle)
            mval = cmembers[0]
            if mval not in loops_by_min:
                lid = next_lid
                next_lid += 1
                loops_by_min[mval] = {
                    "raw_id": lid,
                    "min_value": mval,
                    "length": len(cmembers),
                    "members": cmembers,
                }
            else:
                lid = loops_by_min[mval]["raw_id"]
            for val in rcycle:
                steps_cache[val] = (lid, 0)
            for idx in range(cstart):
                steps_cache[path[idx]] = (lid, cstart - idx)
        else:
            steps_cache[start_n] = (0, -1)

    sorted_loops = sorted(loops_by_min.values(), key=lambda x: x["min_value"])
    raw_to_rank = {lp["raw_id"]: i + 1 for i, lp in enumerate(sorted_loops)}

    pts_n = list(range(1, max_n + 1))
    pts_steps = [0] * max_n
    pts_lid = [0] * max_n
    max_obs = 0

    for idx, n_val in enumerate(pts_n):
        rlid, st = steps_cache[n_val]
        if rlid == 0 or st < 0:
            pts_lid[idx] = 0
            pts_steps[idx] = -1
        else:
            rk = raw_to_rank[rlid]
            pts_lid[idx] = rk
            pts_steps[idx] = st
            if st > max_obs:
                max_obs = st

    loops_info = []
    for i, lp in enumerate(sorted_loops):
        rk = i + 1
        loops_info.append(
            {
                "loop_id": rk,
                "min_value": lp["min_value"],
                "length": lp["length"],
                "members": lp["members"],
                "label": format_loop_label(rk, lp["members"]),
                "color": DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
            }
        )

    return {
        "p": p,
        "d": d,
        "q": q_clean,
        "max_n": max_n,
        "max_steps": max_obs,
        "loops": loops_info,
        "n": pts_n,
        "steps": pts_steps,
        "loop_id": pts_lid,
        "steps_map": {n_v: st_v for n_v, st_v in zip(pts_n, pts_steps)},
    }


def select_representative_seeds(
    res: Dict[str, Any],
    num_seeds: int = 6,
) -> List[int]:
    """
    Pick representative seeds `a` (with a % d != 0 and small enough to have many
    powers a * d^k <= max_n) that span different vertical intercepts C_a.
    """
    d = res["d"]
    max_n = res["max_n"]
    steps_map = res["steps_map"]

    candidates = []
    for a in range(1, min(250, max_n // (d ** 3) + 1)):
        if a % d == 0:
            continue
        h_a = steps_map.get(a, -1)
        if h_a <= 0:
            continue
        intercept = h_a - math.log(a, d)
        candidates.append((intercept, a))

    candidates.sort(key=lambda x: x[0])
    if len(candidates) <= num_seeds:
        return [c[1] for c in candidates]

    indices = np.linspace(0, len(candidates) - 1, num_seeds, dtype=int)
    return [candidates[i][1] for i in indices]


def plot_linear_vs_log_comparison(
    p: int,
    q_norm: List[Optional[int]],
    max_n: int = 100000,
    out_path: Path = Path("data/p5/log_linear_comparison_p5_3_2_1.png"),
) -> Path:
    """
    Render a 2-panel comparison figure:
      - Left:  Standard Linear-X scale (`N`) where `n_k = a * d^k` form logarithmic curves.
      - Right: Logarithmic-X scale (`N` on log_d axis) where the exact same nodes
               align onto parallel straight lines `h(n) = log_d(n) + C_a` of slope 1!
    """
    res = evaluate_system_points(p=p, q_norm=q_norm, max_n=max_n)
    d = res["d"]
    loops = res["loops"]
    pts_n = res["n"]
    pts_steps = res["steps"]
    pts_lid = res["loop_id"]
    steps_map = res["steps_map"]

    seeds = select_representative_seeds(res, num_seeds=6)
    seed_colors = ["#dc2626", "#16a34a", "#7c3aed", "#d97706", "#0284c7", "#db2777"]

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif", "STIXGeneral"],
            "mathtext.fontset": "stix",
        }
    )

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(18.0, 7.5), dpi=200)

    # Group points by loop
    xs_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
    ys_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
    for n_v, st_v, lid_v in zip(pts_n, pts_steps, pts_lid):
        if lid_v in xs_by_loop and st_v >= 0:
            xs_by_loop[lid_v].append(n_v)
            ys_by_loop[lid_v].append(st_v)

    q_str = "[" + ", ".join("_" if x is None else str(x) for x in res["q"]) + "]"

    for ax, is_log in ((ax_lin, False), (ax_log, True)):
        # Plot all 100,000 background nodes
        for lp in loops:
            lid = lp["loop_id"]
            ax.plot(
                xs_by_loop[lid],
                ys_by_loop[lid],
                linestyle="none",
                marker="o",
                markersize=2.0,
                markerfacecolor=lp["color"],
                markeredgecolor="none",
                alpha=0.32,
                label=lp["label"] if not is_log else None,
            )

        # Overlay highlighted geometric sequences n_k = a * d^k and exact guide lines
        for idx, (a, scol) in enumerate(zip(seeds, seed_colors)):
            seq_x = []
            seq_y = []
            k = 0
            while True:
                nk = a * (d ** k)
                if nk > max_n:
                    break
                hk = steps_map.get(nk, -1)
                if hk >= 0:
                    seq_x.append(nk)
                    seq_y.append(hk)
                k += 1

            if len(seq_x) >= 2:
                h_a = steps_map[a]
                c_a = h_a - math.log(a, d)
                # Smooth theoretical curve / straight line
                x_dense = np.logspace(math.log10(a), math.log10(max_n), 300)
                y_dense = np.log(x_dense) / math.log(d) + c_a
                ax.plot(
                    x_dense,
                    y_dense,
                    linestyle="--",
                    linewidth=1.5,
                    color=scol,
                    alpha=0.85,
                )
                ax.plot(
                    seq_x,
                    seq_y,
                    linestyle="none",
                    marker="o",
                    markersize=5.5,
                    markerfacecolor=scol,
                    markeredgecolor="white",
                    markeredgewidth=0.7,
                    zorder=5,
                    label=(
                        f"Seed a={a}: n={a}·{d}^k  "
                        f"[h(n) = log_{d}(n) {c_a:+.2f}, {len(seq_x)} pts]"
                    ),
                )

        if is_log:
            ax.set_xscale("log", base=d)
            ax.set_xlim(1, max_n)
            ax.set_xlabel(f"N  (Logarithmic scale base d = {d}: powers {d}^k are equally spaced)", fontsize=13)
            ax.set_title(
                f"[Log-X Scale]  (p, Q) = ({p}, {q_str})\n"
                f"Every curve becomes a parallel STRAIGHT LINE:  h(n) = log_{d}(n) + C_a",
                fontsize=13.5,
                fontweight="bold",
            )
        else:
            ax.set_xlim(0, max_n)
            ax.set_xlabel("N  (Standard Linear scale)", fontsize=13)
            ax.set_title(
                f"[Linear-X Scale]  (p, Q) = ({p}, {q_str})\n"
                f"Nodes form bundles of LOGARITHMIC CURVES:  h(n) = log_{d}(n) + C_a",
                fontsize=13.5,
                fontweight="bold",
            )

        ax.set_ylabel("Height h(n) (iterN)", fontsize=13)
        ax.set_ylim(0, int(res["max_steps"] * 1.15))
        ax.grid(True, which="both", linestyle=":", linewidth=0.6, color="#64748b", alpha=0.45)
        ax.legend(loc="upper left", fontsize=8.8, framealpha=0.92)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def plot_multi_system_log_showcase(
    out_path: Path = Path("data/p5/log_linear_showcase_p3_p4_p5.png"),
    max_n: int = 100000,
) -> Path:
    """
    Render a 2x2 showcase of log-X height plots across p=3, p=4, and p=5
    showing how all nodes align on parallel straight lines of slope 1/ln(d)
    and how the vertical layer spacing ΔC = 1 + log_d(p) appears as parallel bands.
    """
    configs = [
        (3, [None, 1], "Classic 3n+1 (p=3, d=2, Q=[_, 1])"),
        (4, [None, 2, 1], "p=4 Base System (p=4, d=3, Q=[_, 2, 1])"),
        (5, [None, 3, 2, 1], "p=5 Base System (p=5, d=4, Q=[_, 3, 2, 1])"),
        (5, [None, 11, 22, 33], "p=5 Resonance System (p=5, d=4, Q=[_, 11, 22, 33])"),
    ]

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif", "STIXGeneral"],
            "mathtext.fontset": "stix",
        }
    )

    fig, axes = plt.subplots(2, 2, figsize=(18.0, 12.0), dpi=200)
    flat_axes = axes.flatten()

    for ax, (p, q_in, title_label) in zip(flat_axes, configs):
        res = evaluate_system_points(p=p, q_norm=q_in, max_n=max_n)
        d = res["d"]
        loops = res["loops"]
        pts_n = res["n"]
        pts_steps = res["steps"]
        pts_lid = res["loop_id"]
        steps_map = res["steps_map"]

        xs_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
        ys_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
        for n_v, st_v, lid_v in zip(pts_n, pts_steps, pts_lid):
            if lid_v in xs_by_loop and st_v >= 0:
                xs_by_loop[lid_v].append(n_v)
                ys_by_loop[lid_v].append(st_v)

        for lp in loops:
            lid = lp["loop_id"]
            ax.plot(
                xs_by_loop[lid],
                ys_by_loop[lid],
                linestyle="none",
                marker="o",
                markersize=2.1,
                markerfacecolor=lp["color"],
                markeredgecolor="none",
                alpha=0.55,
                label=lp["label"],
            )

        # Draw 4 reference parallel straight lines h(n) = log_d(n) + C_a
        seeds = select_representative_seeds(res, num_seeds=4)
        for a in seeds:
            h_a = steps_map[a]
            c_a = h_a - math.log(a, d)
            x_line = np.array([1.0, float(max_n)])
            y_line = np.log(x_line) / math.log(d) + c_a
            ax.plot(
                x_line,
                y_line,
                linestyle="--",
                linewidth=1.3,
                color="#1e293b",
                alpha=0.75,
            )

        delta_c = 1.0 + math.log(p, d)
        ax.set_xscale("log", base=10)
        ax.set_xlim(1, max_n)
        ax.set_ylim(0, int(res["max_steps"] * 1.18))
        ax.set_title(
            f"{title_label}\n"
            f"[Slope = 1/ln({d}) = {1.0/math.log(d):.3f} per ln(N),  "
            f"Jump layer spacing ΔC = 1 + log_{d}({p}) = {delta_c:.3f}]",
            fontsize=12.5,
            fontweight="bold",
        )
        ax.set_xlabel("N  (Log10 scale: straight lines = geometric progressions a · d^k)", fontsize=11.5)
        ax.set_ylabel("Height h(n) (iterN)", fontsize=11.5)
        ax.grid(True, which="both", linestyle=":", linewidth=0.6, color="#64748b", alpha=0.45)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles[:6], labels[:6], loc="upper left", fontsize=8.2, framealpha=0.9)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot Collatz (p, Q) height graphs with a logarithmic X-axis to emphasize straight-line node alignment."
    )
    parser.add_argument("-p", type=int, default=5, help="Multiplier p (default: 5).")
    parser.add_argument(
        "-q",
        type=int,
        nargs="+",
        default=[3, 2, 1],
        help="Q values q_1 .. q_{p-2} (default: 3 2 1).",
    )
    parser.add_argument(
        "-n",
        "--max-n",
        type=int,
        default=100000,
        help="Maximum N to plot (default: 100000).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/p5/log_linear_comparison_p5_3_2_1.png"),
        help="Output PNG path for the Linear-X vs Log-X comparison plot.",
    )
    parser.add_argument(
        "--showcase-out",
        type=Path,
        default=Path("data/p5/log_linear_showcase_p3_p4_p5.png"),
        help="Output PNG path for the 4-panel p=3,4,5 Log-X showcase.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    q_norm: List[Optional[int]] = [None] + [int(x) for x in args.q]
    p1 = plot_linear_vs_log_comparison(
        p=args.p,
        q_norm=q_norm,
        max_n=args.max_n,
        out_path=args.out,
    )
    print(f"Saved Linear-vs-Log comparison plot to: {p1}")
    p2 = plot_multi_system_log_showcase(
        out_path=args.showcase_out,
        max_n=args.max_n,
    )
    print(f"Saved 4-panel Log-X showcase plot to  : {p2}")


if __name__ == "__main__":
    main()

