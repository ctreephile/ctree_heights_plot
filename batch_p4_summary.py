#!/usr/bin/env python3
"""
Parallel summary generator for p=4 (q1, q2) NxN grid (default: 80x80 = 6,400 cells).

Outputs compact summary CSVs into outputs/p4_grid_{N}x{N}/:
  - summary.csv
  - loops_catalog.csv
  - ctree_nodes_h10.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.p4_heatmap import count_ctree_nodes_p4


def evaluate_p4_grid_cell(args: Tuple[int, int, int, int]) -> Dict[str, Any]:
    """Evaluate one (q1, q2) cell for n=1..n_max and compute H=max_height CTree nodes."""
    q1, q2, n_max, max_height = args
    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops: Dict[int, Dict[str, Any]] = {}
    next_lid = 1
    max_steps_limit = 10000

    for start_n in range(1, n_max + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_idx: Dict[int, int] = {}
        curr = start_n

        while curr not in steps_cache and curr not in path_idx and len(path) <= max_steps_limit:
            path_idx[curr] = len(path)
            path.append(curr)
            r = curr % 3
            if r == 0:
                curr //= 3
            elif r == 1:
                curr = 4 * curr + q1
            else:
                curr = 4 * curr + q2

        if curr in steps_cache:
            ks, klid = steps_cache[curr]
            for i, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (ks + i, klid)
        elif curr in path_idx:
            c_start = path_idx[curr]
            cycle = path[c_start:]
            lid = next_lid
            next_lid += 1
            loops[lid] = {
                "min_value": min(cycle),
                "members": cycle,
                "length": len(cycle),
                "basin_count": 0,
            }
            for val in cycle:
                steps_cache[val] = (0, lid)
            for i, val in enumerate(reversed(path[:c_start]), start=1):
                steps_cache[val] = (i, lid)
        else:
            for val in path:
                steps_cache[val] = (-1, -1)

    total_steps = 0
    max_obs_steps = 0
    resolved = 0
    for n in range(1, n_max + 1):
        s, lid = steps_cache[n]
        if lid > 0:
            resolved += 1
            total_steps += s
            if s > max_obs_steps:
                max_obs_steps = s
            loops[lid]["basin_count"] += 1

    loop_list = sorted(loops.values(), key=lambda x: x["min_value"])
    lens = [lp["length"] for lp in loop_list]
    max_basin = max((lp["basin_count"] for lp in loop_list), default=0)
    dom_share = round(100.0 * max_basin / resolved, 2) if resolved else 0.0
    avg_steps = round(total_steps / resolved, 2) if resolved else 0.0

    total_nodes = sum(
        count_ctree_nodes_p4(q1, q2, lp["members"], max_height) for lp in loop_list
    )

    loop_rows = [
        {
            "q1": q1,
            "q2": q2,
            "min_value": lp["min_value"],
            "length": lp["length"],
            "basin_share_pct": round(100.0 * lp["basin_count"] / resolved, 2) if resolved else 0.0,
        }
        for lp in loop_list
    ]

    return {
        "q1": q1,
        "q2": q2,
        "gcd": math.gcd(q1, q2),
        "num_loops": len(loop_list),
        "dom_share": dom_share,
        "max_steps": max_obs_steps,
        "avg_steps": avg_steps,
        "loop_lengths": ";".join(str(x) for x in lens),
        "nodes_h": total_nodes,
        "loop_rows": loop_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NxN p=4 summary CSVs in parallel.")
    parser.add_argument("--grid-size", type=int, default=80, help="Grid dimension N (default: 80 -> 80x80).")
    parser.add_argument("--n-max", type=int, default=100000, help="Max n per cell (default: 100000).")
    parser.add_argument("--max-height", type=int, default=10, help="CTree height for precomputed nodes (default: 10).")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    args = parser.parse_args()

    n_grid = args.grid_size
    q1_vals = [2 + 3 * i for i in range(n_grid)]
    q2_vals = [1 + 3 * j for j in range(n_grid)]
    out_dir = Path(f"outputs/p4_grid_{n_grid}x{n_grid}")
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(q1, q2, args.n_max, args.max_height) for q2 in q2_vals for q1 in q1_vals]
    total = len(tasks)
    print(f"Generating p=4 {n_grid}x{n_grid} ({total} cells), n<={args.n_max}, H={args.max_height}, workers={args.workers}...")

    t0 = time.time()
    results: Dict[Tuple[int, int], Dict[str, Any]] = {}
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(evaluate_p4_grid_cell, t) for t in tasks]
        for fut in as_completed(futures):
            res = fut.result()
            results[(res["q1"], res["q2"])] = res
            done += 1
            if done % 800 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0.0
                eta = (total - done) / rate if rate > 0 else 0.0
                print(f"  Progress: {done}/{total} ({100.0*done/total:.1f}%) | {elapsed:.1f}s elapsed, ETA {eta:.1f}s")

    # Write summary.csv
    summary_path = out_dir / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["q1", "q2", "gcd(q1,q2)", "num_loops", "dominant_loop_share_pct", "max_steps", "avg_steps", "loop_lengths"])
        for q2 in q2_vals:
            for q1 in q1_vals:
                r = results[(q1, q2)]
                w.writerow([r["q1"], r["q2"], r["gcd"], r["num_loops"], r["dom_share"], r["max_steps"], r["avg_steps"], r["loop_lengths"]])

    # Write loops_catalog.csv
    catalog_path = out_dir / "loops_catalog.csv"
    with catalog_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["q1", "q2", "min_value", "length", "basin_share_pct"])
        for q2 in q2_vals:
            for q1 in q1_vals:
                for lr in results[(q1, q2)]["loop_rows"]:
                    w.writerow([lr["q1"], lr["q2"], lr["min_value"], lr["length"], lr["basin_share_pct"]])

    # Write ctree_nodes_h{max_height}.csv
    nodes_path = out_dir / f"ctree_nodes_h{args.max_height}.csv"
    with nodes_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["q2 \\ q1"] + q1_vals)
        for q2 in q2_vals:
            w.writerow([q2] + [results[(q1, q2)]["nodes_h"] for q1 in q1_vals])

    print(f"Done in {time.time() - t0:.1f}s! Saved to {out_dir}/")


if __name__ == "__main__":
    main()

