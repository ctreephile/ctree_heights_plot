"""
Generate a 30x30 heatmap of the sum of CTree node counts up to height H=10
across all loops for each (q1, q2) in p=4 (q1 in [2, 5, ..., 89], q2 in [1, 4, ..., 88]).

Uses loop seeds (min_value) from outputs/p4_all_loops_catalog.csv (900 systems, n <= 100,000).
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np


def reconstruct_loop_members(p: int, q1: int, q2: int, min_val: int) -> List[int]:
    """Reconstruct all members of a cycle starting from its min_value."""
    d = p - 1
    members = [min_val]
    curr = min_val
    for _ in range(100000):
        r = curr % d
        if r == 0:
            curr //= d
        elif r == 1:
            curr = p * curr + q1
        else:
            curr = p * curr + q2
        if curr == min_val:
            return members
        members.append(curr)
    raise RuntimeError(f"Failed to close loop from min_val={min_val} for Q=({q1}, {q2})")


def count_ctree_nodes(p: int, q1: int, q2: int, loop_members: List[int], max_height: int) -> int:
    """Count total CTree nodes up to `max_height` (including h=0 loop members) via exact BFS."""
    d = p - 1
    q_list = [(1, q1), (2, q2)]
    q_by_mod: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for r_idx, q_val in q_list:
        q_by_mod[q_val % p].append((r_idx, q_val))

    visited = set(loop_members)
    frontier = list(loop_members)

    for _ in range(1, max_height + 1):
        next_frontier: List[int] = []
        for y in frontier:
            # *d preimage
            c_div = d * y
            if c_div not in visited:
                visited.add(c_div)
                next_frontier.append(c_div)
            # (y - q_r) / p preimages
            for r_idx, q_val in q_by_mod.get(y % p, ()):
                if y > q_val:
                    cand = (y - q_val) // p
                    if cand % d == r_idx and cand not in visited:
                        visited.add(cand)
                        next_frontier.append(cand)
        frontier = next_frontier
        if not frontier:
            break

    return len(visited)


def main() -> None:
    parser = argparse.ArgumentParser(description="Heatmap of total CTree nodes (up to H=10) over p=4 30x30 Q-grid.")
    parser.add_argument("--catalog", type=Path, default=Path("outputs/p4_all_loops_catalog.csv"))
    parser.add_argument("--max-height", type=int, default=10)
    parser.add_argument("--out-png", type=Path, default=None)
    parser.add_argument("--out-csv", type=Path, default=None)
    args = parser.parse_args()

    if args.out_png is None:
        args.out_png = Path(f"outputs/p4_ctree_nodes_h{args.max_height}_heatmap.png")
    if args.out_csv is None:
        args.out_csv = Path(f"outputs/p4_ctree_nodes_h{args.max_height}_30x30.csv")

    p = 4
    q1_vals = [2 + 3 * i for i in range(30)]  # 2, 5, ..., 89
    q2_vals = [1 + 3 * j for j in range(30)]  # 1, 4, ..., 88
    q1_idx = {v: i for i, v in enumerate(q1_vals)}
    q2_idx = {v: j for j, v in enumerate(q2_vals)}

    loops_by_cell: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    with args.catalog.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            q1 = int(row["q1"])
            q2 = int(row["q2"])
            min_v = int(row["min_value"])
            if q1 in q1_idx and q2 in q2_idx:
                loops_by_cell[(q1, q2)].append(min_v)

    grid = np.zeros((len(q2_vals), len(q1_vals)), dtype=np.int64)
    flat_records: List[Tuple[int, int, int, int]] = []

    for j, q2 in enumerate(q2_vals):
        for i, q1 in enumerate(q1_vals):
            total_nodes = 0
            loop_mins = loops_by_cell.get((q1, q2), [])
            for min_v in loop_mins:
                members = reconstruct_loop_members(p, q1, q2, min_v)
                total_nodes += count_ctree_nodes(p, q1, q2, members, args.max_height)
            grid[j, i] = total_nodes
            flat_records.append((total_nodes, q1, q2, len(loop_mins)))

    # Save 30x30 CSV (rows = q2, cols = q1)
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["q2 \\ q1"] + q1_vals)
        for j, q2 in enumerate(q2_vals):
            writer.writerow([q2] + grid[j, :].tolist())

    # Print top 10 & summary stats
    flat_records.sort(reverse=True)
    print(f"Computed 30x30 grid for p=4, H={args.max_height} (900 cells):")
    print(f"  Min={grid.min()}, Median={int(np.median(grid))}, Mean={grid.mean():.1f}, Max={grid.max()}")
    print("  Top 10 cells (total_nodes, q1, q2, num_loops):")
    for tot, q1, q2, nl in flat_records[:10]:
        print(f"    Q=({q1:>2}, {q2:>2}) [mod4=({q1%4},{q2%4}), gcd={math.gcd(q1,q2)}]: nodes={tot:>6}, loops={nl}")

    # Plot Heatmap (LogNorm so both normal and giant-loop cells are clearly distinguishable)
    fig, ax = plt.subplots(figsize=(11.5, 9.5), dpi=160)
    vmin = max(1, int(grid[grid > 0].min()))
    vmax = int(grid.max())
    im = ax.imshow(
        grid,
        origin="lower",
        aspect="equal",
        cmap="viridis",
        norm=LogNorm(vmin=vmin, vmax=vmax),
        interpolation="nearest",
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(f"Sum of CTree Nodes up to H={args.max_height} (log scale)", fontsize=11)

    # Tick labels every 2 cells (or all 30 with small font)
    ax.set_xticks(range(len(q1_vals)))
    ax.set_xticklabels([str(v) for v in q1_vals], fontsize=7.5, rotation=45)
    ax.set_yticks(range(len(q2_vals)))
    ax.set_yticklabels([str(v) for v in q2_vals], fontsize=7.5)

    ax.set_xlabel("q1  (2, 5, 8, ..., 89)", fontsize=12, fontweight="bold")
    ax.set_ylabel("q2  (1, 4, 7, ..., 88)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"p=4: Total CTree Nodes up to Height H={args.max_height} (Sum over All Loops)",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )

    # Subtle grid lines between cells
    ax.set_xticks(np.arange(-0.5, len(q1_vals), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(q2_vals), 1), minor=True)
    ax.grid(which="minor", color="#ffffff", linestyle="-", linewidth=0.35, alpha=0.35)
    ax.tick_params(which="minor", bottom=False, left=False)

    plt.tight_layout()
    args.out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.out_png, dpi=160)
    plt.close(fig)
    print(f"Saved heatmap to {args.out_png}")
    print(f"Saved 30x30 CSV to {args.out_csv}")


if __name__ == "__main__":
    main()
