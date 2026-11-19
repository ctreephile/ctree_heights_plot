#!/usr/bin/env python3
"""
Cross-System Verification & Visualization of the Universal Euler Totient Basin Law
across p = 3, 4, 5 (`plot_euler_totient_p3_p4_p5.py`).

Generates:
  - `docs/2026_1107/euler_totient_p3_p4_p5.png`
  - `docs/2026_1107/euler_totient_p3_p4_p5.svg`
"""

from __future__ import annotations

import csv
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def core_p(val: int, primes: Tuple[int, ...]) -> int:
    res = abs(val)
    for p in primes:
        while res > 0 and res % p == 0:
            res //= p
    return res


def euler_phi(n: int) -> int:
    res = n
    p = 2
    temp = n
    while p * p <= temp:
        if temp % p == 0:
            while temp % p == 0:
                temp //= p
            res -= res // p
        p += 1
    if temp > 1:
        res -= res // temp
    return res


def get_divisors(n: int) -> List[int]:
    divs = []
    for i in range(1, int(math.isqrt(n)) + 1):
        if n % i == 0:
            divs.append(i)
            if i * i != n:
                divs.append(n // i)
    return sorted(divs)


def verify_p4_from_csv(csv_path: Path = Path("outputs/p4_all_loops_catalog.csv")) -> List[Tuple[float, float]]:
    if not csv_path.exists():
        return []
    loops_by_q: Dict[Tuple[int, int], List[Tuple[int, float]]] = defaultdict(list)
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q1 = int(row["q1"])
            q2 = int(row["q2"])
            min_v = int(row["min_value"])
            share = int(row["basin_count"]) / 100000.0
            loops_by_q[(q1, q2)].append((min_v, share))

    pairs: List[Tuple[float, float]] = []
    for (q1, q2), lps in loops_by_q.items():
        g = math.gcd(q1, q2)
        m = core_p(g, (2,))
        if m <= 1:
            continue
        layer_obs: Dict[int, float] = defaultdict(float)
        for min_v, sh in lps:
            d_layer = m // math.gcd(min_v, m)
            layer_obs[d_layer] += sh
        for d in get_divisors(m):
            theo = euler_phi(d) / m
            obs = layer_obs.get(d, 0.0)
            pairs.append((theo * 100.0, obs * 100.0))
    return pairs


def verify_sqlite_db(db_path: Path, primes: Tuple[int, ...]) -> List[Tuple[float, float]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    sys_rows = conn.execute("SELECT system_id, gcd_q FROM systems").fetchall()
    loop_rows = conn.execute("SELECT system_id, min_value, basin_share FROM loops").fetchall()
    conn.close()

    loops_by_sid: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    for sid, min_v, sh in loop_rows:
        loops_by_sid[int(sid)].append((int(min_v), float(sh)))

    pairs: List[Tuple[float, float]] = []
    for sid, gcd_q in sys_rows:
        m = core_p(int(gcd_q), primes)
        if m <= 1:
            continue
        layer_obs: Dict[int, float] = defaultdict(float)
        for min_v, sh in loops_by_sid.get(int(sid), []):
            d_layer = m // math.gcd(min_v, m)
            layer_obs[d_layer] += sh
        for d in get_divisors(m):
            theo = euler_phi(d) / m
            obs = layer_obs.get(d, 0.0)
            pairs.append((theo * 100.0, obs * 100.0))
    return pairs


def main() -> None:
    p3_pairs = verify_sqlite_db(Path("data/p3/summary_p3.db"), (3,))
    p4_pairs = verify_p4_from_csv(Path("outputs/p4_all_loops_catalog.csv"))
    p5_pairs = verify_sqlite_db(Path("data/p5/summary_p5.db"), (5,))

    for label, pairs in [("p=3", p3_pairs), ("p=4", p4_pairs), ("p=5", p5_pairs)]:
        if pairs:
            errs = [abs(t - o) for t, o in pairs]
            print(f"{label}: {len(pairs)} layers, mean abs err = {statistics.mean(errs):.5f}%, max = {max(errs):.5f}%")

    out_dir = Path("docs/2026_1107")
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)
    ax.plot([0, 100], [0, 100], "k--", lw=1.2, label="Theoretical φ(d)/m")
    for label, pairs, col in [("p=3", p3_pairs, "#0284c7"), ("p=4", p4_pairs, "#16a34a"), ("p=5", p5_pairs, "#dc2626")]:
        if pairs:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            ax.scatter(xs, ys, s=16, alpha=0.75, color=col, label=f"{label} ({len(pairs)} layers)")
    ax.set_xlabel("Theoretical Share φ(d)/m (%)")
    ax.set_ylabel("Observed Share (%)")
    ax.set_title("Universal Euler Totient Basin Law Across p = 3, 4, 5")
    ax.legend()
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_dir / "euler_totient_p3_p4_p5.png", dpi=180)
    fig.savefig(out_dir / "euler_totient_p3_p4_p5.svg")
    plt.close(fig)
    print(f"Saved plots to {out_dir}/euler_totient_p3_p4_p5.(png|svg)")


if __name__ == "__main__":
    main()

