#!/usr/bin/env python3
"""
Experiment 2 (p >= 10): Verification of New Algebraic Symmetry Groups
  - p = 10 = 2 * 5 (d = 9 = 3^2): (Z/9Z)^x ~= Z_6 with dual clone primes {2, 5}
    (2 is a primitive root mod 9 -> 60-deg 6-cycle clone rotation!)
  - p = 16 = 2^4 (d = 15 = 3 * 5): (Z/15Z)^x ~= Z_2 x Z_4 (first rank-8 non-cyclic group!)
    with single clone prime {2} (order 4 mod 15 -> 90-deg 4-cycle clone rotation!)

Generates `docs/2026_1113/p10_p16_symmetry_report.md`.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.engine import canonicalize_cycle

REPORT_PATH = Path("docs/2026_1113/p10_p16_symmetry_report.md")


def permute_q(q_tuple: Tuple[int, ...], d: int, g: int) -> Tuple[int, ...]:
    if math.gcd(g, d) != 1:
        raise ValueError(f"gcd({g}, {d}) != 1")
    q_new = [0] * d
    for r in range(1, d):
        r_prime = (g * r) % d
        q_new[r_prime] = g * q_tuple[r - 1]
    return tuple(q_new[1:])


def evaluate_general(p: int, q_tuple: Tuple[int, ...], max_n: int, max_steps: int = 3000) -> Dict[str, Any]:
    d = p - 1
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
            r = curr % d
            if r == 0:
                curr //= d
            else:
                curr = p * curr + q_tuple[r - 1]

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

    unresolved = sum(1 for n in range(1, max_n + 1) if steps_cache[n][1] == 0)
    return {
        "num_loops": len(loops_by_min),
        "loop_mins": set(loops_by_min.keys()),
        "unresolved": unresolved,
    }


def make_parent_systems(p: int, count: int, seed: int) -> List[Tuple[int, ...]]:
    d = p - 1
    rng = random.Random(seed)
    parents: List[Tuple[int, ...]] = [tuple(d - r for r in range(1, d))]
    seen = set(parents)
    while len(parents) < count:
        tup = tuple(d * rng.randint(0, 2) + (d - r) for r in range(1, d))
        if tup not in seen and math.gcd(*tup) == 1:
            seen.add(tup)
            parents.append(tup)
    return parents


def test_symmetry(
    p: int,
    g_list: List[int],
    num_parents: int = 8,
    base_max_n: int = 2000,
    seed: int = 100,
) -> List[Dict[str, Any]]:
    d = p - 1
    parents = make_parent_systems(p, num_parents, seed)
    parent_evals = [evaluate_general(p, q0, max_n=base_max_n) for q0 in parents]

    results = []
    for g in g_list:
        inherited_ok = 0
        deltas = []
        unres_tot = 0
        for q0, p_res in zip(parents, parent_evals):
            qg = permute_q(q0, d, g)
            c_res = evaluate_general(p, qg, max_n=base_max_n * g)
            expected = {g * mv for mv in p_res["loop_mins"]}
            if expected.issubset(c_res["loop_mins"]):
                inherited_ok += 1
            deltas.append(c_res["num_loops"] - p_res["num_loops"])
            unres_tot += c_res["unresolved"]
        results.append({
            "g": g,
            "g_mod_d": g % d,
            "pairs": num_parents,
            "inherit_pct": inherited_ok / num_parents * 100.0,
            "mean_delta": statistics.mean(deltas),
            "min_delta": min(deltas),
            "max_delta": max(deltas),
            "zero_pct": deltas.count(0) / num_parents * 100.0,
            "unresolved": unres_tot,
        })
    return results


def main() -> None:
    t0 = time.perf_counter()
    print("[1/2] Testing p = 10 = 2 * 5 (d = 9 = 3^2, (Z/9Z)^x ~= Z_6)...")
    p10_g = [2, 4, 5, 7, 8, 10, 11, 13, 14, 16]
    p10_res = test_symmetry(p=10, g_list=p10_g, num_parents=8, base_max_n=2000, seed=1010)
    for r in p10_res:
        print(
            f"  p=10 g={r['g']:2d} (mod 9={r['g_mod_d']}): inherit={r['inherit_pct']:.1f}% | "
            f"mean_dM={r['mean_delta']:+.2f} | zero%={r['zero_pct']:.1f}%"
        )

    print("[2/2] Testing p = 16 = 2^4 (d = 15 = 3 * 5, (Z/15Z)^x ~= Z_2 x Z_4)...")
    p16_g = [2, 4, 7, 8, 11, 13, 14, 16]
    p16_res = test_symmetry(p=16, g_list=p16_g, num_parents=8, base_max_n=2000, seed=1616)
    for r in p16_res:
        print(
            f"  p=16 g={r['g']:2d} (mod 15={r['g_mod_d']:2d}): inherit={r['inherit_pct']:.1f}% | "
            f"mean_dM={r['mean_delta']:+.2f} | zero%={r['zero_pct']:.1f}%"
        )

    # Write Report
    p10_angles = {1: "0° (恒等)", 2: "+60° 回転", 4: "+120° 回転", 8: "180° 鏡像", 7: "+240° 回転", 5: "+300° 回転"}
    p16_roles = {
        1: "0° (Z_4^0)",
        2: "+90° 回転 (Z_4^1)",
        4: "180° 回転 (Z_4^2)",
        8: "+270° 回転 (Z_4^3)",
        14: "鏡像対合 (-1)",
        13: "対合×90° (-2)",
        11: "対合×180° (-4)",
        7: "対合×270° (-8)",
    }

    lines: List[str] = []
    lines.append("# 実験 2 (`p = 10` & `p = 16`): 新たな乗法群 $(\\mathbb{Z}/d\\mathbb{Z})^\\times$ の対称性とクローン回転の検証レポート\n")

    lines.append("## 1. `p = 10 = 2 × 5` (`d = 9 = 3^2`, 8次元空間): $(\\mathbb{Z}/9\\mathbb{Z})^\\times \\cong \\mathbb{Z}_6$ と複合クローン `{2, 5}`\n")
    lines.append("- **予測**:")
    lines.append("  1. 初の奇素数べき乗の除数 $d = 9$ において、原始根 $2 \\pmod 9$（および逆元 $5 \\equiv 2^5 \\pmod 9$）は**クローン素因数 $\\{2, 5\\}$** である。")
    lines.append("  2. したがって $g = 2, 4, 5, 8, 10, 16$（$= 2^a 5^b$）はすべて **$\\Delta M = 0$（100% 完全クローン）** のまま、$\\mathbb{Z}_6$ の6方向回転（$60^\\circ$ 刻み）を巡回する。")
    lines.append("  3. 一方 $g = 7, 11, 13$ は新規 $\\gcd(n, m)$ 層を生み、$g = 14 = 2 \\times 7$ は $2$ が透明化して $m = 7$ のみ有効となる。\n")
    lines.append("| 倍率 $g$ | $g \\bmod 9$ | $\\mathbb{Z}_6$ 回転角 | 親ループ継承率 | 平均 $\\Delta M$ | $\\Delta M = 0$ 割合 | 素因数分解と役割 |")
    lines.append("| :---: | :---: | :--- | :---: | :---: | :---: | :--- |")
    for r in p10_res:
        g = r["g"]
        # check core_10
        v = g
        while v % 2 == 0:
            v //= 2
        while v % 5 == 0:
            v //= 5
        role = "**完全クローン ($2^a 5^b$, $\\Delta M=0$)**" if v == 1 else (
            f"クローン×新規層 ($m={v}$)" if g % 2 == 0 or g % 5 == 0 else f"新規層 ($m={v}$)"
        )
        lines.append(
            f"| **$g={g}$** | `{r['g_mod_d']}` | {p10_angles[r['g_mod_d']]} | **{r['inherit_pct']:.1f}%** | "
            f"`{r['mean_delta']:+.2f}` (`{r['min_delta']}..+{r['max_delta']}`) | **{r['zero_pct']:.1f}%** | {role} |"
        )
    lines.append("")

    lines.append("## 2. `p = 16 = 2^4` (`d = 15 = 3 × 5`, 14次元空間): 初の位数8非巡回群 $(\\mathbb{Z}/15\\mathbb{Z})^\\times \\cong \\mathbb{Z}_2 \\times \\mathbb{Z}_4$\n")
    lines.append("- **予測**:")
    lines.append("  1. $(\\mathbb{Z}/15\\mathbb{Z})^\\times$ は初の**位数8の非巡回群 $\\mathbb{Z}_2 \\times \\mathbb{Z}_4$** であり、8種類の置換すべてで親ループが **100%** 継承される。")
    lines.append("  2. 唯一のクローン素因数 $2$ は $2^4 \\equiv 1 \\pmod{15}$ のため、$g = 2, 4, 8, 16$ で **$\\Delta M = 0$ のまま4周期（$90^\\circ$ 刻み）回転クローン**となる。\n")
    lines.append("| 倍率 $g$ | $g \\bmod 15$ | $\\mathbb{Z}_2 \\times \\mathbb{Z}_4$ の元 | 親ループ継承率 | 平均 $\\Delta M$ | $\\Delta M = 0$ 割合 | 素因数分解と役割 |")
    lines.append("| :---: | :---: | :--- | :---: | :---: | :---: | :--- |")
    for r in p16_res:
        g = r["g"]
        v = g
        while v % 2 == 0:
            v //= 2
        role = "**完全クローン ($2^a$, $\\Delta M=0$)**" if v == 1 else f"新規層 ($m={v}$)"
        lines.append(
            f"| **$g={g}$** | `{r['g_mod_d']}` | {p16_roles[r['g_mod_d']]} | **{r['inherit_pct']:.1f}%** | "
            f"`{r['mean_delta']:+.2f}` (`{r['min_delta']}..+{r['max_delta']}`) | **{r['zero_pct']:.1f}%** | {role} |"
        )
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH} in {time.perf_counter()-t0:.2f}s.")


if __name__ == "__main__":
    main()

