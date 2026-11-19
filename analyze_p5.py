#!/usr/bin/env python3
"""
Statistical & Inequality Analyzer for `data/p5/summary_p5.db` (p = 5, d = 4, Q = [_, q1, q2, q3]).

Queries the master aggregated SQLite DB `data/p5/summary_p5.db` directly in < 0.1s,
analyzes:
  1. Overall executive statistics across all evaluated (q1, q2, q3) systems
  2. Loop count frequency distribution
  3. Cycle length (L + K), division/multiplication step signatures (L, K),
     and cycle denominator D = |4^L - 5^K| continued-fraction convergents of ln(5)/ln(4)
  4. GCD(q1, q2, q3) resonance correlation with loop splitting
  5. CTree Basin-of-Attraction Inequality (Standard Gini G, Normalized Gini G*,
     Herfindahl-Hirschman Index HHI, Shannon Evenness)
  6. Top systems by loop count, step height (iterN), extreme monopoly (high G*),
     and extreme egalitarianism (low G*)
  7. Marginal averages along q1, q2, and q3 axes

Generates:
  - `docs/2026_1104/p5_statistics_and_gini_report.md`
  - `data/p5/p5_lorenz_and_distributions.png`
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

DEFAULT_DB_PATH = Path("data/p5/summary_p5.db")
DEFAULT_REPORT_PATH = Path("docs/2026_1104/p5_statistics_and_gini_report.md")
DEFAULT_PLOT_PATH = Path("data/p5/p5_lorenz_and_distributions.png")


def factorize_small(val: int) -> str:
    if val == 0:
        return "0"
    sign = "-" if val < 0 else ""
    n_abs = abs(val)
    if n_abs > 10**14:
        return f"{sign}{n_abs:.3e}"
    factors = []
    d = 2
    temp = n_abs
    while d * d <= temp and d <= 200000:
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


def render_summary_plots(
    systems: List[Dict[str, Any]],
    loops_by_sys: Dict[int, List[Dict[str, Any]]],
    out_png: Path,
) -> None:
    """
    Create a 2x2 diagnostic figure:
      - Top-Left: Lorenz curves of showcase p=5 CTree systems (egalitarian vs monopoly vs max loops)
      - Top-Right: Distribution of Loop Counts M across all systems
      - Bottom-Left: Histogram of Normalized Gini Coefficient G* (for M >= 2)
      - Bottom-Right: Average Loop Count by gcd(q1, q2, q3)
    """
    plt.rcParams.update({"font.family": "serif"})
    fig, axes = plt.subplots(2, 2, figsize=(15, 11), dpi=180)
    ax_lorenz, ax_loops = axes[0]
    ax_gini, ax_gcd = axes[1]

    # 1. Top-Left: Lorenz Curves
    ax_lorenz.plot([0, 1], [0, 1], linestyle="--", color="#64748b", label="Perfect Equality (G*=0)")

    multi_sys = [s for s in systems if s["num_loops"] >= 2]
    many_sys = [s for s in systems if s["num_loops"] >= 5]

    showcase: List[Dict[str, Any]] = []
    if many_sys:
        showcase.append(max(many_sys, key=lambda s: s["gini_norm"]))
        showcase.append(min(many_sys, key=lambda s: s["gini_norm"]))
    if systems:
        max_lp_sys = max(systems, key=lambda s: (s["num_loops"], s["max_steps"]))
        if max_lp_sys not in showcase and max_lp_sys["num_loops"] >= 2:
            showcase.append(max_lp_sys)
    if multi_sys:
        most_eq = min(multi_sys, key=lambda s: (s["gini_norm"], -s["num_loops"]))
        if most_eq not in showcase:
            showcase.append(most_eq)
        most_uneq = max(multi_sys, key=lambda s: (s["gini_norm"], s["num_loops"]))
        if most_uneq not in showcase:
            showcase.append(most_uneq)

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
            markersize=4,
            linewidth=2,
            color=col,
            label=f"({s['q1']},{s['q2']},{s['q3']}) M={m}: G={s['gini']:.2f}, G*={s['gini_norm']:.3f}",
        )

    ax_lorenz.set_title("p=5 CTree Lorenz Curves (Basin Inequality)", fontsize=12.5, fontweight="bold")
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
    ax_loops.set_ylabel("Number of (q1, q2, q3) Systems")
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

    # 4. Bottom-Right: Average Loop Count by gcd(q1, q2, q3)
    gcd_groups: Dict[int, List[int]] = defaultdict(list)
    for s in systems:
        gcd_groups[s["gcd_q"]].append(s["num_loops"])
    gcds_sorted = sorted(gcd_groups.keys())[:18]
    gcd_labels = [str(g) for g in gcds_sorted]
    gcd_means = [statistics.mean(gcd_groups[g]) for g in gcds_sorted]
    ax_gcd.bar(gcd_labels, gcd_means, color="#7c3aed", edgecolor="#5b21b6", alpha=0.85)
    ax_gcd.set_title("Mean Loop Count by gcd(q1, q2, q3) Resonance", fontsize=12.5, fontweight="bold")
    ax_gcd.set_xlabel("gcd(q1, q2, q3)")
    ax_gcd.set_ylabel("Mean Number of Loops")
    ax_gcd.grid(True, axis="y", linestyle=":", alpha=0.5)

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
        raise FileNotFoundError(f"Master DB not found: {db_path}. Run batch_p5.py first.")

    t0 = time.perf_counter()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sys_rows = conn.execute(
        """
        SELECT system_id, p, q1, q2, q3, q_json, gcd_q, n_max, num_loops,
               max_steps, max_step_n, avg_steps, unresolved_count,
               gini, gini_norm, hhi, shannon_evenness, elapsed_ms
        FROM systems
        ORDER BY q1, q2, q3
        """
    ).fetchall()

    loop_rows = conn.execute(
        """
        SELECT system_id, loop_id, min_value, max_value, length,
               l_div_count, k_mul_count, k1_count, k2_count, k3_count,
               basin_count, basin_share, elements_json
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

    for s in systems:
        sid = int(s["system_id"])
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

    # Signature counter: (length, L_div4, K_mul5)
    sig_counter: Counter[Tuple[int, int, int]] = Counter()
    single_loop_lengths: Counter[int] = Counter()
    for s in systems:
        lps = loops_by_sys.get(s["system_id"], [])
        if s["num_loops"] == 1 and lps:
            single_loop_lengths[lps[0]["length"]] += 1
        for lp in lps:
            sig_counter[(lp["length"], lp["l_div_count"], lp["k_mul_count"])] += 1

    # GCD groups
    gcd_groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for s in systems:
        gcd_groups[s["gcd_q"]].append(s)

    # Multi-loop inequality stats
    multi_sys = [s for s in systems if s["num_loops"] >= 2]
    many_sys = [s for s in systems if s["num_loops"] >= 5]

    avg_gini_multi = statistics.mean(s["gini"] for s in multi_sys) if multi_sys else 0.0
    avg_norm_gini_multi = statistics.mean(s["gini_norm"] for s in multi_sys) if multi_sys else 0.0
    median_norm_gini_multi = statistics.median(s["gini_norm"] for s in multi_sys) if multi_sys else 0.0

    by_m: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for s in multi_sys:
        by_m[s["num_loops"]].append(s)

    top_loop_systems = sorted(
        systems, key=lambda s: (s["num_loops"], s["max_steps"]), reverse=True
    )[:15]
    top_height_systems = sorted(
        systems, key=lambda s: s["max_steps"], reverse=True
    )[:12]
    most_unequal_many = sorted(
        many_sys, key=lambda s: (s["gini_norm"], s["num_loops"]), reverse=True
    )[:12]
    most_equal_many = sorted(
        many_sys, key=lambda s: (s["gini_norm"], -s["num_loops"])
    )[:12]
    most_equal_all = sorted(
        multi_sys, key=lambda s: (s["gini_norm"], -s["num_loops"])
    )[:12]

    # Render diagnostic plot
    render_summary_plots(systems, loops_by_sys, plot_path)

    # Build Markdown report
    db_size_mb = db_path.stat().st_size / (1024 * 1024)
    query_ms = (time.perf_counter() - t0) * 1000.0

    md: List[str] = []
    md.append("# `(p, Q) = (5, [_, q1, q2, q3])` マスターDB (`summary_p5.db`) 統計・ジニ係数解析レポート")
    md.append("")
    md.append("## 1. エグゼクティブ・サマリ（省ディスク集約DB方式）")
    md.append("")
    md.append(f"- **マスターDB**: `{db_path}`（ファイルサイズ: **{db_size_mb:.2f} MB**, 集計・描画時間: **{query_ms:.0f} ms**）")
    md.append(f"- **解析対象システム数**: **{total_systems:,} 通り**（$p = 5, d = 4, Q = [\\_, q_1, q_2, q_3]$）")
    md.append(f"- **各システムの初期値検証範囲**: $n = 1 \\sim {n_max_val:,}$（合計 **{total_systems * n_max_val:,} 通り** の初期軌道）")
    md.append(f"- **未到達（発散・上限超過）軌道数**: **{total_unresolved:,} 個**")
    md.append(f"- **発見されたループ総数**: **{total_loops:,} 本**")
    md.append(
        f"- **1システムあたりのループ本数**: 平均 **{statistics.mean(loop_counts):.2f} 本** / "
        f"中央値 **{statistics.median(loop_counts):.1f} 本** / "
        f"最小 **{min(loop_counts)} 本**（{count_freq[min(loop_counts)]:,}システム） / "
        f"最大 **{max(loop_counts)} 本**（`Q = [_, {top_loop_systems[0]['q1']}, {top_loop_systems[0]['q2']}, {top_loop_systems[0]['q3']}]`）"
    )
    md.append(f"- **到達ステップ数（高さ `iterN`）全体平均**: **{avg_steps_all:.2f} ステップ**")
    md.append(
        f"- **最高到達ステップ数**: **{max_steps_sys['max_steps']} ステップ** "
        f"（`Q = [_, {max_steps_sys['q1']}, {max_steps_sys['q2']}, {max_steps_sys['q3']}]`, 初期値 `n = {max_steps_sys['max_step_n']:,}`）"
    )
    if multi_sys:
        md.append(
            f"- **複数ループ系（$M \\ge 2$, {len(multi_sys):,}システム）のジニ係数**: "
            f"標準 $G$ 平均 **{avg_gini_multi:.3f}** / 正規化 $G^*$ 平均 **{avg_norm_gini_multi:.3f}**（中央値 **{median_norm_gini_multi:.3f}**）"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. ループ本数 $M$ の度数分布")
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
    md.append("## 3. サイクル方程式 $|4^L - 5^K|$ と周期長 (`length`) TOP 20")
    md.append("")
    md.append(
        f"全 **{total_loops:,} 本** のループについて、周期長 `length`（$= L + K$）、"
        "`÷4` の回数 $L$、`5n + q_r` の回数 $K$、および理論分母 $D = 4^L - 5^K$ の集計結果です。"
        "比率 $L/K$ は $\\ln 5 / \\ln 4 \\approx 1.160964$ の連分数近似値に集中します。"
    )
    md.append("")
    md.append("| 順位 | 周期長 `length` | `÷4` ($L$) | `5n+q` ($K$) | 比率 $L/K$ | 理論分母 $D = 4^L - 5^K$ (素因数分解) | 出現ループ数 | シェア (%) |")
    md.append("|---:|---:|---:|---:|---:|:---|---:|---:|")
    for rank_idx, ((length, l_cnt, k_cnt), cnt) in enumerate(sig_counter.most_common(20), start=1):
        denom = (4 ** l_cnt) - (5 ** k_cnt)
        ratio_str = f"{l_cnt / k_cnt:.5f}" if k_cnt > 0 else "-"
        pct = (cnt / max(1, total_loops)) * 100.0
        md.append(
            f"| {rank_idx} | **{length}** | {l_cnt} | {k_cnt} | `{ratio_str}` | `{factorize_small(denom)}` | **{cnt:,}** | {pct:.2f}% |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. $\\gcd(q_1, q_2, q_3)$ とループ共鳴分裂の相関")
    md.append("")
    md.append("| $\\gcd(q_1, q_2, q_3)$ | 素因数分解 | システム数 | 平均ループ本数 | 最小 | 最大 | 単一ループ ($M=1$) の割合 |")
    md.append("|---:|:---|---:|---:|---:|---:|---:|")
    for g in sorted(gcd_groups.keys()):
        grp = gcd_groups[g]
        vals = [s["num_loops"] for s in grp]
        ones = vals.count(1)
        md.append(
            f"| **{g}** | `{factorize_small(g)}` | {len(vals):,} | **{statistics.mean(vals):.2f} 本** | "
            f"{min(vals)} | {max(vals)} | {ones:,} ({ones/len(vals)*100:.1f}%) |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. CTree 吸引盆地のジニ係数（ループ本数 $M$ 別統計）")
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
    md.append("## 6. ループ本数が多いシステム TOP 15")
    md.append("")
    md.append("| 順位 | `(q1, q2, q3)` | $\\gcd$ | ループ数 $M$ | 正規化ジニ $G^*$ | 最大ループ占有率 | 最大ステップ数 | 周期長一覧 |")
    md.append("|---:|:---|---:|---:|---:|---:|---:|:---|")
    for idx, s in enumerate(top_loop_systems, start=1):
        lens = ", ".join(str(x) for x in s["loop_lengths_list"][:12])
        if len(s["loop_lengths_list"]) > 12:
            lens += ", ..."
        md.append(
            f"| {idx} | **`({s['q1']}, {s['q2']}, {s['q3']})`** | {s['gcd_q']} | **{s['num_loops']} 本** | "
            f"{s['gini_norm']:.3f} | {s['top1_pct']:.1f}% | {s['max_steps']} | `[{lens}]` |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 7. 【超平等型 vs 超独占型 CTree】ジニ係数ランキング")
    md.append("")
    md.append("### (A) ループ5本以上（$M \\ge 5$）で最も平等なシステム TOP 12")
    md.append("| 順位 | `(q1, q2, q3)` | $\\gcd$ | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 各ループの占有率内訳 |")
    md.append("|---:|:---|---:|---:|---:|---:|:---|")
    for idx, s in enumerate(most_equal_many, start=1):
        md.append(
            f"| {idx} | **`({s['q1']}, {s['q2']}, {s['q3']})`** | {s['gcd_q']} | **{s['num_loops']} 本** | "
            f"**{s['gini_norm']:.4f}** | {s['gini']:.4f} | `{s['shares_desc_str']}` |"
        )
    md.append("")
    md.append("### (B) 全複数ループ系（$M \\ge 2$）で最も平等なシステム TOP 12")
    md.append("| 順位 | `(q1, q2, q3)` | $\\gcd$ | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 各ループの占有率内訳 |")
    md.append("|---:|:---|---:|---:|---:|---:|:---|")
    for idx, s in enumerate(most_equal_all, start=1):
        md.append(
            f"| {idx} | **`({s['q1']}, {s['q2']}, {s['q3']})`** | {s['gcd_q']} | **{s['num_loops']} 本** | "
            f"**{s['gini_norm']:.4f}** | {s['gini']:.4f} | `{s['shares_desc_str']}` |"
        )
    md.append("")
    md.append("### (C) ループ5本以上（$M \\ge 5$）で最も独占的なシステム TOP 12")
    md.append("| 順位 | `(q1, q2, q3)` | $\\gcd$ | ループ数 $M$ | 正規化ジニ $G^*$ | 最大ループ占有率 | 各ループの占有率内訳 |")
    md.append("|---:|:---|---:|---:|---:|---:|:---|")
    for idx, s in enumerate(most_unequal_many, start=1):
        md.append(
            f"| {idx} | **`({s['q1']}, {s['q2']}, {s['q3']})`** | {s['gcd_q']} | **{s['num_loops']} 本** | "
            f"**{s['gini_norm']:.4f}** | **{s['top1_pct']:.1f}%** | `{s['shares_desc_str']}` |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 8. 到達ステップ数（高さ `iterN`）が最大のシステム TOP 12")
    md.append("")
    md.append("| 順位 | `(q1, q2, q3)` | 最高到達ステップ数 (`max iterN`) | 初期値 `n` | 平均ステップ数 | ループ数 $M$ |")
    md.append("|---:|:---|---:|---:|---:|---:|")
    for idx, s in enumerate(top_height_systems, start=1):
        md.append(
            f"| {idx} | **`({s['q1']}, {s['q2']}, {s['q3']})`** | **{s['max_steps']} ステップ** | "
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
        description="Analyze data/p5/summary_p5.db and generate Markdown report & plots."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to summary_p5.db (default: data/p5/summary_p5.db).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Output Markdown report path (default: docs/2026_1104/p5_statistics_and_gini_report.md).",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=DEFAULT_PLOT_PATH,
        help="Output diagnostic PNG plot path (default: data/p5/p5_lorenz_and_distributions.png).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyze_db(db_path=args.db, report_path=args.report, plot_path=args.plot)


if __name__ == "__main__":
    main()

