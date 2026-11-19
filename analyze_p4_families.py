"""
Enumerate all primitive Q-families (orbits under scalar multiplication + swap for g % 3 == 2)
in the p=4 30x30 grid (q1 in [2..89], q2 in [1..88]), compute tree personality statistics
across each family, and export CSV tables.

Inputs:
  - outputs/p4_900dbs_summary.csv
  - outputs/p4_ctree_nodes_h10_30x30.csv

Outputs:
  - outputs/p4_families_all_617.csv
  - outputs/p4_families_multi_155.csv
  - outputs/p4_families_members.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_900_summary(path: Path) -> Dict[Tuple[int, int], Dict[str, Any]]:
    data: Dict[Tuple[int, int], Dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            q1 = int(row["q1"])
            q2 = int(row["q2"])
            lens_raw = [int(x) for x in row["loop_lengths"].split(";") if x.strip()]
            data[(q1, q2)] = {
                "q1": q1,
                "q2": q2,
                "gcd": int(row["gcd(q1,q2)"]),
                "num_loops": int(row["num_loops"]),
                "dom_share": float(row["dominant_loop_share_pct"]),
                "max_steps": int(row["max_steps"]),
                "avg_steps": float(row["avg_steps"]),
                "loop_lengths": lens_raw,
                "max_loop_len": max(lens_raw, default=0),
                "min_loop_len": min(lens_raw, default=0),
            }
    return data


def load_h10_nodes(path: Path) -> Dict[Tuple[int, int], int]:
    nodes: Dict[Tuple[int, int], int] = {}
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        q1_vals = [int(x) for x in header[1:]]
        for row in reader:
            q2 = int(row[0])
            for q1, val in zip(q1_vals, row[1:]):
                nodes[(q1, q2)] = int(val)
    return nodes


def classify_personality(fam: Dict[str, Any]) -> str:
    """Generate a concise Japanese personality tag for a Q-family."""
    tags: List[str] = []
    # 1. Base loop structure
    if fam["base_num_loops"] == 1:
        tags.append("単ループ一本杉")
    elif fam["base_max_loop_len"] >= 50:
        tags.append("巨大ループ搭載")
    else:
        tags.append(f"多ループ({fam['base_num_loops']}本)")

    # 2. CTree H=10 scale
    mn = fam["mean_nodes_h10"]
    if mn >= 10000:
        tags.append("超爆発型")
    elif mn >= 5000:
        tags.append("大型")
    elif mn <= 1500:
        tags.append("スリム省ノード型")
    else:
        tags.append("標準規模")

    # 3. Convergence speed
    st = fam["mean_avg_steps"]
    if st < 65.0:
        tags.append("超高速収束")
    elif st > 95.0:
        tags.append("長距離軌道")

    return " / ".join(tags)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze all primitive Q-families in p=4 30x30 grid.")
    parser.add_argument("--summary-csv", type=Path, default=Path("outputs/p4_900dbs_summary.csv"))
    parser.add_argument("--h10-csv", type=Path, default=Path("outputs/p4_ctree_nodes_h10_30x30.csv"))
    args = parser.parse_args()

    summary = load_900_summary(args.summary_csv)
    h10_nodes = load_h10_nodes(args.h10_csv)

    families_raw: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
    member_rows: List[Dict[str, Any]] = []

    for (q1, q2), rec in sorted(summary.items()):
        g = rec["gcd"]
        a, b = q1 // g, q2 // g
        base = (b, a) if (g % 3 == 2) else (a, b)
        n_h10 = h10_nodes[(q1, q2)]
        m_rec = {
            **rec,
            "base_q1": base[0],
            "base_q2": base[1],
            "nodes_h10": n_h10,
            "mod4": f"({q1%4},{q2%4})",
        }
        families_raw[base].append(m_rec)
        member_rows.append(
            {
                "base": f"({base[0]},{base[1]})",
                "g": g,
                "q1": q1,
                "q2": q2,
                "mod4": m_rec["mod4"],
                "num_loops": rec["num_loops"],
                "max_loop_len": rec["max_loop_len"],
                "dom_share_pct": rec["dom_share"],
                "avg_steps": rec["avg_steps"],
                "max_steps": rec["max_steps"],
                "nodes_h10": n_h10,
            }
        )

    fam_rows: List[Dict[str, Any]] = []
    for base, members in sorted(families_raw.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        members.sort(key=lambda x: x["gcd"])
        base_m = members[0]  # g=1 is always in grid
        nodes_list = [m["nodes_h10"] for m in members]
        steps_list = [m["avg_steps"] for m in members]
        max_steps_list = [m["max_steps"] for m in members]
        loops_list = [m["num_loops"] for m in members]
        shares_list = [m["dom_share"] for m in members]

        fam_rec: Dict[str, Any] = {
            "base_q1": base[0],
            "base_q2": base[1],
            "base_str": f"({base[0]},{base[1]})",
            "base_mod4": f"({base[0]%4},{base[1]%4})",
            "family_size": len(members),
            "members_str": "; ".join(f"g={m['gcd']}:({m['q1']},{m['q2']})" for m in members),
            "base_num_loops": base_m["num_loops"],
            "base_loop_lengths": ";".join(str(x) for x in base_m["loop_lengths"]),
            "base_max_loop_len": base_m["max_loop_len"],
            "base_dom_share_pct": base_m["dom_share"],
            "base_avg_steps": base_m["avg_steps"],
            "base_nodes_h10": base_m["nodes_h10"],
            "mean_nodes_h10": round(statistics.mean(nodes_list), 1),
            "min_nodes_h10": min(nodes_list),
            "max_nodes_h10": max(nodes_list),
            "nodes_ratio_max_min": round(max(nodes_list) / max(1, min(nodes_list)), 2),
            "mean_avg_steps": round(statistics.mean(steps_list), 2),
            "min_avg_steps": round(min(steps_list), 2),
            "max_avg_steps": round(max(steps_list), 2),
            "mean_max_steps": round(statistics.mean(max_steps_list), 1),
            "mean_num_loops": round(statistics.mean(loops_list), 2),
            "max_num_loops": max(loops_list),
            "mean_dom_share_pct": round(statistics.mean(shares_list), 2),
        }
        fam_rec["personality"] = classify_personality(fam_rec)
        fam_rows.append(fam_rec)

    multi_rows = [r for r in fam_rows if r["family_size"] >= 2]
    write_csv(Path("outputs/p4_families_all_617.csv"), fam_rows)
    write_csv(Path("outputs/p4_families_multi_155.csv"), multi_rows)
    write_csv(Path("outputs/p4_families_members.csv"), member_rows)

    print(f"Total primitive families: {len(fam_rows)}")
    print(f"Multi-member families (size >= 2): {len(multi_rows)} (total cells = {sum(r['family_size'] for r in multi_rows)})")
    print("\n--- Top 12 Multi-Member Families by mean_nodes_h10 ---")
    for r in sorted(multi_rows, key=lambda x: -x["mean_nodes_h10"])[:12]:
        print(
            f"  {r['base_str']:<8} (size={r['family_size']:>2}) | "
            f"mean_nodes={r['mean_nodes_h10']:>8.1f} (min={r['min_nodes_h10']:>5}, max={r['max_nodes_h10']:>5}) | "
            f"avgStp={r['mean_avg_steps']:>5.1f} | loops={r['base_loop_lengths']:<14} | {r['personality']}"
        )

    print("\n--- Bottom 10 Multi-Member Families by mean_nodes_h10 (Slimmest) ---")
    for r in sorted(multi_rows, key=lambda x: x["mean_nodes_h10"])[:10]:
        print(
            f"  {r['base_str']:<8} (size={r['family_size']:>2}) | "
            f"mean_nodes={r['mean_nodes_h10']:>8.1f} (min={r['min_nodes_h10']:>5}, max={r['max_nodes_h10']:>5}) | "
            f"avgStp={r['mean_avg_steps']:>5.1f} | loops={r['base_loop_lengths']:<14} | {r['personality']}"
        )

    print("\n--- Personality Type Counts (across 155 Multi-Member Families) ---")
    p_counts: Dict[str, int] = defaultdict(int)
    for r in multi_rows:
        p_counts[r["personality"]] += 1
    for k, v in sorted(p_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<45}: {v}")


if __name__ == "__main__":
    main()

