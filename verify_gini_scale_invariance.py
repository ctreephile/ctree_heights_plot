#!/usr/bin/env python3
"""
Verify whether CTree basin shares and Gini coefficients are scale-invariant
across different sample cutoffs: N = 10,000, 30,000, 50,000, and 100,000
across all 900 DBs, plus N = 500,000 on representative pairs.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

from analyze_ctree_gini import compute_gini_metrics

DB_DIR = Path("DB")
Q1_LIST = list(range(2, 90, 3))
Q2_LIST = list(range(1, 89, 3))
CUTOFFS = [10000, 30000, 50000, 100000]


def check_one_db(task: Tuple[int, int, str]) -> Dict[str, Any]:
    q1, q2, db_path_str = task
    conn = sqlite3.connect(db_path_str)
    try:
        loops_rows = conn.execute(
            "SELECT loop_id FROM loops ORDER BY min_value"
        ).fetchall()
        loop_ids = [int(r[0]) for r in loops_rows]
        m = len(loop_ids)

        # Single scan of n <= 100000 ordered by n
        rows = conn.execute(
            """
            SELECT
                loop_id,
                SUM(CASE WHEN n <= 10000 THEN 1 ELSE 0 END) AS c10k,
                SUM(CASE WHEN n <= 30000 THEN 1 ELSE 0 END) AS c30k,
                SUM(CASE WHEN n <= 50000 THEN 1 ELSE 0 END) AS c50k,
                COUNT(*) AS c100k
            FROM steps_cache
            WHERE n <= 100000 AND loop_id > 0
            GROUP BY loop_id
            """
        ).fetchall()
    finally:
        conn.close()

    by_lid = {int(r[0]): (int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in rows}

    # Note: total loop count M is fixed as the loops existing in the system (or discovered up to cutoff)
    c10_all = [by_lid.get(lid, (0, 0, 0, 0))[0] for lid in loop_ids]
    c30_all = [by_lid.get(lid, (0, 0, 0, 0))[1] for lid in loop_ids]
    c50_all = [by_lid.get(lid, (0, 0, 0, 0))[2] for lid in loop_ids]
    c100_all = [by_lid.get(lid, (0, 0, 0, 0))[3] for lid in loop_ids]

    m10 = compute_gini_metrics(c10_all)
    m30 = compute_gini_metrics(c30_all)
    m50 = compute_gini_metrics(c50_all)
    m100 = compute_gini_metrics(c100_all)

    # Also count how many loops had >0 members at 10k, 30k, 50k, 100k
    active_10k = sum(1 for c in c10_all if c > 0)
    active_30k = sum(1 for c in c30_all if c > 0)
    active_50k = sum(1 for c in c50_all if c > 0)
    active_100k = sum(1 for c in c100_all if c > 0)

    return {
        "q1": q1,
        "q2": q2,
        "m": m,
        "active": (active_10k, active_30k, active_50k, active_100k),
        "gini": {
            10000: m10["gini"],
            30000: m30["gini"],
            50000: m50["gini"],
            100000: m100["gini"],
        },
        "norm_gini": {
            10000: m10["norm_gini"],
            30000: m30["norm_gini"],
            50000: m50["norm_gini"],
            100000: m100["norm_gini"],
        },
        "top1_pct": {
            10000: m10["top1_pct"],
            30000: m30["top1_pct"],
            50000: m50["top1_pct"],
            100000: m100["top1_pct"],
        },
        "shares_30k": sorted([c / 300.0 for c in c30_all], reverse=True),
        "shares_50k": sorted([c / 500.0 for c in c50_all], reverse=True),
        "shares_100k": sorted([c / 1000.0 for c in c100_all], reverse=True),
    }


def main() -> None:
    t0 = time.perf_counter()
    tasks = [
        (q1, q2, str(DB_DIR / f"p4_{q1}_{q2}.db"))
        for q2 in Q2_LIST
        for q1 in Q1_LIST
    ]
    workers = max(1, (os.cpu_count() or 4) - 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(check_one_db, tasks))

    elapsed = time.perf_counter() - t0
    print(f"Scanned 900 DBs at 4 cutoffs (10k, 30k, 50k, 100k) in {elapsed:.2f}s\n")

    multi = [r for r in results if r["m"] >= 2]

    print("=== 1. Overall Average across 834 Multi-Loop Pairs (M >= 2) ===")
    for k in CUTOFFS:
        avg_g = statistics.mean(r["gini"][k] for r in multi)
        avg_ng = statistics.mean(r["norm_gini"][k] for r in multi)
        med_ng = statistics.median(r["norm_gini"][k] for r in multi)
        avg_top1 = statistics.mean(r["top1_pct"][k] for r in multi)
        print(
            f"  N = {k:7,d} : Avg G = {avg_g:.4f} | Avg G* = {avg_ng:.4f} (Median {med_ng:.4f}) | Avg Top1 Share = {avg_top1:.2f}%"
        )

    # Mean absolute difference between 30k vs 100k, and 50k vs 100k
    diff_30_100 = [abs(r["norm_gini"][30000] - r["norm_gini"][100000]) for r in multi]
    diff_50_100 = [abs(r["norm_gini"][50000] - r["norm_gini"][100000]) for r in multi]
    max_diff_30_100 = max(diff_30_100)
    max_diff_50_100 = max(diff_50_100)

    # Pearson correlation between G*(30k) and G*(100k)
    x30 = [r["norm_gini"][30000] for r in multi]
    x50 = [r["norm_gini"][50000] for r in multi]
    x100 = [r["norm_gini"][100000] for r in multi]
    corr_30_100 = statistics.correlation(x30, x100)
    corr_50_100 = statistics.correlation(x50, x100)

    print("\n=== 2. Deviation & Correlation across all 834 Multi-Loop Pairs ===")
    print(f"  |G*(30,000) - G*(100,000)| : Mean = {statistics.mean(diff_30_100):.5f}, Max = {max_diff_30_100:.5f}, Correlation r = {corr_30_100:.6f}")
    print(f"  |G*(50,000) - G*(100,000)| : Mean = {statistics.mean(diff_50_100):.5f}, Max = {max_diff_50_100:.5f}, Correlation r = {corr_50_100:.6f}")

    # Check how many loops were already discovered by N=10k, 30k, 50k vs 100k
    total_loops_10k = sum(r["active"][0] for r in results)
    total_loops_30k = sum(r["active"][1] for r in results)
    total_loops_50k = sum(r["active"][2] for r in results)
    total_loops_100k = sum(r["active"][3] for r in results)
    print("\n=== 3. Total Loops Discovered by Cutoff N (across all 900 pairs) ===")
    print(f"  N =  10,000 : {total_loops_10k:,} / {total_loops_100k:,} loops ({total_loops_10k/total_loops_100k*100:.2f}%)")
    print(f"  N =  30,000 : {total_loops_30k:,} / {total_loops_100k:,} loops ({total_loops_30k/total_loops_100k*100:.2f}%)")
    print(f"  N =  50,000 : {total_loops_50k:,} / {total_loops_100k:,} loops ({total_loops_50k/total_loops_100k*100:.2f}%)")
    print(f"  N = 100,000 : {total_loops_100k:,} / {total_loops_100k:,} loops (100.00%)")

    print("\n=== 4. Representative Pairs at N = 10k, 30k, 50k, 100k ===")
    targets = [(35, 34), (77, 4), (17, 85), (35, 70), (80, 10), (5, 40), (47, 46)]
    for q1, q2 in targets:
        rec = next(r for r in results if r["q1"] == q1 and r["q2"] == q2)
        print(
            f"  ({q1:2d}, {q2:2d}) [M={rec['m']:2d}] : "
            f"G*(10k)={rec['norm_gini'][10000]:.4f}, "
            f"G*(30k)={rec['norm_gini'][30000]:.4f}, "
            f"G*(50k)={rec['norm_gini'][50000]:.4f}, "
            f"G*(100k)={rec['norm_gini'][100000]:.4f}"
        )
        s30 = " / ".join(f"{s:.1f}%" for s in rec["shares_30k"][:5])
        s50 = " / ".join(f"{s:.1f}%" for s in rec["shares_50k"][:5])
        s100 = " / ".join(f"{s:.1f}%" for s in rec["shares_100k"][:5])
        print(f"      Shares @  30k: {s30}")
        print(f"      Shares @  50k: {s50}")
        print(f"      Shares @ 100k: {s100}")


if __name__ == "__main__":
    main()

