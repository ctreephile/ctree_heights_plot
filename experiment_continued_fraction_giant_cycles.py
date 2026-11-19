#!/usr/bin/env python3
"""
Experiment 5 (p >= 10): Targeted Discovery of Giant Cycles & Long Trajectories
via Continued-Fraction Super-Approximations of ln(p) / ln(p - 1).

Theory:
  A cycle of (L divisions, K multiplications) has denominator D = |d^L - p^K|.
  When L/K is an unusually sharp continued-fraction convergent of ln(p)/ln(d)
  (meaning relative gap |d^L - p^K| / p^K is tiny), the net drift per step is
  near zero, enabling giant cycles (L + K >> 100) and extreme max_steps!

Generates `docs/2026_1113/giant_cycle_continued_fraction_report.md`.
"""

from __future__ import annotations

import math
import random
import time
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.engine import canonicalize_cycle

getcontext().prec = 80
REPORT_PATH = Path("docs/2026_1113/giant_cycle_continued_fraction_report.md")


def continued_fraction_convergents(p: int, max_l: int = 400) -> List[Tuple[int, int, float, int]]:
    """
    Compute continued-fraction convergents (L, K) of ln(p)/ln(p-1) with L <= max_l.
    Returns list of (L, K, rel_gap = |d^L - p^K| / p^K, next_partial_quotient).
    """
    d = p - 1
    x = Decimal(p).ln() / Decimal(d).ln()
    convs: List[Tuple[int, int, float, int]] = []

    p_prev, p_curr = 1, int(x)
    q_prev, q_curr = 0, 1
    rem = x - Decimal(p_curr)

    for _ in range(30):
        if p_curr > max_l:
            break
        if rem <= 0:
            break
        inv = Decimal(1) / rem
        a_next = int(inv)
        # Relative gap of (L=p_curr, K=q_curr)
        # |d^L - p^K| / p^K = |exp(L ln d - K ln p) - 1|
        diff = float(Decimal(p_curr) * Decimal(d).ln() - Decimal(q_curr) * Decimal(p).ln())
        rel_gap = abs(math.expm1(diff)) if abs(diff) < 50 else 1.0
        if p_curr + q_curr >= 30:
            convs.append((p_curr, q_curr, rel_gap, a_next))

        p_next = a_next * p_curr + p_prev
        q_next = a_next * q_curr + q_prev
        p_prev, p_curr = p_curr, p_next
        q_prev, q_curr = q_curr, q_next
        rem = inv - Decimal(a_next)

    return convs


def scan_p_for_giants(p: int, trials: int = 120, max_n: int = 3000, max_steps: int = 10000, seed: int = 1) -> Dict[str, Any]:
    d = p - 1
    rng = random.Random(seed)
    best_cycle_len = 0
    best_cycle_info: Dict[str, Any] = {}
    best_steps = 0
    best_steps_info: Dict[str, Any] = {}
    all_cycles_lk: List[Tuple[int, int]] = []

    for t_idx in range(trials):
        # Mix small and moderate offsets k_r in 0..5 to encourage near-neutral drift
        k_max = 2 if t_idx < 40 else (4 if t_idx < 80 else 7)
        q_tuple = tuple(d * rng.randint(0, k_max) + (d - r) for r in range(1, d))
        if math.gcd(*q_tuple) != 1:
            continue

        steps_cache: Dict[int, Tuple[int, int]] = {}
        loops_by_min: Dict[int, Dict[str, Any]] = {}
        next_id = 1
        max_st_seen = 0

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
                    st = ks + idx
                    steps_cache[val] = (st, klid)
                    if st > max_st_seen:
                        max_st_seen = st
            elif curr in path_idx:
                ls = path_idx[curr]
                canon = canonicalize_cycle(path[ls:])
                mv = canon[0]
                if mv not in loops_by_min:
                    l_div = sum(1 for v in canon if v % d == 0)
                    k_mul = len(canon) - l_div
                    loops_by_min[mv] = {
                        "loop_id": next_id,
                        "min_value": mv,
                        "length": len(canon),
                        "L": l_div,
                        "K": k_mul,
                    }
                    next_id += 1
                    all_cycles_lk.append((l_div, k_mul))
                    if len(canon) > best_cycle_len:
                        best_cycle_len = len(canon)
                        best_cycle_info = {
                            "q": q_tuple,
                            "min_value": mv,
                            "length": len(canon),
                            "L": l_div,
                            "K": k_mul,
                            "num_loops": len(loops_by_min),
                        }
                lid = loops_by_min[mv]["loop_id"]
                for val in path[ls:]:
                    steps_cache[val] = (0, lid)
                for idx, val in enumerate(reversed(path[:ls]), start=1):
                    steps_cache[val] = (idx, lid)
                    if idx > max_st_seen:
                        max_st_seen = idx
            else:
                for val in path:
                    steps_cache[val] = (-1, 0)

        if max_st_seen > best_steps:
            best_steps = max_st_seen
            best_steps_info = {"q": q_tuple, "max_steps": max_st_seen, "num_loops": len(loops_by_min)}

    return {
        "p": p,
        "d": d,
        "best_cycle": best_cycle_info,
        "best_steps": best_steps_info,
        "longest_lk_list": sorted(set(all_cycles_lk), key=lambda x: x[0] + x[1], reverse=True)[:5],
    }


def main() -> None:
    t0 = time.perf_counter()
    print("[Step 1] Computing continued-fraction super-approximations of ln(p)/ln(p-1) for p = 10..30...")
    cf_rankings: List[Dict[str, Any]] = []
    for p in range(10, 31):
        convs = continued_fraction_convergents(p, max_l=400)
        if convs:
            # Find sharpest convergent with L+K <= 600
            best_conv = min(convs, key=lambda c: c[2])
            cf_rankings.append({
                "p": p,
                "L": best_conv[0],
                "K": best_conv[1],
                "len": best_conv[0] + best_conv[1],
                "rel_gap": best_conv[2],
                "a_next": best_conv[3],
                "all_convs": convs,
            })

    cf_rankings.sort(key=lambda x: x["rel_gap"])
    for r in cf_rankings[:6]:
        print(
            f"  p={r['p']:2d} (d={r['p']-1:2d}): best convergent (L,K)=({r['L']},{r['K']}) len={r['len']} | "
            f"rel_gap={r['rel_gap']:.3e} (next a={r['a_next']})"
        )

    # Pick top 3 super-approximation p values + 1 baseline (largest rel_gap among p=10..20)
    target_ps = [r["p"] for r in cf_rankings[:3]]
    print(f"\n[Step 2] Scanning 120 systems each for top-3 target p = {target_ps}...")
    scan_results = []
    for p_val in target_ps:
        res = scan_p_for_giants(p_val, trials=120, max_n=3000, max_steps=10000, seed=p_val * 100)
        scan_results.append(res)
        bc = res["best_cycle"]
        bs = res["best_steps"]
        print(
            f"  p={p_val:2d}: MAX cycle len={bc.get('length', 0)} (L,K)=({bc.get('L',0)},{bc.get('K',0)}) | "
            f"MAX steps={bs.get('max_steps', 0)} | top5 (L,K)={res['longest_lk_list']}"
        )

    # Write Report
    lines: List[str] = []
    lines.append("# 実験 5 (`p = 10 .. 30`): 連分数の超良近似 $(L, K)$ による巨大サイクル・長大軌道の狙い撃ちレポート\n")
    lines.append("## 1. 連分数展開 $\\ln p / \\ln(p-1)$ による事前予測（`p = 10 .. 30`）\n")
    lines.append("相対誤差 $\\delta = \\lvert d^L - p^K \\rvert / p^K$ が極小になる（＝次の部分商 $a_{\\text{next}}$ が異常に大きい）$p$ ほど、エネルギー収支が中立に近づき、巨大サイクルが出現しやすいと予測しました。\n")
    lines.append("| 順位 | $p$ ($d=p-1$) | 最鋭近似 $(L, K)$ | サイクル長 $L+K$ | 相対誤差 $\\delta = \\lvert d^L - p^K \\rvert / p^K$ | 次の部分商 $a_{\\text{next}}$ |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: |")
    for idx, r in enumerate(cf_rankings[:10], 1):
        lines.append(
            f"| {idx} | **$p={r['p']}$** ($d={r['p']-1}$) | `({r['L']}, {r['K']})` | **{r['len']}** | `{r['rel_gap']:.3e}` | **{r['a_next']}** |"
        )
    lines.append("")

    lines.append("## 2. 上位3つの狙い目 $p$ における巨大サイクル・高ステップ数探索（各 120 試行, `n=1..3000`）\n")
    lines.append("| $p$ ($d$) | 観測された最大サイクル長 $L+K$ | $(L, K)$ | 最小値 $n_{\\min}$ | 最大ステップ数 `max_steps` | 検出された上位 $(L, K)$ パターン |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :--- |")
    for sr in scan_results:
        bc = sr["best_cycle"]
        bs = sr["best_steps"]
        lk_str = ", ".join(f"`({l},{k})`[{l+k}]" for l, k in sr["longest_lk_list"][:4])
        lines.append(
            f"| **$p={sr['p']}$** ($d={sr['d']}$) | **{bc.get('length', 0)}** | `({bc.get('L',0)}, {bc.get('K',0)})` | "
            f"`{bc.get('min_value', 0)}` | **{bs.get('max_steps', 0):,}** | {lk_str} |"
        )
    lines.append("")

    lines.append("## 3. 発見された最大サイクルのシステム詳細\n")
    for sr in scan_results:
        bc = sr["best_cycle"]
        lines.append(f"- **$p = {sr['p']}$ (最大長 {bc.get('length', 0)}, `(L, K) = ({bc.get('L',0)}, {bc.get('K',0)})`, $n_{{\\min}} = {bc.get('min_value', 0)}$)**:")
        lines.append(f"  - `Q = {bc.get('q')}`")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH} in {time.perf_counter()-t0:.2f}s.")


if __name__ == "__main__":
    main()

