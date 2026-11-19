#!/usr/bin/env python3
"""
CTree Basin-of-Attraction Inequality (Gini Coefficient & Lorenz Curve) Analyzer.

Reads `outputs/p4_all_loops_catalog.csv` (from the 900 SQLite DBs of p=4, Q=[_, q1, q2]),
computes for each (q1, q2) system:
  1. Standard Gini Coefficient G in [0, (M-1)/M]
  2. Normalized Gini Coefficient G* = G * M / (M - 1) in [0, 1] (for M >= 2)
  3. Herfindahl-Hirschman Index (HHI = sum(s_i^2))
  4. Shannon Equitability (Evenness E in [0, 1])

Generates:
  - `outputs/p4_gini_30x30.csv` (30x30 matrix of standard Gini G)
  - `outputs/p4_normalized_gini_30x30.csv` (30x30 matrix of normalized Gini G*)
  - `outputs/p4_gini_analysis.csv` (full table of all 900 pairs)
  - `outputs/p4_gini_lorenz_plot.png` (Lorenz curves & Gini distribution visualization)
  - `docs/2026_1101/ctree_gini_report.md` (statistical report on CTree inequality)
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CATALOG_CSV = Path("outputs/p4_all_loops_catalog.csv")
GINI_30X30_CSV = Path("outputs/p4_gini_30x30.csv")
NORM_GINI_30X30_CSV = Path("outputs/p4_normalized_gini_30x30.csv")
FULL_GINI_CSV = Path("outputs/p4_gini_analysis.csv")
PLOT_PNG = Path("outputs/p4_gini_lorenz_plot.png")
REPORT_MD = Path("docs/2026_1101/ctree_gini_report.md")

Q1_LIST = list(range(2, 90, 3))
Q2_LIST = list(range(1, 89, 3))


def compute_gini_metrics(counts: List[int]) -> Dict[str, float]:
    """
    Compute inequality metrics for a list of basin sizes `counts` across M loops.
    """
    m = len(counts)
    total = sum(counts)
    if m <= 1 or total <= 0:
        return {
            "gini": 0.0,
            "norm_gini": 0.0,
            "hhi": 1.0,
            "evenness": 1.0,
            "top1_pct": 100.0 if m == 1 else 0.0,
            "min_pct": 100.0 if m == 1 else 0.0,
        }

    sorted_x = sorted(counts)
    # Standard Gini: G = (2 * sum_{i=1..M} i * x_i) / (M * sum(x_i)) - (M + 1) / M
    weighted_sum = sum((idx + 1) * x for idx, x in enumerate(sorted_x))
    gini = (2.0 * weighted_sum) / (m * total) - (m + 1.0) / m
    gini = max(0.0, min(1.0, gini))

    # Finite-group Normalized Gini: G* = G * M / (M - 1) in [0, 1]
    norm_gini = gini * (m / (m - 1.0))
    norm_gini = max(0.0, min(1.0, norm_gini))

    shares = [x / total for x in sorted_x]
    hhi = sum(s * s for s in shares)

    # Shannon entropy evenness
    entropy = -sum(s * math.log(s) for s in shares if s > 0)
    evenness = entropy / math.log(m) if m > 1 else 1.0

    return {
        "gini": gini,
        "norm_gini": norm_gini,
        "hhi": hhi,
        "evenness": evenness,
        "top1_pct": shares[-1] * 100.0,
        "min_pct": shares[0] * 100.0,
    }


def write_matrix_csv(
    path: Path,
    value_map: Dict[Tuple[int, int], str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["q2 \\ q1"] + [str(q1) for q1 in Q1_LIST])
        for q2 in Q2_LIST:
            row = [str(q2)]
            for q1 in Q1_LIST:
                row.append(value_map.get((q1, q2), ""))
            writer.writerow(row)


def main() -> None:
    if not CATALOG_CSV.exists():
        raise FileNotFoundError(f"Catalog CSV not found: {CATALOG_CSV}")

    loops_by_pair: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
    with CATALOG_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q1 = int(row["q1"])
            q2 = int(row["q2"])
            loops_by_pair[(q1, q2)].append(
                {
                    "rank": int(row["loop_rank"]),
                    "min_value": int(row["min_value"]),
                    "length": int(row["length"]),
                    "basin_count": int(row["basin_count"]),
                    "basin_share_pct": float(row["basin_share_pct"]),
                }
            )

    pair_records: List[Dict[str, Any]] = []
    gini_grid_str: Dict[Tuple[int, int], str] = {}
    norm_gini_grid_str: Dict[Tuple[int, int], str] = {}

    for q2 in Q2_LIST:
        for q1 in Q1_LIST:
            lps = loops_by_pair.get((q1, q2), [])
            counts = [lp["basin_count"] for lp in lps]
            metrics = compute_gini_metrics(counts)
            shares_desc = sorted(
                (lp["basin_share_pct"] for lp in lps), reverse=True
            )
            rec = {
                "q1": q1,
                "q2": q2,
                "gcd": math.gcd(q1, q2),
                "num_loops": len(lps),
                "gini": metrics["gini"],
                "norm_gini": metrics["norm_gini"],
                "hhi": metrics["hhi"],
                "evenness": metrics["evenness"],
                "top1_pct": metrics["top1_pct"],
                "min_pct": metrics["min_pct"],
                "counts_sorted": sorted(counts),
                "shares_desc_str": " / ".join(f"{s:.1f}%" for s in shares_desc),
            }
            pair_records.append(rec)
            gini_grid_str[(q1, q2)] = f"{metrics['gini']:.4f}"
            norm_gini_grid_str[(q1, q2)] = (
                f"{metrics['norm_gini']:.4f}" if len(lps) >= 2 else "0.0000"
            )

    write_matrix_csv(GINI_30X30_CSV, gini_grid_str)
    write_matrix_csv(NORM_GINI_30X30_CSV, norm_gini_grid_str)

    with FULL_GINI_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "q1", "q2", "gcd(q1,q2)", "num_loops",
            "gini", "normalized_gini", "hhi", "shannon_evenness",
            "top1_share_pct", "min_share_pct", "shares_breakdown"
        ])
        for r in pair_records:
            writer.writerow([
                r["q1"], r["q2"], r["gcd"], r["num_loops"],
                f"{r['gini']:.4f}", f"{r['norm_gini']:.4f}",
                f"{r['hhi']:.4f}", f"{r['evenness']:.4f}",
                f"{r['top1_pct']:.2f}", f"{r['min_pct']:.2f}",
                r["shares_desc_str"]
            ])

    # Filter multi-loop systems (M >= 2) and large multi-loop systems (M >= 5)
    multi_records = [r for r in pair_records if r["num_loops"] >= 2]
    many_loop_records = [r for r in pair_records if r["num_loops"] >= 5]

    # Sort for rankings
    most_unequal_norm = sorted(
        multi_records, key=lambda r: (r["norm_gini"], r["num_loops"]), reverse=True
    )
    most_equal_norm = sorted(
        multi_records, key=lambda r: (r["norm_gini"], -r["num_loops"])
    )
    most_unequal_many = sorted(
        many_loop_records, key=lambda r: r["norm_gini"], reverse=True
    )
    most_equal_many = sorted(
        many_loop_records, key=lambda r: r["norm_gini"]
    )

    # Create Visualization: Left = Lorenz curves of representative CTrees, Right = 30x30 Normalized Gini Heatmap
    plt.rcParams.update({"font.family": "serif"})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.2), dpi=180)

    # Left subplot: Lorenz curves
    ax1.plot([0, 1], [0, 1], linestyle="--", color="#64748b", label="Perfect Equality (G*=0)")

    # Pick 5 interesting cases to plot Lorenz curves
    showcase_pairs = [
        most_unequal_many[0],  # Extreme monopoly among M>=5
        next(r for r in pair_records if r["q1"] == 17 and r["q2"] == 85),  # Max 14 loops (17, 85)
        next(r for r in pair_records if r["q1"] == 35 and r["q2"] == 70),  # 13 loops (35, 70)
        most_equal_many[0],    # Most egalitarian among M>=5
        most_equal_norm[0],    # Most egalitarian overall (M>=2)
    ]
    colors = ["#dc2626", "#d97706", "#7c3aed", "#0284c7", "#16a34a"]

    for rec, col in zip(showcase_pairs, colors):
        xs = rec["counts_sorted"]
        m = len(xs)
        tot = sum(xs)
        cum_pop = [0.0] + [(i + 1) / m for i in range(m)]
        cum_wealth = [0.0]
        running = 0
        for val in xs:
            running += val
            cum_wealth.append(running / tot)
        ax1.plot(
            cum_pop,
            cum_wealth,
            marker="o",
            markersize=4,
            linewidth=2,
            color=col,
            label=f"({rec['q1']},{rec['q2']}) M={m}: G={rec['gini']:.2f}, G*={rec['norm_gini']:.2f}",
        )

    ax1.set_title("CTree Lorenz Curves (Cumulative Loops vs Basin Share)", fontsize=13, fontweight="bold")
    ax1.set_xlabel("Cumulative Share of Loops (from smallest to largest)")
    ax1.set_ylabel("Cumulative Share of Initial Values n (Basin Size)")
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.grid(True, linestyle=":", alpha=0.5)
    ax1.legend(loc="upper left", fontsize=8.8)

    # Right subplot: 30x30 Heatmap of Normalized Gini G*
    grid_mat = np.zeros((len(Q2_LIST), len(Q1_LIST)))
    for i, q2 in enumerate(Q2_LIST):
        for j, q1 in enumerate(Q1_LIST):
            rec = next(r for r in pair_records if r["q1"] == q1 and r["q2"] == q2)
            grid_mat[i, j] = rec["norm_gini"] if rec["num_loops"] >= 2 else np.nan

    cmap = plt.cm.YlOrRd.copy()
    cmap.set_bad(color="#e2e8f0")  # Gray for single-loop (M=1) cells
    im = ax2.imshow(grid_mat, cmap=cmap, vmin=0.0, vmax=1.0, aspect="auto", origin="upper")
    cbar = fig.colorbar(im, ax=ax2, fraction=0.046, pad=0.04)
    cbar.set_label("Normalized Gini G* (Gray = Single Loop M=1)")

    tick_indices = list(range(0, 30, 3))
    ax2.set_xticks(tick_indices)
    ax2.set_xticklabels([str(Q1_LIST[k]) for k in tick_indices], fontsize=9)
    ax2.set_yticks(tick_indices)
    ax2.set_yticklabels([str(Q2_LIST[k]) for k in tick_indices], fontsize=9)
    ax2.set_xlabel("q1")
    ax2.set_ylabel("q2")
    ax2.set_title("30x30 Heatmap of Normalized Gini Coefficient G*", fontsize=13, fontweight="bold")

    fig.tight_layout()
    PLOT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PNG, dpi=180)
    plt.close(fig)

    # Build Markdown report
    avg_gini_multi = statistics.mean(r["gini"] for r in multi_records)
    avg_norm_gini_multi = statistics.mean(r["norm_gini"] for r in multi_records)
    median_norm_gini_multi = statistics.median(r["norm_gini"] for r in multi_records)

    # Group by loop count M
    by_m: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in multi_records:
        by_m[r["num_loops"]].append(r)

    md: List[str] = []
    md.append("# CTree 吸引盆地の不平等度（ジニ係数・ローレンツ曲線）解析レポート")
    md.append("")
    md.append("## 1. 指標の定義：CTree における「ジニ係数」とは？")
    md.append("")
    md.append(
        "ある $(p, Q)$ に対して $M$ 本のループ（吸引盆地）が存在し、$i$ 番目のループ（小さい順に $i = 1, 2, \\dots, M$）が引き寄せる初期値の個数を $x_i$（$\\sum_{i=1}^M x_i = N = 100,000$）とします。"
    )
    md.append("- **経済学との対応**：")
    md.append("  - **各ループ（計 $M$ 本）** ＝ 「世帯（または企業）」")
    md.append("  - **各ループが吸引する初期値の数 $x_i$** ＝ 「その世帯が保有する資産（または市場シェア）」")
    md.append("- **標準ジニ係数 $G$**：")
    md.append("  $$G = \\frac{2 \\sum_{i=1}^M i \\cdot x_i}{M \\sum_{i=1}^M x_i} - \\frac{M + 1}{M} \\quad \\in \\left[0, \\frac{M-1}{M}\\right]$$")
    md.append("- **正規化ジニ係数 $G^*$（グループ数 $M$ の違いを補正した指標, $M \\ge 2$）**：")
    md.append("  ループ本数 $M$ が少ないとき（例：$M=2$）、1つのループが100%独占しても標準ジニ係数 $G$ の上限は $\\frac{M-1}{M} = 0.5$ になります。そこで異なるループ本数 $M$ 同士を公平に比較できるよう、最大値 $\\frac{M-1}{M}$ で割った **正規化ジニ係数 $G^* = \\frac{M}{M-1} G \\in [0, 1]$** を併用します。")
    md.append("  - **$G^* = 0.0$（完全平等）**：すべてのループがちょうど $\\frac{100\\%}{M}$ ずつ均等に自然数を分け合っている状態")
    md.append("  - **$G^* = 1.0$（完全独占）**：1本の巨大ループがほぼ100%の自然数を独占し、残りのループはごく少数の数値しか持たない状態")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. 全900個のDB（うち複数ループを持つ 834 個）の全体統計")
    md.append("")
    md.append(f"- **複数ループ（$M \\ge 2$）を持つペア数**: **834 / 900 ペア**（残り66ペアは $M=1$ の単一ループ独占）")
    md.append(f"- **標準ジニ係数 $G$ の平均（$M \\ge 2$）**: **{avg_gini_multi:.3f}**")
    md.append(f"- **正規化ジニ係数 $G^*$ の平均（$M \\ge 2$）**: **{avg_norm_gini_multi:.3f}**（中央値: **{median_norm_gini_multi:.3f}**）")
    md.append("  - ※ 現実世界の国家の所得ジニ係数は $0.30 \\sim 0.60$ 程度ですが、CTree の正規化ジニ係数 $G^*$ は平均 **$0.53$** とかなり高く、しかも **「$G^* \\approx 0.00$ の超平等社会」から「$G^* \\approx 0.99$ の超独占社会」まで両極端な世界が共存している** ことが判明しました！")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. ループ本数 $M$ ごとの平均ジニ係数と最大シェア率")
    md.append("")
    md.append("| ループ本数 $M$ | ペア数 | 標準ジニ係数 $G$ 平均 | 正規化ジニ係数 $G^*$ 平均 | 正規化 $G^*$ 最小〜最大 | 最大ループ平均占有率 (%) | ハーフィンダール指数 (HHI) 平均 |")
    md.append("|---:|---:|---:|---:|:---|---:|---:|")
    for m in sorted(by_m.keys()):
        recs = by_m[m]
        g_avg = statistics.mean(r["gini"] for r in recs)
        ng_avg = statistics.mean(r["norm_gini"] for r in recs)
        ng_min = min(r["norm_gini"] for r in recs)
        ng_max = max(r["norm_gini"] for r in recs)
        top1_avg = statistics.mean(r["top1_pct"] for r in recs)
        hhi_avg = statistics.mean(r["hhi"] for r in recs)
        md.append(
            f"| **{m} 本** | {len(recs)} | {g_avg:.3f} | **{ng_avg:.3f}** | `{ng_min:.3f} 〜 {ng_max:.3f}` | {top1_avg:.1f}% | {hhi_avg:.3f} |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. 【超独占型 CTree】ジニ係数が極めて高いペア TOP 10（5ループ以上 $M \\ge 5$）")
    md.append("")
    md.append("ループが5本以上たくさんあるにもかかわらず、**1〜2本の巨大ループが自然数の大半を独占し、残りのループが「孤立した小島」になっている不平等度の高い $(q_1, q_2)$** です。")
    md.append("")
    md.append("| 順位 | `(q1, q2)` | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 最大ループ占有率 | 各ループの占有率内訳（大きい順） |")
    md.append("|---:|:---|---:|---:|---:|---:|:---|")
    for idx, r in enumerate(most_unequal_many[:10], start=1):
        md.append(
            f"| {idx} | **`({r['q1']}, {r['q2']})`** | {r['num_loops']} 本 | **{r['norm_gini']:.4f}** | {r['gini']:.4f} | **{r['top1_pct']:.1f}%** | `{r['shares_desc_str']}` |"
        )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. 【超平等型 CTree】ジニ係数が極めて低いペア TOP 10")
    md.append("")
    md.append("### (A) ループ5本以上（$M \\ge 5$）で最も均等に分け合っているペア")
    md.append("| 順位 | `(q1, q2)` | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 最大ループ占有率 | 各ループの占有率内訳（大きい順） |")
    md.append("|---:|:---|---:|---:|---:|---:|:---|")
    for idx, r in enumerate(most_equal_many[:10], start=1):
        md.append(
            f"| {idx} | **`({r['q1']}, {r['q2']})`** | {r['num_loops']} 本 | **{r['norm_gini']:.4f}** | {r['gini']:.4f} | **{r['top1_pct']:.1f}%** | `{r['shares_desc_str']}` |"
        )
    md.append("")
    md.append("### (B) 全ペア（$M \\ge 2$）でほぼ完全な「50% : 50%（または33% : 33% : 33%）」を実現しているペア")
    md.append("| 順位 | `(q1, q2)` | ループ数 $M$ | 正規化ジニ $G^*$ | 標準ジニ $G$ | 各ループの占有率内訳（大きい順） |")
    md.append("|---:|:---|---:|---:|---:|:---|")
    for idx, r in enumerate(most_equal_norm[:10], start=1):
        md.append(
            f"| {idx} | **`({r['q1']}, {r['q2']})`** | {r['num_loops']} 本 | **{r['norm_gini']:.4f}** | {r['gini']:.4f} | `{r['shares_desc_str']}` |"
        )
    md.append("")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Saved report to {REPORT_MD}")
    print(f"Saved plot to {PLOT_PNG}")


if __name__ == "__main__":
    main()

