"""
Statistical analysis of q_r mod p collision effects on (p, Q) Collatz systems and CTrees.

Compares systems where all q_r share the same residue mod p (extreme (p-1)-way burst
at matching nodes) against systems where all q_r mod p are distinct (<=2-way binary tree)
across existing SQLite databases (data/p5 .. data/p9).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple


def mann_whitney_u_pvalue(x: Sequence[float], y: Sequence[float]) -> float:
    """Two-sided Mann-Whitney U test p-value via normal approximation with tie correction."""
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 1.0
    combined = [(val, 0) for val in x] + [(val, 1) for val in y]
    combined.sort(key=lambda t: t[0])

    ranks_x = 0.0
    tie_correction = 0.0
    i = 0
    n = len(combined)
    while i < n:
        j = i
        while j < n and combined[j][0] == combined[i][0]:
            j += 1
        t = j - i
        if t > 1:
            tie_correction += t * (t * t - 1)
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            if combined[k][1] == 0:
                ranks_x += avg_rank
        i = j

    u1 = ranks_x - nx * (nx + 1) / 2.0
    mu = nx * ny / 2.0
    var = (nx * ny / 12.0) * ((n + 1) - tie_correction / (n * (n - 1))) if n > 1 else 0.0
    if var <= 0.0:
        return 1.0
    z = abs(u1 - mu) / math.sqrt(var)
    return math.erfc(z / math.sqrt(2.0))


def load_system_records(p: int, db_path: Path) -> List[Dict[str, Any]]:
    """Load system-level and aggregated loop-level records from summary_p{p}.db."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    sys_rows = cur.execute(
        """
        SELECT system_id, q_json, gcd_q, num_loops, max_steps, avg_steps,
               unresolved_count, gini, gini_norm, hhi, shannon_evenness
        FROM systems
        """
    ).fetchall()

    loop_rows = cur.execute(
        """
        SELECT system_id, min_value, length, basin_share
        FROM loops
        """
    ).fetchall()
    conn.close()

    loops_by_sys: Dict[int, List[Tuple[int, int, float]]] = defaultdict(list)
    for sid, min_v, length, b_share in loop_rows:
        loops_by_sys[sid].append((min_v, length, b_share))

    records: List[Dict[str, Any]] = []
    for r in sys_rows:
        sid, qj, gcd_q, num_loops, max_steps, avg_steps, unres, gini, gini_norm, hhi, shannon = r
        q_list = [int(x) for x in json.loads(qj) if x is not None]
        mods = [x % p for x in q_list]
        dist = len(set(mods))
        max_mult = max(Counter(mods).values())

        sys_loops = loops_by_sys[sid]
        lens = [l[1] for l in sys_loops]
        top_loop = max(sys_loops, key=lambda l: l[2]) if sys_loops else (0, 0, 0.0)

        records.append(
            {
                "p": p,
                "system_id": sid,
                "q_list": q_list,
                "mods": mods,
                "distinct_mod_p": dist,
                "max_mult": max_mult,
                "gcd_q": gcd_q,
                "mean_q": sum(q_list) / len(q_list),
                "num_loops": num_loops,
                "is_single_loop": 1 if num_loops == 1 else 0,
                "max_len": max(lens, default=0),
                "min_len": min(lens, default=0),
                "has_len50": 1 if max(lens, default=0) >= 50 else 0,
                "has_len100": 1 if max(lens, default=0) >= 100 else 0,
                "max_share": top_loop[2],
                "top_loop_min_val": top_loop[0],
                "max_steps": max_steps,
                "avg_steps": avg_steps,
                "unresolved_count": unres,
                "gini": gini,
                "gini_norm": gini_norm if gini_norm is not None else 0.0,
                "hhi": hhi,
                "shannon": shannon if shannon is not None else 0.0,
            }
        )
    return records


def measure_ctree_bfs(p: int, q_list: List[int], root: int, max_h: int = 12) -> Dict[str, Any]:
    """Expand the CTree rooted at `root` up to height `max_h` and measure width/branching stats."""
    d = p - 1
    q_by_mod: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for r_idx, q in enumerate(q_list, start=1):
        q_by_mod[q % p].append((r_idx, q))

    visited = {root}
    frontier = [root]
    widths = [1]
    branch_nodes = 0
    burst_nodes = 0

    for _ in range(1, max_h + 1):
        next_frontier: List[int] = []
        for y in frontier:
            candidates = [d * y]
            for r_idx, q in q_by_mod.get(y % p, ()):
                if y > q:
                    cand = (y - q) // p
                    if cand % d == r_idx:
                        candidates.append(cand)
            deg = 0
            for c in candidates:
                if c not in visited:
                    visited.add(c)
                    next_frontier.append(c)
                    deg += 1
            if deg >= 2:
                branch_nodes += 1
            if deg == p - 1:
                burst_nodes += 1
        frontier = next_frontier
        widths.append(len(frontier))
        if not frontier:
            break

    while len(widths) <= max_h:
        widths.append(0)

    return {
        "total_nodes": sum(widths),
        "max_width": max(widths),
        "width_at_h": widths[max_h],
        "branch_nodes": branch_nodes,
        "burst_nodes": burst_nodes,
        "widths": widths,
    }


def summarize_by_collision_group(
    records: List[Dict[str, Any]],
    p: int,
    filter_name: str,
    pred: Callable[[Dict[str, Any]], bool],
    csv_rows: List[Dict[str, Any]],
) -> None:
    """Print and collect group summary statistics by (distinct_mod_p, max_mult)."""
    groups: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        if pred(rec):
            groups[(rec["distinct_mod_p"], rec["max_mult"])].append(rec)

    print(f"\n--- p={p} [{filter_name}] ---")
    header = (
        f"{'dist':>4} {'mult':>4} {'N':>6} | {'loops':>6} {'maxLen':>6} "
        f"{'avgStp':>7} {'maxStp':>7} | {'gini':>6} {'giniN':>6} {'maxShr':>6} | {'meanQ':>6}"
    )
    print(header)
    print("-" * len(header))

    for (dist, mult), recs in sorted(groups.items()):
        n = len(recs)
        avg = lambda k: sum(x[k] for x in recs) / n
        row = {
            "p": p,
            "filter": filter_name,
            "distinct_mod_p": dist,
            "max_mult": mult,
            "count": n,
            "avg_num_loops": avg("num_loops"),
            "avg_max_len": avg("max_len"),
            "avg_avg_steps": avg("avg_steps"),
            "avg_max_steps": avg("max_steps"),
            "avg_gini": avg("gini"),
            "avg_gini_norm": avg("gini_norm"),
            "avg_hhi": avg("hhi"),
            "avg_max_share": avg("max_share"),
            "avg_mean_q": avg("mean_q"),
        }
        csv_rows.append(row)
        print(
            f"{dist:>4} {mult:>4} {n:>6} | "
            f"{row['avg_num_loops']:>6.2f} {row['avg_max_len']:>6.2f} "
            f"{row['avg_avg_steps']:>7.2f} {row['avg_max_steps']:>7.1f} | "
            f"{row['avg_gini']:>6.3f} {row['avg_gini_norm']:>6.3f} {row['avg_max_share']:>6.3f} | "
            f"{row['avg_mean_q']:>6.1f}"
        )


def compare_extremes(
    records: List[Dict[str, Any]],
    p: int,
    comp_rows: List[Dict[str, Any]],
) -> None:
    """Compare all-collide (dist=1) vs all-distinct (max_mult=1) with gcd(Q)==1."""
    collide = [r for r in records if r["gcd_q"] == 1 and r["distinct_mod_p"] == 1]
    distinct = [r for r in records if r["gcd_q"] == 1 and r["max_mult"] == 1]
    if len(collide) < 5 or len(distinct) < 5:
        return

    metrics = [
        ("num_loops", "Loop count"),
        ("is_single_loop", "Single-loop rate"),
        ("max_len", "Max loop length"),
        ("min_len", "Min loop length"),
        ("has_len50", "Has loop>=50 rate"),
        ("avg_steps", "Avg steps"),
        ("max_steps", "Max steps"),
        ("gini", "Gini"),
        ("gini_norm", "Gini (normalized)"),
        ("hhi", "HHI"),
        ("max_share", "Top loop share"),
    ]
    print(f"\n=== Extreme Comparison p={p} (gcd(Q)==1): All-Collide (N={len(collide)}) vs All-Distinct (N={len(distinct)}) ===")
    print(f"{'Metric':<20} | {'Collide mean/med':>18} | {'Distinct mean/med':>18} | {'p-value':>10}")
    print("-" * 76)
    for key, label in metrics:
        vx = [float(r[key]) for r in collide]
        vy = [float(r[key]) for r in distinct]
        mx, medx = statistics.mean(vx), statistics.median(vx)
        my, medy = statistics.mean(vy), statistics.median(vy)
        pval = mann_whitney_u_pvalue(vx, vy)
        print(f"{label:<20} | {mx:>8.3f} / {medx:>7.3f} | {my:>8.3f} / {medy:>7.3f} | {pval:>10.2e}")
        comp_rows.append(
            {
                "p": p,
                "metric": key,
                "label": label,
                "n_collide": len(vx),
                "collide_mean": mx,
                "collide_median": medx,
                "n_distinct": len(vy),
                "distinct_mean": my,
                "distinct_median": medy,
                "p_value": pval,
            }
        )


def run_ctree_sampling(
    records: List[Dict[str, Any]],
    p: int,
    max_h: int,
    sample_n: int,
    seed: int,
    ctree_rows: List[Dict[str, Any]],
) -> None:
    """Sample all-collide and all-distinct systems (gcd==1) and measure CTree BFS metrics."""
    rng = random.Random(seed)
    collide = [r for r in records if r["gcd_q"] == 1 and r["distinct_mod_p"] == 1 and r["top_loop_min_val"] > 0]
    distinct = [r for r in records if r["gcd_q"] == 1 and r["max_mult"] == 1 and r["top_loop_min_val"] > 0]
    if len(collide) < 5 or len(distinct) < 5:
        return

    s_col = rng.sample(collide, min(sample_n, len(collide)))
    s_dis = rng.sample(distinct, min(sample_n, len(distinct)))

    for group_label, sample in [("all_collide", s_col), ("all_distinct", s_dis)]:
        metrics_list = []
        for r in sample:
            m = measure_ctree_bfs(p, r["q_list"], r["top_loop_min_val"], max_h=max_h)
            metrics_list.append(m)
            ctree_rows.append(
                {
                    "p": p,
                    "group": group_label,
                    "system_id": r["system_id"],
                    "root": r["top_loop_min_val"],
                    "max_h": max_h,
                    "total_nodes": m["total_nodes"],
                    "max_width": m["max_width"],
                    "width_at_h": m["width_at_h"],
                    "branch_nodes": m["branch_nodes"],
                    "burst_nodes": m["burst_nodes"],
                }
            )
        print(f"\n--- CTree BFS p={p} {group_label} (N={len(metrics_list)}, H={max_h}) ---")
        for k in ["total_nodes", "max_width", "width_at_h", "branch_nodes", "burst_nodes"]:
            vals = [m[k] for m in metrics_list]
            print(f"  {k:<12}: mean={statistics.mean(vals):8.2f}, median={statistics.median(vals):8.2f}, max={max(vals)}")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze q_r mod p collision effects across p=5..9 DBs.")
    parser.add_argument("--p", type=int, nargs="+", default=[5, 6, 7, 8, 9], help="Values of p to analyze.")
    parser.add_argument("--max-h", type=int, default=12, help="Max CTree BFS height.")
    parser.add_argument("--sample-n", type=int, default=80, help="Sample size per group for CTree BFS.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling.")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/modp_collision"), help="Output directory for CSVs.")
    args = parser.parse_args()

    group_csv_rows: List[Dict[str, Any]] = []
    comp_csv_rows: List[Dict[str, Any]] = []
    ctree_csv_rows: List[Dict[str, Any]] = []

    for p in args.p:
        db_path = Path(f"data/p{p}/summary_p{p}.db")
        if not db_path.exists():
            print(f"[skip] {db_path} not found.")
            continue
        records = load_system_records(p, db_path)
        summarize_by_collision_group(records, p, "ALL", lambda _: True, group_csv_rows)
        summarize_by_collision_group(records, p, "gcd(Q)==1", lambda r: r["gcd_q"] == 1, group_csv_rows)
        compare_extremes(records, p, comp_csv_rows)
        run_ctree_sampling(records, p, args.max_h, args.sample_n, args.seed, ctree_csv_rows)

    write_csv(args.out_dir / "summary_by_group.csv", group_csv_rows)
    write_csv(args.out_dir / "extreme_comparison.csv", comp_csv_rows)
    write_csv(args.out_dir / "ctree_bfs_samples.csv", ctree_csv_rows)
    print(f"\nSaved CSVs to {args.out_dir}/")


if __name__ == "__main__":
    main()

