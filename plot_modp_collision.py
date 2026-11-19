"""
Phase 4: Generate comparison figure for q_r mod p collision & burst modes
from outputs/modp_collision/ CSVs.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    out_img = Path("docs/2026_1116/modp_collision_comparison.png")
    out_img.parent.mkdir(parents=True, exist_ok=True)

    # Load Phase 2 p=6 width profiles
    p6_profiles = []
    with open("outputs/modp_collision/p6_burst_modes_ctree.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p6_profiles.append(row)

    # Load Phase 3 p=8, 10 data
    p3_rows = defaultdict(list)
    with open("outputs/modp_collision/phase3_amplification.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p3_rows[(int(row["p"]), row["group"])].append(row)

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.8), dpi=150)

    # Panel A: p=6 CTree width W(h) on log scale
    ax = axes[0]
    hs = list(range(13))
    style_map = {
        "c=0 (every-step, gcd=6)": ("#D55E00", "-", "o", "c=0 (every-step, gcd=6)"),
        "c=3 (every-step, gcd=3)": ("#E69F00", "-", "s", "c=3 (every-step, gcd=3)"),
        "c=1,5 (alternating, gcd=1)": ("#0072B2", "--", "^", "c=1,5 (alternating, gcd=1)"),
        "c=2,4 (alternating, gcd=2)": ("#56B4E9", ":", "v", "c=2,4 (alternating, gcd=2)"),
        "all_distinct (binary, gcd=1)": ("#333333", "-.", "x", "all_distinct (binary, gcd=1)"),
    }
    for row in p6_profiles:
        lbl = row["label"]
        color, ls, marker, short = style_map.get(lbl, ("gray", "-", ".", lbl))
        ws = [float(row[f"w_h{h}"]) for h in hs]
        ax.plot(hs, ws, color=color, linestyle=ls, marker=marker, markersize=4.5, linewidth=1.8, label=short)
    ax.set_yscale("log")
    ax.set_title("p=6 CTree Width W(h) by Burst Mode (log)", fontsize=11, fontweight="bold")
    ax.set_xlabel("Height h")
    ax.set_ylabel("Mean Width W(h)")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=7.5, loc="upper left")

    # Panel B: Phase 3 p=8, 10 CTree total nodes @ H=10
    ax = axes[1]
    groups = ["binary_distinct", "alternating_c1", "every_step_c_half", "every_step_c0"]
    g_labels = ["Binary\n(distinct)", "Alternating\n(c=1)", "Every-step\n(c=p/2)", "Every-step\n(c=0)"]
    x = list(range(len(groups)))
    w = 0.35
    vals_p8 = [statistics.mean(float(r["ctree_nodes_h10"]) for r in p3_rows[(8, g)]) for g in groups]
    vals_p10 = [statistics.mean(float(r["ctree_nodes_h10"]) for r in p3_rows[(10, g)]) for g in groups]
    ax.bar([i - w / 2 for i in x], vals_p8, width=w, color="#0072B2", label="p=8 (7-way)")
    ax.bar([i + w / 2 for i in x], vals_p10, width=w, color="#D55E00", label="p=10 (9-way)")
    ax.set_xticks(x)
    ax.set_xticklabels(g_labels, fontsize=8.5)
    ax.set_title("CTree Total Nodes up to H=10", fontsize=11, fontweight="bold")
    ax.set_ylabel("Mean Nodes (H <= 10)")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8.5)

    # Panel C: Phase 3 p=8, 10 Mean avg_steps
    ax = axes[2]
    stp_p8 = [statistics.mean(float(r["avg_steps"]) for r in p3_rows[(8, g)]) for g in groups]
    stp_p10 = [statistics.mean(float(r["avg_steps"]) for r in p3_rows[(10, g)]) for g in groups]
    ax.bar([i - w / 2 for i in x], stp_p8, width=w, color="#0072B2", label="p=8 (n<=50k)")
    ax.bar([i + w / 2 for i in x], stp_p10, width=w, color="#D55E00", label="p=10 (n<=50k)")
    ax.set_xticks(x)
    ax.set_xticklabels(g_labels, fontsize=8.5)
    ax.set_title("Mean Convergence Steps (avg_steps)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Mean Steps")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8.5)

    plt.tight_layout()
    plt.savefig(out_img, dpi=150)
    plt.close(fig)
    print(f"Saved figure to {out_img}")


if __name__ == "__main__":
    main()

