#!/usr/bin/env python3
"""
Experiment 3 (p = 10 = 2 * 5, d = 9): Composite Clone Absorption & Euler Totient Extreme Test.

Tests that when scaling by g containing clone primes {2, 5} mixed with coprime m:
  e.g. g = 7, 14 (2*7), 35 (5*7), 70 (2*5*7), 77 (7*11), 154 (2*7*11),
the clone primes {2, 5} are completely absorbed (transparent), reducing the effective
modulus to m = core_10(gcd(Q)) = 7 or 77, and all layer basin shares match phi(d)/m.

Generates `docs/2026_1113/p10_clone_absorption_report.md`.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.engine import canonicalize_cycle

P_VAL = 10
D_VAL = 9
REPORT_PATH = Path("docs/2026_1113/p10_clone_absorption_report.md")


def core_10(n: int) -> int:
    val = abs(n)
    while val > 0 and val % 2 == 0:
        val //= 2
    while val > 0 and val % 5 == 0:
        val //= 5
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


def permute_q_p10(q_tuple: Tuple[int, ...], g: int) -> Tuple[int, ...]:
    if math.gcd(g, D_VAL) != 1:
        raise ValueError(f"gcd({g}, 9) != 1")
    q_new = [0] * D_VAL
    for r in range(1, D_VAL):
        r_prime = (g * r) % D_VAL
        q_new[r_prime] = g * q_tuple[r - 1]
    return tuple(q_new[1:])


def evaluate_p10(q_tuple: Tuple[int, ...], max_n: int, max_steps: int = 3500) -> Dict[str, Any]:
    t0 = time.perf_counter()
    q1, q2, q3, q4, q5, q6, q7, q8 = q_tuple
    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops_by_min: Dict[int, Dict[str, Any]] = {}
    next_loop_id = 1

    for start_n in range(1, max_n + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_index: Dict[int, int] = {}
        curr = start_n

        while curr not in steps_cache and curr not in path_index and len(path) <= max_steps:
            path_index[curr] = len(path)
            path.append(curr)
            r = curr % 9
            if r == 0:
                curr //= 9
            elif r == 1:
                curr = 10 * curr + q1
            elif r == 2:
                curr = 10 * curr + q2
            elif r == 3:
                curr = 10 * curr + q3
            elif r == 4:
                curr = 10 * curr + q4
            elif r == 5:
                curr = 10 * curr + q5
            elif r == 6:
                curr = 10 * curr + q6
            elif r == 7:
                curr = 10 * curr + q7
            else:
                curr = 10 * curr + q8

        if curr in steps_cache:
            ks, klid = steps_cache[curr]
            for idx, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (ks + idx, klid)
        elif curr in path_index:
            ls = path_index[curr]
            canon = canonicalize_cycle(path[ls:])
            min_v = canon[0]
            if min_v not in loops_by_min:
                loops_by_min[min_v] = {
                    "loop_id": next_loop_id,
                    "min_value": min_v,
                    "length": len(canon),
                }
                next_loop_id += 1
            lid = loops_by_min[min_v]["loop_id"]
            for val in path[ls:]:
                steps_cache[val] = (0, lid)
            for idx, val in enumerate(reversed(path[:ls]), start=1):
                steps_cache[val] = (idx, lid)
        else:
            for val in path:
                steps_cache[val] = (-1, 0)

    basin_counts: Dict[int, int] = {lp["loop_id"]: 0 for lp in loops_by_min.values()}
    unresolved = 0
    for n in range(1, max_n + 1):
        st, lid = steps_cache[n]
        if lid == 0 or st < 0:
            unresolved += 1
        else:
            basin_counts[lid] += 1

    resolved = max_n - unresolved
    loops_out = []
    for lp in sorted(loops_by_min.values(), key=lambda x: x["min_value"]):
        cnt = basin_counts[lp["loop_id"]]
        loops_out.append({
            **lp,
            "basin_count": cnt,
            "basin_share": cnt / resolved if resolved > 0 else 0.0,
        })

    return {
        "q": q_tuple,
        "gcd_q": math.gcd(*q_tuple),
        "num_loops": len(loops_out),
        "unresolved": unresolved,
        "loops": loops_out,
        "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
    }


def main() -> None:
    t0 = time.perf_counter()
    q0 = (8, 7, 6, 5, 4, 3, 2, 1)
    test_gs = [1, 2, 5, 10, 7, 14, 35, 70, 77, 154]
    results = []

    for g in test_gs:
        qg = q0 if g == 1 else permute_q_p10(q0, g)
        max_n = 100000 if g <= 70 else 154000
        res = evaluate_p10(qg, max_n=max_n)
        m = core_10(res["gcd_q"])
        divs = get_divisors(m)
        layer_shares: Dict[int, float] = defaultdict(float)
        layer_counts: Dict[int, int] = defaultdict(int)
        for lp in res["loops"]:
            d_layer = m // math.gcd(lp["min_value"], m)
            layer_shares[d_layer] += lp["basin_share"]
            layer_counts[d_layer] += 1

        max_err = 0.0
        details = []
        for d_div in divs:
            theo = euler_phi(d_div) / m * 100.0
            obs = layer_shares.get(d_div, 0.0) * 100.0
            err = abs(obs - theo)
            max_err = max(max_err, err)
            details.append((d_div, theo, obs, err, layer_counts.get(d_div, 0)))

        results.append({
            "g": g,
            "q": qg,
            "gcd_q": res["gcd_q"],
            "m": m,
            "num_loops": res["num_loops"],
            "unresolved": res["unresolved"],
            "max_err": max_err,
            "details": details,
            "elapsed_ms": res["elapsed_ms"],
        })
        print(
            f"  g={g:3d} (gcd={res['gcd_q']:3d} -> m=core_10={m:2d}): M={res['num_loops']:2d} | "
            f"max_euler_err={max_err:.4f}% | {res['elapsed_ms']:.0f}ms"
        )

    lines: List[str] = []
    lines.append("# 実験 3 (`p = 10 = 2 × 5`, $d = 9$): 複合クローン吸収 × オイラー関数法則 極限テストレポート\n")
    lines.append("- **基準親システム**: `Q_0 = (8, 7, 6, 5, 4, 3, 2, 1)` ($p = 10 = 2 \\times 5$, クローン素因数 $\\{2, 5\\}$)")
    lines.append("- **予測**: $\\gcd(Q')$ に $2$ や $5$ が含まれていても完全に透明化（吸収）され、すべての吸引率が有効法 $m = \\text{core}_{10}(\\gcd(Q'))$ の約数層 $d \\mid m$ にのみ $\\varphi(d)/m$ で分配される。\n")

    lines.append("## 1. 実験結果サマリー\n")
    lines.append("| 倍率 $g = \\gcd(Q')$ | 素因数分解 | 有効法 $m = \\text{core}_{10}(g)$ | 層数 $\\tau(m)$ | ループ数 $M$ | オイラー法則最大誤差 | 各層の実測値 vs 理論値 $\\varphi(d)/m$ |")
    lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
    for r in results:
        g = r["g"]
        # quick factorization string
        facs = []
        tmp = g
        for pr in [2, 5, 7, 11]:
            c = 0
            while tmp % pr == 0:
                tmp //= pr
                c += 1
            if c == 1:
                facs.append(str(pr))
            elif c > 1:
                facs.append(f"{pr}^{c}")
        f_str = " × ".join(facs) if facs else "1"
        layer_str = ", ".join(
            f"$d={d}$: **{obs:.2f}%** (理論 {theo:.2f}%, {lc}個)"
            for d, theo, obs, err, lc in r["details"]
        )
        lines.append(
            f"| **$g={g}$** | `{f_str}` | **$m={r['m']}$** | {len(r['details'])} 層 | **{r['num_loops']}** | `{r['max_err']:.4f}%` | {layer_str} |"
        )
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH} in {time.perf_counter()-t0:.2f}s.")


if __name__ == "__main__":
    main()

