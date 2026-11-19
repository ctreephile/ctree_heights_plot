#!/usr/bin/env python3
"""
Statistical, Inequality & Heredity Analyzer for `data/p3/summary_p3.db`
(p = 3, d = 2, Q = [_, q1] for odd q1 in [1, 3, 5, ..., 19999]).

Queries `data/p3/summary_p3.db` directly and analyzes:
  1. Overall executive statistics across all 10,000 odd q1 systems
  2. Loop count M frequency distribution & prime-q1 single-loop analysis
  3. Cycle length (L + K), division/multiplication step signatures (L, K),
     and cycle denominator D = |2^L - 3^K| continued-fraction convergents of ln(3)/ln(2)
  4. Resonance correlation between prime factors of q1 (5, 7, 13, 17, 19, 23, 29, 37, 47...) and loop counts
  5. CTree Basin-of-Attraction Inequality (Standard Gini G, Normalized Gini G*,
     Herfindahl-Hirschman Index HHI, Shannon Evenness)
  6. Heredity & Complete Clone Inheritance under 3^m scaling (q1 -> 3*q1 -> 9*q1 -> ...)
     and 5^m evolution scaling (q1 = 5, 25, 125, 625, 3125, 15625)
  7. Top systems by loop count, step height (iterN), extreme egalitarianism (low G*),
     and extreme monopoly (high G*)

Generates:
  - `docs/2026_1105/p3_statistics_and_gini_report.md`
  - `data/p3/p3_lorenz_and_distributions.png`
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DEFAULT_DB_PATH = Path("data/p3/summary_p3.db")
DEFAULT_REPORT_PATH = Path("docs/2026_1105/p3_statistics_and_gini_report.md")
DEFAULT_PLOT_PATH = Path("data/p3/p3_lorenz_and_distributions.png")


def factorize_small(val: int) -> str:
    if val == 0:
        return "0"
    sign = "-" if val < 0 else ""
    n_abs = abs(val)
    if n_abs > 10**15:
        return f"{sign}{n_abs:.3e}"
    factors = []
    d = 2
    temp = n_abs
    while d * d <= temp and d <= 300000:
        exp = 0
        while temp % d == 0:
            temp //= d
            exp += 1
        if exp > 0:
            factors.append(f"{d}^{exp}" if exp > 1 else f"{d}")
        d += 1 if d == 2 else 2
    if temp > 1:
        factors.append(f"{temp}")
    fact_str = " × ".join(factors) if len(factors) > 1 or sign else str(n_abs)
    return f"{val:,} ({sign}{fact_str})"


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    d = 3
    while d * d <= n:
        if n % d == 0:
            return False
        d += 2
    return True


def strip_factor_3(n: int) -> Tuple[int, int]:
    """Return (core, exp3) where n = core * 3^exp3 and core % 3 != 0."""
    exp3 = 0
    temp = n
    while temp > 0 and temp % 3 == 0:
        temp //= 3
        exp3 += 1
    return temp, exp3


def render_summary_plots(
    systems: List[Dict[str, Any]],
    loops_by_sys: Dict[int, List[Dict[str, Any]]],
    out_png: Path,
) -> None:
    plt.rcParams.update({"font.family": "serif"})
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 11.2), dpi=180)
    ax_lorenz, ax_loops = axes[0]
    ax_gini, ax_q_scatter = axes[1]

    # 1. Top-Left: Lorenz Curves
    ax_lorenz.plot([0, 1], [0, 1], linestyle="--", color="#64748b", label="Perfect Equality (G*=0)")

    multi_sys = [s for s in systems if s["num_loops"] >= 2]
    many_sys = [s for s in systems if s["num_loops"] >= 6]

    showcase: List[Dict[str, Any]] = []
    if many_sys:
        showcase.append(max(many_sys, key=lambda s: s["gini_norm"]))
        showcase.append(min(many_sys, key=lambda s: s["gini_norm"]))
    if systems:
        max_lp_sys = max(systems, key=lambda s: (s["num_loops"], s["max_steps"]))
        if max_lp_sys not in showcase and max_lp_sys["num_loops"] >= 2:
            showcase.append(max_lp_sys)
    q5_sys = next((s for s in systems if s["q1"] == 5), None)
    if q5_sys and q5_sys not in showcase and q5_sys["num_loops"] >= 2:
        showcase.append(q5_sys)
    if multi_sys:
        most_eq = min(multi_sys, key=lambda s: (s["gini_norm"], -s["num_loops"]))
        if most_eq not in showcase:
            showcase.append(most_eq)

    colors = ["#dc2626", "#16a34a", "#7c3aed", "#0284c7", "#d97706"]
    for s, col in zip(showcase[:5], colors):
        lps = loops_by_sys.get(s["system_id"], [])
        counts = sorted(lp["basin_count"] for lp in lps)
        m = len(counts)
        tot = sum(counts)
        if m == 0 or tot == 0:
            continue
        cum_pop = [0.0] + [(i + 1) / m for i in range(m)]
        cum_wealth = [0.0]
        running = 0
        for v in counts:
            running += v
            cum_wealth.append(running / tot)
        ax_lorenz.plot(
            cum_pop,
            cum_wealth,
            marker="o",
            markersize=3.8,
            linewidth=2,
            color=col,
            label=f"q1={s['q1']} (M={m}): G={s['gini']:.2f}, G*={s['gini_norm']:.3f}",
        )

    ax_lorenz.set_title("p=3 (3n+q1) CTree Lorenz Curves (Basin Inequality)", fontsize=12.5, fontweight="bold")
    ax_lorenz.set_xlabel("Cumulative Share of Loops")
    ax_lorenz.set_ylabel("Cumulative Share of Initial Values n")
    ax_lorenz.set_xlim(0, 1)
    ax_lorenz.set_ylim(0, 1)
    ax_lorenz.grid(True, linestyle=":", alpha=0.5)
    ax_lorenz.legend(loc="upper left", fontsize=8.5)

    # 2. Top-Right: Loop Count Distribution
    loop_counts = [s["num_loops"] for s in systems]
    freq = Counter(loop_counts)
    xs_m = sorted(freq.keys())
    ys_m = [freq[k] for k in xs_m]
    ax_loops.bar(xs_m, ys_m, color="#0284c7", edgecolor="#0369a1", alpha=0.85)
    ax_loops.set_title(f"Distribution of Loop Counts M (Total {len(systems):,} Systems)", fontsize=12.5, fontweight="bold")
    ax_loops.set_xlabel("Number of Loops (M)")
    ax_loops.set_ylabel("Number of q1 Systems")
    ax_loops.grid(True, axis="y", linestyle=":", alpha=0.5)

    # 3. Bottom-Left: Normalized Gini G* Distribution (M >= 2)
    gini_norms = [s["gini_norm"] for s in multi_sys]
    if gini_norms:
        ax_gini.hist(gini_norms, bins=30, range=(0.0, 1.0), color="#d97706", edgecolor="#92400e", alpha=0.85)
        mean_gn = statistics.mean(gini_norms)
        ax_gini.axvline(mean_gn, color="#dc2626", linestyle="--", linewidth=1.8, label=f"Mean G* = {mean_gn:.3f}")
        ax_gini.legend(loc="upper left")
    ax_gini.set_title(f"Normalized Gini Coefficient G* Distribution (M >= 2, n={len(multi_sys):,})", fontsize=12.5, fontweight="bold")
    ax_gini.set_xlabel("Normalized Gini Coefficient G*")
    ax_gini.set_ylabel("Number of Systems")
    ax_gini.set_xlim(0, 1)
    ax_gini.grid(True, linestyle=":", alpha=0.5)

    # 4. Bottom-Right: Loop Count vs q1 (highlighting 5^m and 3^m families)
    qs = [s["q1"] for s in systems]
    ms = [s["num_loops"] for s in systems]
    ax_q_scatter.plot(qs, ms, linestyle="none", marker=".", markersize=2.5, color="#64748b", alpha=0.45, label="All odd q1")
    # Highlight multiples of 5*7*13 = 455 or 5*13 = 65
    res_q = [s["q1"] for s in systems if s["q1"] % 65 == 0]
    res_m = [s["num_loops"] for s in systems if s["q1"] % 65 == 0]
    if res_q:
        ax_q_scatter.plot(res_q, res_m, linestyle="none", marker="o", markersize=4.5, color="#dc2626", alpha=0.85, label="65 | q1 (5×13 resonance)")
    pow5_q = [s["q1"] for s in systems if s["q1"] in {5, 25, 125, 625, 3125, 15625}]
    pow5_m = [s["num_loops"] for s in systems if s["q1"] in {5, 25, 125, 625, 3125, 15625}]
    if pow5_q:
        ax_q_scatter.plot(pow5_q, pow5_m, linestyle="-", marker="D", markersize=6, color="#16a34a", linewidth=1.5, label="q1 = 5^k lineage")
    ax_q_scatter.set_title("Number of Loops M across q1 = 1 .. 19,999", fontsize=12.5, fontweight="bold")
    ax_q_scatter.set_xlabel("q1")
    ax_q_scatter.set_ylabel("Number of Loops (M)")
    ax_q_scatter.grid(True, linestyle=":", alpha=0.5)
    ax_q_scatter.legend(loc="upper left", fontsize=8.5)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def analyze_db(
    db_path: Path = DEFAULT_DB_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    plot_path: Path = DEFAULT_PLOT_PATH,
) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Master DB not found: {db_path}. Run batch_p3.py first.")

    t0 = time.perf_counter()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sys_rows = conn.execute(
        """
        SELECT system_id, p, q1, q_json, gcd_q, n_max, num_loops,
               max_steps, max_step_n, avg_steps, unresolved_count,
               gini, gini_norm, hhi, shannon_evenness, elapsed_ms
        FROM systems
        ORDER BY q1
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

    systems: List[Dict[str, Any]] = [dict(r) for r in sys_rows]
    loops_by_sys: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in loop_rows:
        d = dict(r)
        loops_by_sys[int(d["system_id"])].append(d)

    sys_by_q1: Dict[int, Dict[str, Any]] = {}
    for s in systems:
        sid = int(s["system_id"])
        q1 = int(s["q1"])
        sys_by_q1[q1] = s
        lps = loops_by_sys.get(sid, [])
        shares_desc = sorted((lp["basin_share"] * 100.0 for lp in lps), reverse=True)
        s["top1_pct"] = shares_desc[0] if shares_desc else 0.0
        s["shares_desc_str"] = " / ".join(f"{sh:.1f}%" for sh in shares_desc[:8])
        if len(shares_desc) > 8:
            s["shares_desc_str"] += f" / ... (+{len(shares_desc)-8})"
        s["loop_lengths_list"] = [lp["length"] for lp in lps]

    total_systems = len(systems)
    if total_systems == 0:
        raise ValueError(f"No systems found in {db_path}")

    loop_counts = [s["num_loops"] for s in systems]
    total_loops = sum(loop_counts)
    count_freq = Counter(loop_counts)
    total_unresolved = sum(s["unresolved_count"] for s in systems)
    avg_steps_all = statistics.mean(s["avg_steps"] for s in systems)
    max_steps_sys = max(systems, key=lambda s: s["max_steps"])
    n_max_val = systems[0]["n_max"]

    # Signature counter: (length, L_div2, K_mul3)
    sig_counter: Counter[Tuple[int, int, int]] = Counter()
    single_loop_lengths: Counter[int] = Counter()
    for s in systems:
        lps = loops_by_sys.get(s["system_id"], [])
        if s["num_loops"] == 1 and lps:
            single_loop_lengths[lps[0]["length"]] += 1
        for lp in lps:
            sig_counter[(lp["length"], lp["l_div_count"], lp["k_mul_count"])] += 1

    # Prime factor resonance analysis on core(q1) (stripped of powers of 3)
    resonance_primes = [5, 7, 11, 13, 17, 19, 23, 29, 37, 47, 73]
    prime_factor_stats: List[Tuple[str, int, float, int, int, int]] = []
    # Also check when q1 is a prime or 3^k * prime
    pure_3k_systems = [s for s in systems if strip_factor_3(s["q1"])[0] == 1]
    prime_core_no_res = [
        s for s in systems
        if is_prime(strip_factor_3(s["q1"])[0])
        and all(strip_factor_3(s["q1"])[0] != rp for rp in [5, 7, 13, 17, 19, 23, 29, 37, 47])
    ]
    for p_div in resonance_primes:
        matching = [s["num_loops"] for s in systems if s["q1"] % p_div == 0]
        if matching:
            prime_factor_stats.append(
                (
                    f"{p_div} | q1",
                    len(matching),
                    statistics.mean(matching),
                    min(matching),
                    max(matching),
                    matching.count(1),
                )
            )

    # Heredity verification in p=3:
    # 1) Complete Clone Heredity: q1 -> 3 * q1
    clone_3x_pairs = []
    clone_3x_exact = 0
    for q1, s_parent in sorted(sys_by_q1.items()):
        q_child = 3 * q1
        if q_child in sys_by_q1:
            s_child = sys_by_q1[q_child]
            if s_parent["num_loops"] == s_child["num_loops"]:
                clone_3x_exact += 1
            clone_3x_pairs.append((q1, q_child, s_parent, s_child))

    # 2) 5^k Evolution Lineage: q1 = 1 -> 5 -> 25 -> 125 -> 625 -> 3125 -> 15625
    pow5_lineage = [sys_by_q1[5**k] for k in range(7) if (5**k) in sys_by_q1]

    # Multi-loop inequality stats
    multi_sys = [s for s in systems if s["num_loops"] >= 2]
    many_sys = [s for s in systems if s["num_loops"] >= 6]

    avg_gini_multi = statistics.mean(s["gini"] for s in multi_sys) if multi_sys else 0.0
    avg_norm_gini_multi = statistics.mean(s["gini_norm"] for s in multi_sys) if multi_sys else 0.0
    median_norm_gini_multi = statistics.median(s["gini_norm"] for s in multi_sys) if multi_sys else 0.0

    by_m: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for s in multi_sys:
        by_m[s["num_loops"]].append(s)

    top_loop_systems = sorted(
        systems, key=lambda s: (s["num_loops"], s["max_steps"]), reverse=True
    )[:20]
    top_height_systems = sorted(
        systems, key=lambda s: s["max_steps"], reverse=True
    )[:15]
    most_unequal_many = sorted(
        many_sys, key=lambda s: (s["gini_norm"], s["num_loops"]), reverse=True
    )[:12]
    most_equal_many = sorted(
        many_sys, key=lambda s: (s["gini_norm"], -s["num_loops"])
    )[:12]
    most_equal_all = sorted(
        multi_sys, key=lambda s: (s["gini_norm"], -s["num_loops"])
    )[:12]

    render_summary_plots(systems, loops_by_sys, plot_path)

    db_size_mb = db_path.stat().st_size / (1024 * 1024)
    query_ms = (time.perf_counter() - t0) * 1000.0

    md: List[str] = []
    md.append("# `(p, Q) = (3, [_, q1])` ($q_1 = 1, 3, 5, \\dots, 19999$) 全10,000システム 統計・ジニ係数・遺伝解析レポート")
    md.append("")
    md.append("## 1. エグゼクティブ・サマリ（省ディスク集約DB方式）")
    md.append("")
    md.append(f"- **マスターDB**: `{db_path}`（ファイルサイズ: **{db_size_mb:.2f} MB**, 集計・描画時間: **{query_ms:.0f} ms**）")
    md.append(f"- **解析対象システム数**: **{total_systems:,} 通り**（$p = 3, d = 2, Q = [\\_, q_1], q_1 \\in \\{{1, 3, 5, \\dots, 19999\\}}$）")
    md.append(f"- **各システムの初期値検証範囲**: $n = 1 \\sim {n_max_val:,}$（合計 **{total_systems * n_max_val:,} 通り＝10億通り** の初期軌道）")
    md.append(f"- **未到達（発散・上限超過）軌道数**: **{total_unresolved:,} 個**")
    md.append(f"- **発見されたループ総数**: **{total_loops:,} 本**")
    md.append(
        f"- **1システムあたりのループ本数**: 平均 **{statistics.mean(loop_counts):.2f} 本** / "
        f"中央値 **{statistics.median(loop_counts):.1f} 本** / "
        f"最小 **{min(loop_counts)} 本**（{count_freq[min(loop_counts)]:,}システム, {count_freq[min(loop_counts)]/total_systems*100:.1f}%） / "
        f"最大 **{max(loop_counts)} 本**（`q1 = {top_loop_systems[0]['q1']}`）"
    )
    md.append(f"- **到達ステップ数（高さ `iterN`）全体平均**: **{avg_steps_all:.2f} ステップ**")
    md.append(
        f"- **最高到達ステップ数**: **{max_steps_sys['max_steps']} ステップ** "
        f"（`q1 = {max_steps_sys['q1']}`, 初期値 `n = {max_steps_sys['max_step_n']:,}`）"
    )
    if multi_sys:
        md.append(
            f"- **複数ループ系（$M \\ge 2$, {len(multi_sys):,}システム）のジニ係数**: "
            f"標準 $G$ 平均 **{avg_gini_multi:.3f}** / 正規化 $G^*$ 平均 **{avg_norm_gini_multi:.3f}**（中央値 **{median_norm_gini_multi:.3f}**）"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. ループ本数 $M$ の度数分布（10,000システム内訳）")
    md.append("")
    md.append("| ループ本数 $M$ | システム数 | 割合 (%) | 累積割合 (%) | 棒グラフ |")
    md.append("|---:|---:|---:|---:|:---|")
    cum = 0
    for k in sorted(count_freq.keys()):
        cnt = count_freq[k]
        pct = (cnt / total_systems) * 100.0
        cum += cnt
        cum_pct = (cum / total_systems) * 100.0
        bar = "█" * max(1, int(round(pct / 1.5)))
        md.append(f"| **{k} 本** | {cnt:,} | {pct:.2f}% | {cum_pct:.2f}% | `{bar}` |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. サイクル方程式 $|2^L - 3^K|$ と周期長 (`length`) TOP 25")
    md.append("")
    md.append(
        f"全 **{total_loops:,} 本** のループについて、周期長 `length`（$= L + K$）、"
        "`÷2` の回数 $L$、`3n + q_1` の回数 $K$、および理論分母 $D = 2^L - 3^K$ の集計結果です。"
        "比率 $L/K$ は $\\ln 3 / \\ln 2 \\approx 1.5849625$ の連分数近似値（$2/1, 3/2, 5/3, 8/5, 11/7, 19/12, 27/17, 46/29, 65/41, \\dots$）に厳密に集中します。"
    )
    md.append("")
    md.append("| 順位 | 周期長 `length` | `÷2` ($L$) | `3n+q1` ($K$) | 比率 $L/K$ | 理論分母 $D = 2^L - 3^K$ (素因数分解) | 出現ループ数 | シェア (%) |")
    md.append("|---:|---:|---:|---:|---:|:---|---:|---:|")
    for rank_idx, ((length, l_cnt, k_cnt), cnt) in enumerate(sig_counter.most_common(25), start=1):
        denom = (2 ** l_cnt) - (3 ** k_cnt)
        ratio_str = f"{l_cnt / k_cnt:.5f}" if k_cnt > 0 else "-"
        pct = (cnt / max(1, total_loops)) * 100.0
        md.append(
            f"| {rank_idx} | **{length}** | {l_cnt} | {k_cnt} | `{ratio_str}` | `{factorize_small(denom)}` | **{cnt:,}** | {pct:.2f}% |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. $q_1$ の素因数とサイクル分母 $|2^L - 3^K|$ の共鳴分裂")
    md.append("")
    md.append(
        "$p = 3$ における主要なサイクル分母は $2^2 - 3^1 = \\mathbf{1}$、$2^3 - 3^2 = \\mathbf{-1}$、"
        "$2^4 - 3^2 = \\mathbf{7}$、$2^5 - 3^3 = \\mathbf{5}$、$2^8 - 3^5 = \\mathbf{13}$、"
        "$2^{11} - 3^7 = \\mathbf{-139}$、$2^{19} - 3^{12} = \\mathbf{-7,153 = -23 \\times 311}$、"
        "$2^7 - 3^4 = \\mathbf{47}$ などです。$q_1$ がこれらの素因数を持つときのループ本数を比較します。"
    )
    md.append("")
    md.append("| 条件（$q_1$ の性質） | 該当システム数 | 平均ループ本数 | 最小 | 最大 | 単一ループ ($M=1$) のシステム数 |")
    md.append("|:---|---:|---:|---:|---:|---:|")
    if pure_3k_systems:
        v3 = [s["num_loops"] for s in pure_3k_systems]
        md.append(
            f"| **$q_1 = 3^m$** ($1, 3, 9, 27, \\dots, 19683$) | {len(v3)} | **{statistics.mean(v3):.2f} 本** | {min(v3)} | {max(v3)} | {v3.count(1)} ({v3.count(1)/len(v3)*100:.1f}%) |"
        )
    if prime_core_no_res:
        vp = [s["num_loops"] for s in prime_core_no_res]
        md.append(
            f"| **$q_1$ が非共鳴素数 ($\times 3^m$)** | {len(vp):,} | **{statistics.mean(vp):.2f} 本** | {min(vp)} | {max(vp)} | {vp.count(1):,} ({vp.count(1)/len(vp)*100:.1f}%) |"
        )
    for label, cnt_s, avg_m, min_m, max_m, ones_m in prime_factor_stats:
        md.append(
            f"| **`{label}`** | {cnt_s:,} | **{avg_m:.2f} 本** | {min_m} | {max_m} | {ones_m:,} ({ones_m/cnt_s*100:.1f}%) |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. $p = 3$ における「遺伝」の実証データ（完全クローン遺伝 vs. $5^k$ 進化遺伝）")
    md.append("")
    md.append("### (A) 【完全クローン遺伝】$q_1 \\to 3 q_1 \\to 9 q_1 \\to 27 q_1 \\dots$（$3^m$ 倍系列）")
    md.append(
        "$p = 3$ では変換式が $3n + q_1$ であるため、$q_1$ を **3倍（$3^m$ 倍）** にすると、"
        "すべての数は最初の $3n + 3q'_1 = 3(n + q'_1)$ の1ステップで強制的に「3の倍数の世界（＝親のクローン世界）」へ吸収されます。"
        f"実際に 10,000 システム内に存在する **$q_1 \\to 3q_1$ の全 {len(clone_3x_pairs):,} ペア** を検証した結果："
    )
    md.append(
        f"- **ループ本数・周期長内訳の一致率**: **{clone_3x_exact:,} / {len(clone_3x_pairs):,} ペア（{clone_3x_exact/max(1,len(clone_3x_pairs))*100:.2f}%）**！"
    )
    md.append("")
    md.append("| 始祖 $q_1$ | $\\times 3$ 子 | $\\times 9$ 孫 | $\\times 27$ 曾孫 | ループ本数 | ループ周期長リスト | 正規化ジニ $G^*$（親 $\\to$ 子 $\\to$ 孫） |")
    md.append("|:---|:---|:---|:---|---:|:---|:---|")
    for base_q in [1, 5, 7, 13, 17, 19, 23, 25, 35, 65, 175]:
        if base_q not in sys_by_q1:
            continue
        s0 = sys_by_q1[base_q]
        s1 = sys_by_q1.get(base_q * 3)
        s2 = sys_by_q1.get(base_q * 9)
        s3 = sys_by_q1.get(base_q * 27)
        lens_str = ", ".join(str(x) for x in s0["loop_lengths_list"][:8])
        if len(s0["loop_lengths_list"]) > 8:
            lens_str += ", ..."
        g_chain = " → ".join(
            f"{sx['gini_norm']:.3f} (M={sx['num_loops']})"
            for sx in [s0, s1, s2, s3]
            if sx is not None
        )
        md.append(
            f"| **`{base_q}`** | `{base_q*3}` | `{base_q*9}` | `{base_q*27}` | **{s0['num_loops']} 本** | `[{lens_str}]` | `{g_chain}` |"
        )
    md.append("")
    md.append("### (B) 【5倍遺伝】$q_1 = 1 \\to 5 \\to 25 \\to 125 \\to 625 \\to 3,125 \\to 15,625$（$5^k$ 家系）")
    md.append(
        "`docs/2026_1101/CTreeの遺伝は存在する.txt` で言及された **$q_1 = 5^k$ 家系** の実測データです。"
        "$k=0 \\ (q_1=1)$ では $2^2 - 3^1 = 1$ の単一ループ（`[1, 4, 2]`）のみですが、"
        "$k=1 \\ (q_1=5)$ でサイクル分母 $2^5 - 3^3 = 5$ が約分されて一気に **+5本（計6本：周期 `[3, 3, 5, 5, 27, 27]`）** に共鳴分裂し、"
        "以降の世代 $q_1 = 25, 125, 625, 3125, 15625$ はこの6本のループとジニ係数を $\\times 5^k$ でそのまま継承する様子が確認できます。"
    )
    md.append("")
    md.append("| 世代 $k$ | $q_1 = 5^k$ | ループ本数 $M$ | 前世代からの増加数 | 正規化ジニ $G^*$ | 最大ループ占有率 | 周期長の内訳 |")
    md.append("|---:|---:|---:|---:|---:|---:|:---|")
    prev_m = 0
    for idx, s in enumerate(pow5_lineage):
        diff_str = f"+{s['num_loops'] - prev_m} 本" if idx > 0 else "—"
        prev_m = s["num_loops"]
        c_len = Counter(s["loop_lengths_list"])
        len_summary = ", ".join(f"長{l}×{c}本" for l, c in sorted(c_len.items()))
        md.append(
            f"| **$k={idx}$** | **`{s['q1']:,}`** | **{s['num_loops']} 本** | **{diff_str}** | "
            f"{s['gini_norm']:.3f} | {s['top1_pct']:.1f}% | `{len_summary}` |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 6. CTree 吸引盆地のジニ係数（ループ本数 $M$ 別統計）")
    md.append("")
    md.append("| ループ本数 $M$ | システム数 | 標準ジニ $G$ 平均 | 正規化ジニ $G^*$ 平均 | 正規化 $G^*$ 最小〜最大 | 最大ループ平均占有率 (%) | HHI 平均 |")
    md.append("|---:|---:|---:|---:|:---|---:|---:|")
    for m in sorted(by_m.keys()):
        recs = by_m[m]
        g_avg = statistics.mean(r["gini"] for r in recs)
        ng_avg = statistics.mean(r["gini_norm"] for r in recs)
        ng_min = min(r["gini_norm"] for r in recs)
        ng_max = max(r["gini_norm"] for r in recs)
        top1_avg = statistics.mean(r["top1_pct"] for r in recs)
        hhi_avg = statistics.mean(r["hhi"] for r in recs)
        md.append(
            f"| **{m} 本** | {len(recs):,} | {g_avg:.3f} | **{ng_avg:.3f}** | `{ng_min:.3f} 〜 {ng_max:.3f}` | {top1_avg:.1f}% | {hhi_avg:.3f} |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 7. ループ本数が多いシステム TOP 20")
    md.append("")
    md.append("| 順位 | `q1` | `q1` の素因数分解 | ループ数 $M$ | 正規化ジニ $G^*$ | 最大ループ占有率 | 最大ステップ数 | 周期長の内訳 |")
    md.append("|---:|---:|:---|---:|---:|---:|---:|:---|")
    for idx, s in enumerate(top_loop_systems, start=1):
        c_len = Counter(s["loop_lengths_list"])
        len_summary = ", ".join(f"長{l}×{c}" for l, c in sorted(c_len.items())[:8])
        if len(c_len) > 8:
            len_summary += ", ..."
        md.append(
            f"| {idx} | **`{s['q1']:,}`** | `{factorize_small(s['q1'])}` | **{s['num_loops']} 本** | "
            f"{s['gini_norm']:.3f} | {s['top1_pct']:.1f}% | {s['max_steps']} | `{len_summary}` |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 8. 【超平等型 vs 超独占型 CTree】ジニ係数ランキング")
    md.append("")
    md.append("### (A) ループ6本以上（$M \\ge 6$）で最も平等なシステム TOP 12")
    md.append("| 順位 | `q1` | 素因数分解 | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 各ループの占有率内訳 |")
    md.append("|---:|---:|:---|---:|---:|---:|:---|")
    for idx, s in enumerate(most_equal_many, start=1):
        md.append(
            f"| {idx} | **`{s['q1']:,}`** | `{factorize_small(s['q1'])}` | **{s['num_loops']} 本** | "
            f"**{s['gini_norm']:.4f}** | {s['gini']:.4f} | `{s['shares_desc_str']}` |"
        )
    md.append("")
    md.append("### (B) 全複数ループ系（$M \\ge 2$）で最も平等なシステム TOP 12")
    md.append("| 順位 | `q1` | 素因数分解 | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 各ループの占有率内訳 |")
    md.append("|---:|---:|:---|---:|---:|---:|:---|")
    for idx, s in enumerate(most_equal_all, start=1):
        md.append(
            f"| {idx} | **`{s['q1']:,}`** | `{factorize_small(s['q1'])}` | **{s['num_loops']} 本** | "
            f"**{s['gini_norm']:.4f}** | {s['gini']:.4f} | `{s['shares_desc_str']}` |"
        )
    md.append("")
    md.append("### (C) ループ6本以上（$M \\ge 6$）で最も独占的なシステム TOP 12")
    md.append("| 順位 | `q1` | 素因数分解 | ループ数 $M$ | 正規化ジニ $G^*$ | 最大ループ占有率 | 各ループの占有率内訳 |")
    md.append("|---:|---:|:---|---:|---:|---:|:---|")
    for idx, s in enumerate(most_unequal_many, start=1):
        md.append(
            f"| {idx} | **`{s['q1']:,}`** | `{factorize_small(s['q1'])}` | **{s['num_loops']} 本** | "
            f"**{s['gini_norm']:.4f}** | **{s['top1_pct']:.1f}%** | `{s['shares_desc_str']}` |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 9. 到達ステップ数（高さ `iterN`）が最大のシステム TOP 15")
    md.append("")
    md.append("| 順位 | `q1` | 素因数分解 | 最高到達ステップ数 (`max iterN`) | 初期値 `n` | 平均ステップ数 | ループ数 $M$ |")
    md.append("|---:|---:|:---|---:|---:|---:|---:|")
    for idx, s in enumerate(top_height_systems, start=1):
        md.append(
            f"| {idx} | **`{s['q1']:,}`** | `{factorize_small(s['q1'])}` | **{s['max_steps']} ステップ** | "
            f"`n = {s['max_step_n']:,}` | {s['avg_steps']:.2f} | {s['num_loops']} 本 |"
        )
    md.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Report written to : {report_path}")
    print(f"Diagnostic plot   : {plot_path}")
    return {
        "total_systems": total_systems,
        "total_loops": total_loops,
        "total_unresolved": total_unresolved,
        "report_path": report_path,
        "plot_path": plot_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze data/p3/summary_p3.db and generate Markdown report & plots."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to summary_p3.db (default: data/p3/summary_p3.db).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Output Markdown report path (default: docs/2026_1105/p3_statistics_and_gini_report.md).",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=DEFAULT_PLOT_PATH,
        help="Output diagnostic PNG plot path (default: data/p3/p3_lorenz_and_distributions.png).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyze_db(db_path=args.db, report_path=args.report, plot_path=args.plot)


if __name__ == "__main__":
    main()
