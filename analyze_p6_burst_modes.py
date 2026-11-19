"""
Phase 2: Deep-dive comparison of every-step burst (-c == c mod p) vs alternating burst
(-c != c mod p) in p=6 (data/p6/summary_p6.db), controlling for gcd(Q).
"""

from __future__ import annotations

import csv
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from analyze_modp_collision import load_system_records, mann_whitney_u_pvalue, measure_ctree_bfs, write_csv


def main() -> None:
    p = 6
    db_path = Path("data/p6/summary_p6.db")
    records = load_system_records(p, db_path)

    # 1. Breakdown of dist==1 by residue c mod 6 and gcd(Q)
    print("=== 1. p=6 All-Collide (dist==1, N=228) by residue c mod 6 ===")
    by_c: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        if r["distinct_mod_p"] == 1:
            by_c[r["mods"][0]].append(r)

    summary_rows: List[Dict[str, Any]] = []
    print(f"{'c':>2} {'mode':<12} {'N':>4} {'gcds':<14} | {'loops':>5} {'maxLen':>6} {'avgStp':>6} {'maxStp':>6} | {'giniN':>5} {'maxShr':>6}")
    print("-" * 86)
    for c in sorted(by_c.keys()):
        recs = by_c[c]
        n = len(recs)
        mode = "every-step" if (-c) % p == c else "alternating"
        gcds = dict(sorted(Counter(r["gcd_q"] for r in recs).items()))
        avg = lambda k: sum(r[k] for r in recs) / n
        row = {
            "group": f"dist1_c={c}",
            "mode": mode,
            "n": n,
            "gcds": str(gcds),
            "avg_loops": avg("num_loops"),
            "avg_max_len": avg("max_len"),
            "avg_avg_steps": avg("avg_steps"),
            "avg_max_steps": avg("max_steps"),
            "avg_gini_norm": avg("gini_norm"),
            "avg_max_share": avg("max_share"),
        }
        summary_rows.append(row)
        print(
            f"{c:>2} {mode:<12} {n:>4} {str(gcds):<14} | "
            f"{row['avg_loops']:>5.2f} {row['avg_max_len']:>6.2f} "
            f"{row['avg_avg_steps']:>6.2f} {row['avg_max_steps']:>6.1f} | "
            f"{row['avg_gini_norm']:>5.3f} {row['avg_max_share']:>6.3f}"
        )

    # 2. Isolate gcd(Q) == 3: c=3 all-collide vs non-collide (max_mult==1 or dist>=3)
    print("\n=== 2. Controlling for gcd(Q) == 3 (isolating every-step burst vs clone-prime 3) ===")
    gcd3_c3 = [r for r in records if r["gcd_q"] == 3 and r["distinct_mod_p"] == 1]
    gcd3_other = [r for r in records if r["gcd_q"] == 3 and r["distinct_mod_p"] >= 3]
    gcd3_bin = [r for r in records if r["gcd_q"] == 3 and r["max_mult"] == 1]
    print(f"Counts with gcd(Q)==3: dist=1 (c=3) N={len(gcd3_c3)}, dist>=3 N={len(gcd3_other)}, max_mult=1 N={len(gcd3_bin)}")

    for label, grp in [
        ("gcd=3 & c=3 (every-step burst)", gcd3_c3),
        ("gcd=3 & dist>=3 (mixed)", gcd3_other),
    ]:
        n = len(grp)
        if n == 0:
            continue
        avg = lambda k: sum(r[k] for r in grp) / n
        print(
            f"  {label:<32} (N={n:>4}): loops={avg('num_loops'):.2f}, maxLen={avg('max_len'):.2f}, "
            f"avgStp={avg('avg_steps'):.2f}, maxStp={avg('max_steps'):.1f}, giniN={avg('gini_norm'):.3f}, maxShr={avg('max_share'):.3f}"
        )
    if gcd3_c3 and gcd3_other:
        for k in ["num_loops", "max_len", "avg_steps", "max_steps", "gini_norm"]:
            pv = mann_whitney_u_pvalue([r[k] for r in gcd3_c3], [r[k] for r in gcd3_other])
            print(f"    p-value ({k}): {pv:.2e}")

    # 3. Isolate gcd(Q) == 2: c=2,4 all-collide (alternating) vs gcd=2 & dist>=3
    print("\n=== 3. Controlling for gcd(Q) == 2 (c=2,4 alternating burst vs mixed) ===")
    gcd2_col = [r for r in records if r["gcd_q"] == 2 and r["distinct_mod_p"] == 1]
    gcd2_other = [r for r in records if r["gcd_q"] == 2 and r["distinct_mod_p"] >= 3]
    for label, grp in [
        ("gcd=2 & c=2,4 (alternating burst)", gcd2_col),
        ("gcd=2 & dist>=3 (mixed)", gcd2_other),
    ]:
        n = len(grp)
        if n == 0:
            continue
        avg = lambda k: sum(r[k] for r in grp) / n
        print(
            f"  {label:<36} (N={n:>4}): loops={avg('num_loops'):.2f}, maxLen={avg('max_len'):.2f}, "
            f"avgStp={avg('avg_steps'):.2f}, maxStp={avg('max_steps'):.1f}, giniN={avg('gini_norm'):.3f}, maxShr={avg('max_share'):.3f}"
        )

    # 4. CTree BFS height-by-height profile for c=0, c=3, c=1/5, and all-distinct (gcd=1)
    print("\n=== 4. CTree BFS Profile (H=12) by Burst Mode ===")
    groups_bfs = [
        ("c=0 (every-step, gcd=6)", [r for r in records if r["distinct_mod_p"] == 1 and r["mods"][0] == 0]),
        ("c=3 (every-step, gcd=3)", [r for r in records if r["distinct_mod_p"] == 1 and r["mods"][0] == 3]),
        ("c=2,4 (alternating, gcd=2)", [r for r in records if r["distinct_mod_p"] == 1 and r["mods"][0] in (2, 4)]),
        ("c=1,5 (alternating, gcd=1)", [r for r in records if r["distinct_mod_p"] == 1 and r["mods"][0] in (1, 5)]),
        ("all_distinct (binary, gcd=1)", [r for r in records if r["gcd_q"] == 1 and r["max_mult"] == 1][:78]),
    ]
    bfs_rows: List[Dict[str, Any]] = []
    for label, grp in groups_bfs:
        res = [measure_ctree_bfs(p, r["q_list"], r["top_loop_min_val"], max_h=12) for r in grp if r["top_loop_min_val"] > 0]
        n = len(res)
        avg_w = [sum(m["widths"][h] for m in res) / n for h in range(13)]
        avg_tot = sum(m["total_nodes"] for m in res) / n
        avg_br = sum(m["branch_nodes"] for m in res) / n
        avg_bu = sum(m["burst_nodes"] for m in res) / n
        print(f"  {label:<30} (N={n:>2}): total={avg_tot:7.1f}, branch={avg_br:5.1f}, burst={avg_bu:5.1f}")
        print(f"    widths h=0..12: {[round(w, 1) for w in avg_w]}")
        bfs_rows.append(
            {
                "label": label,
                "n": n,
                "avg_total_nodes": avg_tot,
                "avg_branch_nodes": avg_br,
                "avg_burst_nodes": avg_bu,
                **{f"w_h{h}": avg_w[h] for h in range(13)},
            }
        )

    out_dir = Path("outputs/modp_collision")
    write_csv(out_dir / "p6_burst_modes_summary.csv", summary_rows)
    write_csv(out_dir / "p6_burst_modes_ctree.csv", bfs_rows)
    print(f"\nSaved Phase 2 CSVs to {out_dir}/")


if __name__ == "__main__":
    main()

