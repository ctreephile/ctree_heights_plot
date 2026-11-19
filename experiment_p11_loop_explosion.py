#!/usr/bin/env python3
"""
Experiment 1 (p >= 10): Targeted Prediction & Verification of Loop Count Explosion
for p = 11 (d = 10, 9D Q space).

Strategy:
  1. Scan 300 small-offset m=1 systems at p = 11 (n = 1..3000) to find a high-diversity
     seed parent Q_0 with M_0 >= 5 loops.
  2. Predict loop explosion by scaling Q_0 with composite multipliers g coprime to 10 & 11:
     g in {3, 7, 21, 63, 189} (having 2, 2, 4, 6, 8 divisors respectively).
     Using (Z/10Z)^x permutation: q'_{r'} = g * q_r where r' = (g * r) mod 10.
  3. Evaluate each scaled system up to n = 1..100,000, verify:
     - 100% parent loop inheritance (g * min_val)
     - Exact Euler Totient layer share law (phi(d) / m)
     - Loop count explosion M across layers
  4. Write report to `docs/2026_1113/p11_loop_explosion_report.md`.
"""

from __future__ import annotations

import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.engine import canonicalize_cycle

P_VAL = 11
D_VAL = 10  # p - 1
REPORT_PATH = Path("docs/2026_1113/p11_loop_explosion_report.md")


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


def permute_q_p11(q_tuple: Tuple[int, ...], g: int) -> Tuple[int, ...]:
    """(Z/10Z)^x permutation: q'_{r'} = g * q_r where r' = (g * r) mod 10."""
    if math.gcd(g, D_VAL) != 1:
        raise ValueError(f"gcd({g}, 10) != 1")
    q_new = [0] * D_VAL
    for r in range(1, D_VAL):
        r_prime = (g * r) % D_VAL
        q_new[r_prime] = g * q_tuple[r - 1]
    return tuple(q_new[1:])


def evaluate_p11(q_tuple: Tuple[int, ...], max_n: int, max_steps: int = 3000) -> Dict[str, Any]:
    t0 = time.perf_counter()
    q1, q2, q3, q4, q5, q6, q7, q8, q9 = q_tuple
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
            r = curr % 10
            if r == 0:
                curr //= 10
            elif r == 1:
                curr = 11 * curr + q1
            elif r == 2:
                curr = 11 * curr + q2
            elif r == 3:
                curr = 11 * curr + q3
            elif r == 4:
                curr = 11 * curr + q4
            elif r == 5:
                curr = 11 * curr + q5
            elif r == 6:
                curr = 11 * curr + q6
            elif r == 7:
                curr = 11 * curr + q7
            elif r == 8:
                curr = 11 * curr + q8
            else:
                curr = 11 * curr + q9

        if curr in steps_cache:
            ks, klid = steps_cache[curr]
            for idx, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (ks + idx, klid)
        elif curr in path_index:
            ls = path_index[curr]
            canon = canonicalize_cycle(path[ls:])
            min_v = canon[0]
            if min_v not in loops_by_min:
                l_div = sum(1 for v in canon if v % 10 == 0)
                loops_by_min[min_v] = {
                    "loop_id": next_loop_id,
                    "min_value": min_v,
                    "length": len(canon),
                    "L": l_div,
                    "K": len(canon) - l_div,
                    "elements": canon,
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
    max_step_seen = 0
    for n in range(1, max_n + 1):
        st, lid = steps_cache[n]
        if lid == 0 or st < 0:
            unresolved += 1
        else:
            basin_counts[lid] += 1
            if st > max_step_seen:
                max_step_seen = st

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
        "max_steps": max_step_seen,
        "loops": loops_out,
        "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
    }


def main() -> None:
    t_start = time.perf_counter()
    rng = random.Random(20261113)

    # Step 1: Search 300 small-offset m=1 systems to find a high-diversity seed parent Q_0
    print("[Step 1] Scanning 300 candidate p=11 (d=10) systems for a high-diversity seed parent...")
    candidates: List[Dict[str, Any]] = []
    seen = set()
    # Include the canonical minimal system (9,8,7,6,5,4,3,2,1) plus 299 small random k_r in {0,1,2,3}
    base_tuples: List[Tuple[int, ...]] = [(9, 8, 7, 6, 5, 4, 3, 2, 1)]
    while len(base_tuples) < 300:
        tup = tuple(10 * rng.randint(0, 3) + (10 - r) for r in range(1, 10))
        if tup not in seen and math.gcd(*tup) == 1:
            seen.add(tup)
            base_tuples.append(tup)

    for tup in base_tuples:
        res = evaluate_p11(tup, max_n=3000, max_steps=2000)
        candidates.append(res)

    candidates.sort(key=lambda x: (x["num_loops"], x["max_steps"]), reverse=True)
    best_seed = candidates[0]
    q0 = best_seed["q"]
    print(f"  Best seed Q_0 = {q0} with M_0 = {best_seed['num_loops']} loops (in {time.perf_counter()-t_start:.1f}s)")

    # Re-evaluate Q_0 at high resolution (max_n = 100,000)
    res_q0 = evaluate_p11(q0, max_n=100000, max_steps=3000)
    parent_mins = {lp["min_value"] for lp in res_q0["loops"]}

    # Step 2: Predict & verify loop explosion across composite multipliers g
    multipliers = [1, 3, 7, 21, 63, 189]
    chain_results: List[Dict[str, Any]] = []
    for g in multipliers:
        qg = q0 if g == 1 else permute_q_p11(q0, g)
        max_n_eval = 100000 if g <= 63 else 500000
        res_g = evaluate_p11(qg, max_n=max_n_eval, max_steps=3500)
        child_mins = {lp["min_value"] for lp in res_g["loops"]}
        expected_mins = {g * mv for mv in parent_mins}
        inherited_ok = expected_mins.issubset(child_mins)

        # Check Euler totient layer shares
        m = g  # since gcd(q0)=1 and gcd(g, 11)=1
        layer_shares: Dict[int, float] = defaultdict(float)
        layer_counts: Dict[int, int] = defaultdict(int)
        for lp in res_g["loops"]:
            d_layer = m // math.gcd(lp["min_value"], m)
            layer_shares[d_layer] += lp["basin_share"]
            layer_counts[d_layer] += 1

        divs = get_divisors(m)
        max_err_pct = 0.0
        layer_details = []
        for d_div in divs:
            theo = euler_phi(d_div) / m * 100.0
            obs = layer_shares.get(d_div, 0.0) * 100.0
            err = abs(obs - theo)
            max_err_pct = max(max_err_pct, err)
            layer_details.append({
                "d": d_div,
                "theo_pct": theo,
                "obs_pct": obs,
                "err_pct": err,
                "num_loops": layer_counts.get(d_div, 0),
            })

        chain_results.append({
            "g": g,
            "q": qg,
            "num_divs": len(divs),
            "num_loops": res_g["num_loops"],
            "unresolved": res_g["unresolved"],
            "max_steps": res_g["max_steps"],
            "inherited_ok": inherited_ok,
            "max_err_pct": max_err_pct,
            "layer_details": layer_details,
            "elapsed_ms": res_g["elapsed_ms"],
        })
        print(
            f"  g={g:3d} (layers={len(divs)}): M={res_g['num_loops']:2d} loops | "
            f"inherited={inherited_ok} | max_euler_err={max_err_pct:.3f}% | {res_g['elapsed_ms']:.0f}ms"
        )

    # Write Report
    lines: List[str] = []
    lines.append("# 実験 1 (`p = 11`, $d = 10$): ループ数爆発の仮説予測とピンポイント検証レポート\n")
    lines.append("## 1. 実験の仮説と設計")
    lines.append("1. **同一層内での高多様性種親（Seed Parent）の発掘**: 9次元パラメータ空間 ($Q = [q_1, \\dots, q_9]$) から、小オフセット領域 ($k_r \\in \\{0..3\\}$) を 300 点サンプリングし、元々ループ数 $M_0$ が多い親システム $Q_0$ を特定する。")
    lines.append("2. **高度合成数倍率 $g$ × $(\\mathbb{Z}/10\\mathbb{Z})^\\times$ 置換による多層ループ爆発の予測**:")
    lines.append("   - $p = 11, d = 10$ の両方に互いに素な高度合成数倍率 $g \\in \\{3, 7, 21, 63, 189\\}$ で $Q_0$ を置換スケールする。")
    lines.append("   - **予測 A**: 親の全 $M_0$ ループが $g$ 倍で 100% 継承される。")
    lines.append("   - **予測 B**: $g$ の約数個数（$2, 2, 4, 6, 8$ 層）に応じて層分裂し、各層の吸引率合計が $\\varphi(d)/g$ に厳密一致する。")
    lines.append("   - **予測 C**: 各層に新規ループが創発することで、ループ総数 $M$ が爆発的に増大する。\n")

    lines.append("## 2. ステップ 1：種親探索（300 サンプル, `n = 1..3000`）の上位システム\n")
    lines.append("| 順位 | システム $Q_0$ | ループ数 $M_0$ | 最大ステップ数 |")
    lines.append("| :---: | :--- | :---: | :---: |")
    for idx, c in enumerate(candidates[:5], 1):
        lines.append(f"| {idx} | `{c['q']}` | **{c['num_loops']}** | {c['max_steps']} |")
    lines.append("")

    lines.append("## 3. ステップ 2：高度合成数スケール置換によるループ数爆発の検証結果\n")
    lines.append(f"最優秀種親 $Q_0 = \\text{{`{q0}`}}$ ($M_0 = {res_q0['num_loops']}$) を基準に検証しました。\n")
    lines.append("| 倍率 $g$ | 置換後システム $Q'$ | 予測層数 $\\tau(g)$ | 実測ループ数 $M$ | 親ループ継承 | オイラー法則最大誤差 | 未解決軌道 | 計算時間 |")
    lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for cr in chain_results:
        inh_str = "100% 一致" if cr["inherited_ok"] else "不一致"
        lines.append(
            f"| **$g={cr['g']}$** | `{cr['q']}` | {cr['num_divs']} 層 | **{cr['num_loops']} 個** | {inh_str} | `{cr['max_err_pct']:.3f}%` | {cr['unresolved']} | {cr['elapsed_ms']:.0f} ms |"
        )
    lines.append("")

    # Detailed layer breakdown for g=189
    last_cr = chain_results[-1]
    lines.append(f"## 4. 最大構成 $g = {last_cr['g']}$ ($M = {last_cr['num_loops']}$ ループ) の全 {last_cr['num_divs']} 層の内訳\n")
    lines.append("| 層 $d \\mid 189$ | 理論吸引率 $\\varphi(d)/189$ | 実測吸引率 | 誤差 | 該当層内のループ数 |")
    lines.append("| :---: | :---: | :---: | :---: | :---: |")
    for ld in last_cr["layer_details"]:
        lines.append(
            f"| **$d = {ld['d']}$** | {ld['theo_pct']:.3f}% | **{ld['obs_pct']:.3f}%** | `{ld['err_pct']:.3f}%` | **{ld['num_loops']}** ループ |"
        )
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH} in {time.perf_counter()-t_start:.1f}s.")


if __name__ == "__main__":
    main()
