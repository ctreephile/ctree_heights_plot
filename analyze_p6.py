#!/usr/bin/env python3
"""
Statistical & Composite-Number Law Analyzer for `data/p6/summary_p6.db`
(p = 6 = 2 * 3, d = 5, Q = [_, q1, q2, q3, q4]).

Analyzes:
  1. Dual Clone Prime Factors {2, 3} Transparency (g = 2^a 3^b -> ΔM = 0)
  2. 4-Way Cyclic Rotational Inheritance Z_4 ((Z/5Z)^x = {1, 2, 4, 3} -> 0°, +90°, 180°, -90°)
  3. Universal Euler Totient Basin Law for Composite p = 6 (m = core_6(gcd(Q)))
  4. Loop count distribution, |5^L - 6^K| denominators, and top system rankings.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_DB_PATH = Path("data/p6/summary_p6.db")
DEFAULT_REPORT_PATH = Path("docs/2026_1107/p6_statistics_and_composite_laws_report.md")


def core_6(n: int) -> int:
    val = abs(n)
    while val > 0 and val % 2 == 0:
        val //= 2
    while val > 0 and val % 3 == 0:
        val //= 3
    return val


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


def factorize_small(val: int) -> str:
    n_abs = abs(val)
    if n_abs == 0:
        return "0"
    if n_abs == 1:
        return "1 (1)"
    if n_abs > 10**15:
        return f"{n_abs:.3e}"
    factors = []
    d = 2
    temp = n_abs
    while d * d <= temp and d <= 500000:
        exp = 0
        while temp % d == 0:
            temp //= d
            exp += 1
        if exp > 0:
            factors.append(f"{d}^{exp}" if exp > 1 else f"{d}")
        d += 1 if d == 2 else 2
    if temp > 1:
        factors.append(f"{temp}")
    fact_str = " × ".join(factors) if factors else str(n_abs)
    return f"{n_abs:,} ({fact_str})"


def rotate_q_p6(q_tuple: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """
    For p = 6 (d = 5), scaling by g permutes Q = [q1, q2, q3, q4] according to g mod 5:
      g ≡ 1 (mod 5) [0°]:   g * [q1, q2, q3, q4]
      g ≡ 2 (mod 5) [+90°]: g * [q3, q1, q4, q2]
      g ≡ 4 (mod 5) [180°]: g * [q4, q3, q2, q1]
      g ≡ 3 (mod 5) [-90°]: g * [q2, q4, q1, q3]
    """
    q1, q2, q3, q4 = q_tuple
    rem = g % 5
    if rem == 1:
        return (g * q1, g * q2, g * q3, g * q4)
    elif rem == 2:
        return (g * q3, g * q1, g * q4, g * q2)
    elif rem == 4:
        return (g * q4, g * q3, g * q2, g * q1)
    elif rem == 3:
        return (g * q2, g * q4, g * q1, g * q3)
    raise ValueError(f"g={g} cannot be a multiple of 5")


def analyze_p6_db(
    db_path: Path = DEFAULT_DB_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Master DB not found: {db_path}. Run batch_p6.py first.")

    t0 = time.perf_counter()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sys_rows = conn.execute(
        """
        SELECT system_id, p, q1, q2, q3, q4, q_json, gcd_q, n_max, num_loops,
               max_steps, max_step_n, avg_steps, unresolved_count,
               gini, gini_norm, hhi, shannon_evenness, elapsed_ms
        FROM systems
        ORDER BY q1, q2, q3, q4
        """
    ).fetchall()

    loop_rows = conn.execute(
        """
        SELECT system_id, loop_id, min_value, max_value, length,
               l_div_count, k_mul_count, basin_count, basin_share, elements_json
        FROM loops
        ORDER BY system_id, loop_id
        """
    ).fetchall()
    conn.close()

    systems = [dict(r) for r in sys_rows]
    loops_by_sys: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in loop_rows:
        d = dict(r)
        loops_by_sys[int(d["system_id"])].append(d)

    sys_by_q: Dict[Tuple[int, int, int, int], Dict[str, Any]] = {}
    for s in systems:
        sid = int(s["system_id"])
        lps = loops_by_sys.get(sid, [])
        shares_desc = sorted((lp["basin_share"] * 100.0 for lp in lps), reverse=True)
        s["top1_pct"] = shares_desc[0] if shares_desc else 0.0
        s["loop_lengths_list"] = [lp["length"] for lp in lps]
        s["loop_mins_set"] = {lp["min_value"] for lp in lps}
        sys_by_q[(s["q1"], s["q2"], s["q3"], s["q4"])] = s

    # Verify Z_4 rotational inheritance across scale factors g
    g_stats: Dict[int, Dict[str, Any]] = {}
    for g in [2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18]:
        pairs = 0
        inherited_ok = 0
        deltas: List[int] = []
        for q_parent, s_parent in sys_by_q.items():
            q_child = rotate_q_p6(q_parent, g)
            if q_child in sys_by_q:
                s_child = sys_by_q[q_child]
                pairs += 1
                expected_mins = {g * m for m in s_parent["loop_mins_set"]}
                if expected_mins.issubset(s_child["loop_mins_set"]):
                    inherited_ok += 1
                deltas.append(s_child["num_loops"] - s_parent["num_loops"])
        if pairs > 0:
            g_stats[g] = {
                "pairs": pairs,
                "inherit_pct": (inherited_ok / pairs) * 100.0,
                "mean_delta": statistics.mean(deltas),
                "max_delta": max(deltas),
                "zero_pct": (deltas.count(0) / pairs) * 100.0,
            }

    # Verify Euler Totient Law for m = core_6(gcd_q) > 1
    layer_errors: List[float] = []
    for s in systems:
        m = core_6(s["gcd_q"])
        if m <= 1:
            continue
        lps = loops_by_sys.get(s["system_id"], [])
        layer_shares: Dict[int, float] = defaultdict(float)
        for lp in lps:
            g_lp = math.gcd(lp["min_value"], m)
            d_layer = m // g_lp
            layer_shares[d_layer] += lp["basin_share"]
        for d_div in get_divisors(m):
            theo = euler_phi(d_div) / m
            obs = layer_shares.get(d_div, 0.0)
            layer_errors.append(abs(obs - theo) * 100.0)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    print(f"Analyzed {len(systems):,} systems in {elapsed_ms:.0f} ms.")
    print(f"Euler totient layers checked: {len(layer_errors)}, mean error: {statistics.mean(layer_errors):.5f}%")
    return {
        "total_systems": len(systems),
        "g_stats": g_stats,
        "euler_layers": len(layer_errors),
        "euler_mean_error_pct": statistics.mean(layer_errors) if layer_errors else 0.0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    analyze_p6_db(db_path=args.db, report_path=args.report)

