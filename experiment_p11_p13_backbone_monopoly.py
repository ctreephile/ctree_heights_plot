#!/usr/bin/env python3
"""
Experiment 4 (p = 11 & p = 13): Artificial Design of Extreme Monopoly (G* > 0.999)
via the "Bare d^k Backbone Loop" Mechanism.

Theory from Phase 4:
  Even if a loop has the global minimum n_min = 1 (e.g., {1, d, d^2} with q_1 = d^2 - p),
  if NO multiplicative predecessors (v - q_r)/p exist for v in {1, d, d^2}, its ONLY h=1
  branch rootlet is d^3 (e.g., 1000 for p=11, 1728 for p=13).
  When another low-altitude loop coexists in the same layer (m=1), the bare backbone
  loop loses almost all small integers and collapses to < 0.1% share (G* > 0.998)!

Generates `docs/2026_1113/p11_p13_backbone_monopoly_report.md`.
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.engine import canonicalize_cycle, predecessors_pq

REPORT_PATH = Path("docs/2026_1113/p11_p13_backbone_monopoly_report.md")


def count_h1_rootlets(elems: List[int], p: int, q_tuple: Tuple[int, ...]) -> Tuple[int, Optional[int]]:
    d = p - 1
    q_norm: List[Optional[int]] = [None, *q_tuple]
    loop_set = set(elems)
    roots = []
    for v in elems:
        for pred in predecessors_pq(v, p, d, q_norm):
            pn = int(pred["n"])
            if pn not in loop_set:
                roots.append(pn)
    return len(roots), (min(roots) if roots else None)


def evaluate_sys(p: int, q_tuple: Tuple[int, ...], max_n: int = 30000, max_steps: int = 3000) -> Dict[str, Any]:
    d = p - 1
    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops_by_min: Dict[int, Dict[str, Any]] = {}
    next_id = 1

    for start_n in range(1, max_n + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_idx: Dict[int, int] = {}
        curr = start_n
        while curr not in steps_cache and curr not in path_idx and len(path) <= max_steps:
            path_idx[curr] = len(path)
            path.append(curr)
            r = curr % d
            curr = (curr // d) if r == 0 else (p * curr + q_tuple[r - 1])

        if curr in steps_cache:
            ks, klid = steps_cache[curr]
            for idx, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (ks + idx, klid)
        elif curr in path_idx:
            ls = path_idx[curr]
            canon = canonicalize_cycle(path[ls:])
            mv = canon[0]
            if mv not in loops_by_min:
                loops_by_min[mv] = {
                    "loop_id": next_id,
                    "min_value": mv,
                    "length": len(canon),
                    "elements": canon,
                }
                next_id += 1
            lid = loops_by_min[mv]["loop_id"]
            for val in path[ls:]:
                steps_cache[val] = (0, lid)
            for idx, val in enumerate(reversed(path[:ls]), start=1):
                steps_cache[val] = (idx, lid)
        else:
            for val in path:
                steps_cache[val] = (-1, 0)

    basin_counts: Dict[int, int] = {lp["loop_id"]: 0 for lp in loops_by_min.values()}
    unres = 0
    for n in range(1, max_n + 1):
        st, lid = steps_cache[n]
        if lid == 0 or st < 0:
            unres += 1
        else:
            basin_counts[lid] += 1

    res_tot = max_n - unres
    loops_out = []
    for lp in sorted(loops_by_min.values(), key=lambda x: x["min_value"]):
        cnt = basin_counts[lp["loop_id"]]
        r1_cnt, r1_min = count_h1_rootlets(lp["elements"], p, q_tuple)
        loops_out.append({
            **lp,
            "basin_count": cnt,
            "basin_share": cnt / res_tot if res_tot > 0 else 0.0,
            "r1_cnt": r1_cnt,
            "r1_min": r1_min,
        })

    m = len(loops_out)
    gini_norm = 0.0
    if m >= 2 and res_tot > 0:
        counts = sorted(lp["basin_count"] for lp in loops_out)
        wsum = sum((i + 1) * x for i, x in enumerate(counts))
        gini = max(0.0, min(1.0, (2.0 * wsum) / (m * res_tot) - (m + 1.0) / m))
        gini_norm = max(0.0, min(1.0, gini * (m / (m - 1.0))))

    return {
        "p": p,
        "q": q_tuple,
        "gcd_q": math.gcd(*q_tuple),
        "num_loops": m,
        "gini_norm": gini_norm,
        "unresolved": unres,
        "loops": loops_out,
    }


def design_bare_backbone_examples(p: int, trials: int = 80, seed: int = 42) -> List[Dict[str, Any]]:
    """
    Fix q_1 = d^2 - p so {1, d, d^2} is guaranteed to be a loop.
    Choose q_2..q_{d-1} with small k_r such that NO multiplicative predecessor
    attaches to d^2 (so h=1 rootlet of {1, d, d^2} is ONLY d^3!).
    """
    d = p - 1
    q1 = d * d - p
    rng = random.Random(seed)
    found: List[Dict[str, Any]] = []

    for _ in range(trials):
        qs = [q1]
        for r in range(2, d):
            # Pick small k_r in {0, 1, 2} that avoids (d^2 - q_r) % p == 0
            valid_ks = [
                k for k in range(4)
                if ((d * d) - (d * k + (d - r))) % p != 0
            ]
            k_pick = rng.choice(valid_ks[:2] if len(valid_ks) >= 2 else valid_ks)
            qs.append(d * k_pick + (d - r))
        q_tup = tuple(qs)
        if math.gcd(*q_tup) != 1:
            continue

        res = evaluate_sys(p, q_tup, max_n=10000, max_steps=2000)
        if res["num_loops"] == 2 and res["unresolved"] == 0:
            # Verify loop 1 is {1, d, d^2} with r1_cnt == 1 and r1_min == d^3
            lp1 = res["loops"][0]
            if lp1["min_value"] == 1 and lp1["r1_cnt"] == 1 and lp1["r1_min"] == d ** 3:
                # Re-evaluate at high resolution n = 1..50,000
                hi_res = evaluate_sys(p, q_tup, max_n=50000, max_steps=3000)
                if hi_res["num_loops"] == 2:
                    found.append(hi_res)
                    if len(found) >= 5:
                        break
    found.sort(key=lambda x: x["gini_norm"], reverse=True)
    return found


def main() -> None:
    t0 = time.perf_counter()
    print("[1/2] Designing bare-backbone extreme monopolies for p = 11 (d = 10, q1 = 89)...")
    p11_cases = design_bare_backbone_examples(11, trials=120, seed=1111)
    for c in p11_cases:
        l1, l2 = c["loops"][0], c["loops"][1]
        print(
            f"  p=11 G*={c['gini_norm']:.4f} | L1(min=1): {l1['basin_share']*100:.3f}% (r1={l1['r1_cnt']}, min={l1['r1_min']}) | "
            f"L2(min={l2['min_value']}): {l2['basin_share']*100:.3f}% (r1={l2['r1_cnt']}, min={l2['r1_min']})"
        )

    print("[2/2] Designing bare-backbone extreme monopolies for p = 13 (d = 12, q1 = 131)...")
    p13_cases = design_bare_backbone_examples(13, trials=120, seed=1313)
    for c in p13_cases:
        l1, l2 = c["loops"][0], c["loops"][1]
        print(
            f"  p=13 G*={c['gini_norm']:.4f} | L1(min=1): {l1['basin_share']*100:.3f}% (r1={l1['r1_cnt']}, min={l1['r1_min']}) | "
            f"L2(min={l2['min_value']}): {l2['basin_share']*100:.3f}% (r1={l2['r1_cnt']}, min={l2['r1_min']})"
        )

    all_cases = p11_cases + p13_cases
    lines: List[str] = []
    lines.append("# 実験 4 (`p = 11` & `p = 13`): 「丸裸の $d^k$ 背骨ループ」による極端独占 ($G^* > 0.998$) の人工設計レポート\n")
    lines.append("## 1. 設計理論と予測")
    lines.append("- **設計式**: $q_1 = d^2 - p$（`p=11` なら $q_1=89$、`p=13` なら $q_1=131$）と固定することで、$n_{\\min} = 1$ の最短閉路 `\\{1, d, d^2\\}` を強制的に埋め込む。")
    lines.append("- **丸裸化条件**: 残りの $q_2 \\dots q_{d-1}$ を $(d^2 - q_r) \\not\\equiv 0 \\pmod p$ となる小オフセットから選ぶことで、閉路要素のどこからも乗算逆像 $(v - q_r)/p$ が生えないようにする。")
    lines.append("- **予測**: すると $n_{\\min}=1$ ループの $h=1$ 枝は **$d^3$（`1000` や `1728`）の 1 本だけ** になり、同じ $m=1$ 層に別の小整数ループが共存すると、最小ループであるにもかかわらずシェアが **0.1% 未満（$G^* > 0.998$）** に転落する。\n")

    lines.append("## 2. 人工設計された逆転独占システム（`n = 1..50,000` で検証）\n")
    lines.append("| $p$ ($d$) | 設計システム $Q$ | $G^*$ | Loop 1 ($n_{\\min}=1$ 背骨): シェア, $R_1$ (最小枝) | Loop 2 (勝者): $n_{\\min}$, シェア, $R_1$ (最小枝) |")
    lines.append("| :---: | :--- | :---: | :--- | :--- |")
    for c in all_cases:
        l1, l2 = c["loops"][0], c["loops"][1]
        lines.append(
            f"| **$p={c['p']}$** ($d={c['p']-1}$) | `{c['q']}` | **{c['gini_norm']:.4f}** | "
            f"**{l1['basin_share']*100:.3f}%**, 枝={l1['r1_cnt']} (`{l1['r1_min']}`) | "
            f"$n_{{\\min}}={l2['min_value']}$, **{l2['basin_share']*100:.3f}%**, 枝={l2['r1_cnt']} (`{l2['r1_min']}`) |"
        )
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH} in {time.perf_counter()-t0:.2f}s.")


if __name__ == "__main__":
    main()

