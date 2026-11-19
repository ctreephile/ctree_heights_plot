#!/usr/bin/env python3
"""
Visualize p=4 Q-family orbits (mirror-symmetric ray pairs in the (q1, q2) plane)
color-coded by primitive base Q_base = (a, b).

Generates outputs/p4_family_orbits_80x80.png.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def canonical_base(q1: int, q2: int) -> Tuple[int, Tuple[int, int]]:
    g = math.gcd(q1, q2)
    a, b = q1 // g, q2 // g
    return (g, (b, a)) if (g % 3 == 2) else (g, (a, b))


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot color-coded Q-family orbit rays in p=4 NxN grid.")
    parser.add_argument("--grid-size", type=int, default=80)
    parser.add_argument("--top-k", type=int, default=16, help="Number of largest families to highlight with rays & labels.")
    parser.add_argument("--out-png", type=Path, default=Path("outputs/p4_family_orbits_80x80.png"))
    args = parser.parse_args()

    n_grid = args.grid_size
    q1_vals = [2 + 3 * i for i in range(n_grid)]
    q2_vals = [1 + 3 * j for j in range(n_grid)]
    max_q1 = q1_vals[-1]
    max_q2 = q2_vals[-1]

    families: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = defaultdict(list)
    for q1 in q1_vals:
        for q2 in q2_vals:
            g, base = canonical_base(q1, q2)
            families[base].append((g, q1, q2))

    # Sort families by number of members in grid (desc), then base
    sorted_fams = sorted(families.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    top_fams = sorted_fams[: args.top_k]

    # Distinct high-contrast palette on dark background
    cmap = plt.get_cmap("tab20")
    colors = [cmap(i % 20) for i in range(len(top_fams))]

    fig, axes = plt.subplots(1, 2, figsize=(16.5, 8.0), dpi=160, facecolor="#0f172a")

    # ---- Panel 1: Top-K Family Orbit Rays (2 mirror-symmetric lines per family) ----
    ax = axes[0]
    ax.set_facecolor("#0b1120")

    # Mirror symmetry diagonal q2 = q1
    lim_max = max(max_q1, max_q2) + 8
    ax.plot([0, lim_max], [0, lim_max], color="#475569", linestyle="--", linewidth=1.2, label="q2 = q1 (Mirror Axis)", zorder=1)

    for idx, (base, members) in enumerate(top_fams):
        col = colors[idx]
        a, b = base
        # Ray 1: g % 3 == 1 -> q2 = (b/a) * q1
        x1_end = min(lim_max, lim_max * a / b) if b > 0 else lim_max
        y1_end = (b / a) * x1_end
        ax.plot([0, x1_end], [0, y1_end], color=col, linewidth=1.1, alpha=0.55, zorder=2)

        # Ray 2: g % 3 == 2 -> q2 = (a/b) * q1
        x2_end = min(lim_max, lim_max * b / a) if a > 0 else lim_max
        y2_end = (a / b) * x2_end
        ax.plot([0, x2_end], [0, y2_end], color=col, linewidth=1.1, linestyle=":", alpha=0.55, zorder=2)

        pts_g1 = [(q1, q2) for g, q1, q2 in members if g % 3 == 1]
        pts_g2 = [(q1, q2) for g, q1, q2 in members if g % 3 == 2]

        if pts_g1:
            ax.scatter(
                [p[0] for p in pts_g1],
                [p[1] for p in pts_g1],
                color=col,
                marker="o",
                s=26,
                edgecolors="#ffffff",
                linewidths=0.4,
                label=f"{base} (n={len(members)})",
                zorder=4,
            )
        if pts_g2:
            ax.scatter(
                [p[0] for p in pts_g2],
                [p[1] for p in pts_g2],
                color=col,
                marker="D",
                s=22,
                edgecolors="#0f172a",
                linewidths=0.5,
                zorder=4,
            )

    ax.set_xlim(0, max_q1 + 6)
    ax.set_ylim(0, max_q2 + 6)
    ax.set_xlabel("q1 (2, 5, 8, ...)", color="#e2e8f0", fontsize=11, fontweight="bold")
    ax.set_ylabel("q2 (1, 4, 7, ...)", color="#e2e8f0", fontsize=11, fontweight="bold")
    ax.set_title(
        f"Top {args.top_k} Family Orbits (o: g=1 mod 3 [slope b/a] / diamond: g=2 mod 3 [slope a/b])",
        color="#f8fafc",
        fontsize=11.0,
        fontweight="bold",
        pad=10,
    )
    ax.tick_params(colors="#cbd5e1")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.grid(True, color="#1e293b", linewidth=0.6)
    ax.legend(
        loc="upper right",
        fontsize=7.8,
        facecolor="#0f172a",
        edgecolor="#334155",
        labelcolor="#f8fafc",
        ncol=2,
    )

    # ---- Panel 2: Full Grid Colored by Family Size / Top Families ----
    ax2 = axes[1]
    ax2.set_facecolor("#0b1120")

    # Background: singletons (size=1) in dark slate, multi-member (size>=2) by hue
    fam_color_map: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
    for idx, (base, _) in enumerate(top_fams):
        fam_color_map[base] = colors[idx]

    other_cmap = plt.get_cmap("turbo")
    other_multi = [b for b, mem in sorted_fams[args.top_k :] if len(mem) >= 2]
    for j, base in enumerate(other_multi):
        r, g_c, b_c, _ = other_cmap((j * 0.61803398875) % 1.0)
        fam_color_map[base] = (r * 0.65, g_c * 0.65, b_c * 0.65, 0.85)

    img_rgba = np.zeros((n_grid, n_grid, 4), dtype=float)
    for j, q2 in enumerate(q2_vals):
        for i, q1 in enumerate(q1_vals):
            _, base = canonical_base(q1, q2)
            if base in fam_color_map:
                img_rgba[j, i] = fam_color_map[base]
            else:
                img_rgba[j, i] = (0.11, 0.16, 0.25, 1.0)  # singleton

    ax2.imshow(
        img_rgba,
        origin="lower",
        extent=[q1_vals[0] - 1.5, q1_vals[-1] + 1.5, q2_vals[0] - 1.5, q2_vals[-1] + 1.5],
        aspect="equal",
        interpolation="nearest",
    )
    ax2.plot([0, lim_max], [0, lim_max], color="#94a3b8", linestyle="--", linewidth=1.0, alpha=0.7)
    ax2.set_xlim(0, max_q1 + 6)
    ax2.set_ylim(0, max_q2 + 6)
    ax2.set_xlabel("q1 (2, 5, 8, ...)", color="#e2e8f0", fontsize=11, fontweight="bold")
    ax2.set_ylabel("q2 (1, 4, 7, ...)", color="#e2e8f0", fontsize=11, fontweight="bold")
    ax2.set_title(
        f"p=4 ({n_grid}x{n_grid}) Full Grid by Family (Multi-member: {sum(1 for _, m in sorted_fams if len(m)>=2)} / Singletons: dark)",
        color="#f8fafc",
        fontsize=11.0,
        fontweight="bold",
        pad=10,
    )
    ax2.tick_params(colors="#cbd5e1")
    for spine in ax2.spines.values():
        spine.set_color("#334155")

    fig.suptitle(
        "p=4 Q-Family Orbits: Mirror-Symmetric Rays Under M_g Action",
        color="#f8fafc",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    args.out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.out_png, dpi=160, facecolor="#0f172a")
    plt.close(fig)
    print(f"Saved {args.out_png}")


if __name__ == "__main__":
    main()
