"""Visualization suite for generalized (p >= 4, Q) CTree pairing study."""

from __future__ import annotations

import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import csv
import json
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import PowerNorm
import numpy as np

from .algebra import (
    is_prime,
    multiplicative_subgroup_cosets,
    shifted_coset_map,
)
from .metrics import _join_subgroup_coset_map

plt.rcParams["font.sans-serif"] = ["IPAexGothic", "Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _fmt_count(val: int) -> str:
    if val == 0:
        return ""
    if val >= 10000:
        return f"{val / 1000:.1f}k" if val % 1000 >= 100 else f"{val // 1000}k"
    return str(val)


def _loop_world_info(
    loop_min: int,
    p: int,
    mode: str,
    m: int,
    shift_c: int | None,
    join_rmap: dict[int, int] | None = None,
) -> tuple[tuple[int, int, int], str]:
    """Return (sort_key_prefix, group_label) for a loop under multiplicative or shifted mode."""
    if mode == "multiplicative":
        g = math.gcd(loop_min, m)
        if g > 1:
            return (0, g, 0), f"{m}N(g={g})" if g < m else f"{m}N"
        cs = multiplicative_subgroup_cosets(p, m)
        cid = cs.residue_to_coset[loop_min % m]
        jcid = join_rmap[loop_min % m] if join_rmap is not None else cid
        if cs.index == 2:
            tag = "QR" if cid == 0 else "QNR"
            return (1, jcid, cid), f"{tag}_{m}"
        return (1, jcid, cid), f"C{cid}"

    if mode == "shifted":
        assert shift_c is not None
        u = (loop_min + shift_c) % m
        if u == 0:
            return (0, 0, 0), f"n≡{m - shift_c}(mod {m})"
        idx2, rmap2 = shifted_coset_map(m)
        if idx2 == 1:
            return (1, 0, 0), f"n≢{m - shift_c}(mod {m})"
        cid = rmap2[u]
        tag = "QR" if cid == 0 else "QNR"
        return (1, cid, cid), f"{tag}-{shift_c}"

    return (0, 0, 0), "all"


def _order_loops(
    loops_dict: dict[str, dict[str, Any]],
    p: int,
    mode: str,
    m: int,
    shift_c: int | None,
    join_rmap: dict[int, int] | None = None,
) -> tuple[list[int], list[str], list[tuple[int, int, str]]]:
    """Order loops by world/coset group, returning (ordered_mins, labels, block_spans)."""
    items = []
    for k_str, info in loops_dict.items():
        lmin = int(k_str)
        wkey, wlbl = _loop_world_info(lmin, p, mode, m, shift_c, join_rmap=join_rmap)
        items.append((wkey, -int(info["count_all"]), lmin, int(info["len"]), wlbl))
    items.sort(key=lambda x: (x[0], x[1], x[2]))

    ordered_mins = [x[2] for x in items]
    loop_labels = [f"{x[2]} (L={x[3]})" for x in items]

    # Build contiguous block spans [(start_idx, end_idx_excl, label)]
    spans: list[tuple[int, int, str]] = []
    if items:
        cur_lbl = items[0][4]
        cur_start = 0
        for idx, it in enumerate(items[1:], start=1):
            if it[4] != cur_lbl:
                spans.append((cur_start, idx, cur_lbl))
                cur_start = idx
                cur_lbl = it[4]
        spans.append((cur_start, len(items), cur_lbl))

    return ordered_mins, loop_labels, spans


def _plot_coset_heatmap(
    ax: plt.Axes,
    table_entry: dict[str, Any],
    title: str,
    subtitle: str = "",
    use_join_col_order: bool = False,
) -> None:
    """Plot a coset-ordered contingency matrix heatmap on the given Axes."""
    p_a = int(table_entry["spec_a"]["p"])
    q_a = table_entry["spec_a"]["q"]
    p_b = int(table_entry["spec_b"]["p"])
    q_b = table_entry["spec_b"]["q"]
    mode = table_entry["invariant_mode"]
    m = int(table_entry["modulus"])
    shift_c = table_entry["shift_c"]

    join_rmap = None
    if use_join_col_order and mode == "multiplicative" and m >= 2:
        _, _, join_rmap = _join_subgroup_coset_map(p_a, p_b, m)

    rows_min, rows_lbl, row_spans = _order_loops(
        table_entry["loops_a"], p_a, mode, m, shift_c, join_rmap=join_rmap if use_join_col_order else None
    )
    cols_min, cols_lbl, col_spans = _order_loops(
        table_entry["loops_b"], p_b, mode, m, shift_c, join_rmap=join_rmap if use_join_col_order else None
    )

    row_idx = {v: i for i, v in enumerate(rows_min)}
    col_idx = {v: j for j, v in enumerate(cols_min)}
    mat = np.zeros((len(rows_min), len(cols_min)), dtype=np.int64)
    for a, b, cnt in table_entry["ct_all"]:
        if a in row_idx and b in col_idx:
            mat[row_idx[a], col_idx[b]] = cnt

    vmax = max(1, int(mat.max()))
    masked = np.ma.masked_where(mat == 0, mat)
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad(color="#F5F6F8")

    ax.imshow(
        masked,
        cmap=cmap,
        norm=PowerNorm(gamma=0.45, vmin=1, vmax=vmax),
        aspect="auto",
        interpolation="nearest",
    )

    nr, nc = mat.shape
    # Cell counts if matrix is reasonably compact
    if nr <= 12 and nc <= 12:
        thresh = vmax * 0.42
        fs = 8.5 if max(nr, nc) <= 6 else 6.8
        for i in range(nr):
            for j in range(nc):
                val = int(mat[i, j])
                if val > 0:
                    color = "white" if val >= thresh else "#1B263B"
                    ax.text(
                        j,
                        i,
                        _fmt_count(val),
                        ha="center",
                        va="center",
                        fontsize=fs,
                        color=color,
                        fontweight="bold" if nr <= 6 and nc <= 6 else "normal",
                    )

    # World divider lines
    for s, e, _ in row_spans[:-1]:
        ax.axhline(e - 0.5, color="#D62828", linestyle="--", linewidth=1.3, alpha=0.9)
    for s, e, _ in col_spans[:-1]:
        ax.axvline(e - 0.5, color="#D62828", linestyle="--", linewidth=1.3, alpha=0.9)

    # Tick labels: individual loops if <= 14, else block center labels
    if nr <= 14:
        ax.set_yticks(range(nr))
        ax.set_yticklabels(rows_lbl, fontsize=7.5 if nr > 8 else 8.5)
    else:
        ax.set_yticks([0.5 * (s + e - 1) for s, e, _ in row_spans])
        ax.set_yticklabels([f"{lbl} ({e-s})" for s, e, lbl in row_spans], fontsize=7.5)

    if nc <= 14:
        ax.set_xticks(range(nc))
        ax.set_xticklabels(cols_lbl, rotation=38, ha="right", fontsize=7.5 if nc > 8 else 8.5)
    else:
        ax.set_xticks([0.5 * (s + e - 1) for s, e, _ in col_spans])
        ax.set_xticklabels(
            [f"{lbl}" for _, _, lbl in col_spans],
            rotation=60,
            ha="right",
            fontsize=6.8,
        )

    # Subtle minor grid
    ax.set_xticks(np.arange(-0.5, nc, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, nr, 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=0.5, alpha=0.6)
    ax.tick_params(which="minor", length=0)

    ax.set_ylabel(f"p={p_a}, Q={tuple(q_a)}", fontsize=9, fontweight="bold")
    ax.set_xlabel(f"p={p_b}, Q={tuple(q_b)}", fontsize=9, fontweight="bold")
    full_title = title if not subtitle else f"{title}\n{subtitle}"
    ax.set_title(full_title, fontsize=10, pad=8)


def _find_table(
    tables: list[dict[str, Any]],
    pa: int,
    qa: list[int],
    pb: int,
    qb: list[int],
) -> dict[str, Any]:
    for t in tables:
        sa = t["spec_a"]
        sb = t["spec_b"]
        if sa["p"] == pa and sa["q"] == qa and sb["p"] == pb and sb["q"] == qb:
            return t
    raise KeyError(f"Table not found for p{pa}:{qa} vs p{pb}:{qb}")


def generate_all_charts(out_dir: Path | str = Path("outputs/pairing_p4plus")) -> list[Path]:
    """Generate all 7 summary PNG charts under out_dir/charts/."""
    out = Path(out_dir)
    charts_dir = out / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    p2_tables = json.loads((out / "phase2_highlight_tables.json").read_text(encoding="utf-8"))
    p3_tables = json.loads((out / "phase3_highlight_tables.json").read_text(encoding="utf-8"))
    created: list[Path] = []

    # --- Fig 1: p=4 mod 13 cross-family equality & 2x flip swap ---
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.4), dpi=180)
    t_cross = _find_table(p2_tables, 4, [26, 13], 4, [26, 91])
    t_flip = _find_table(p2_tables, 4, [26, 13], 4, [26, 52])
    _plot_coset_heatmap(
        axes[0],
        t_cross,
        "別ファミリー・異ループ長での100%集合一致 (mod 13)",
        "2(L=6)==41(L=33) [461.5k], 10(L=42)==1(L=12) [461.5k]",
    )
    _plot_coset_heatmap(
        axes[1],
        t_flip,
        "2倍反転共役による長短ループのQR/QNRスワップ (mod 13)",
        "(2/13)=-1 により L=6↔L=42 が入れ替わったまま100%一致",
    )
    fig.suptitle("Fig 1. p=4 (法 13, 指数 2) の完全集合一致と2倍反転 (N=1,000,000)", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p1 = charts_dir / "fig1_p4_mod13_equality_and_swap.png"
    fig.savefig(p1, bbox_inches="tight")
    plt.close(fig)
    created.append(p1)

    # --- Fig 2: Cross-p exact equality & strict inclusion ---
    fig, axes = plt.subplots(1, 3, figsize=(17.5, 5.6), dpi=180)
    t_c1 = _find_table(p2_tables, 3, [23], 4, [161, 115])
    t_c2 = _find_table(p2_tables, 3, [47], 4, [188, 94])
    t_c3 = _find_table(p2_tables, 4, [209, 88], 5, [11, 22, 77])
    _plot_coset_heatmap(
        axes[0],
        t_c1,
        "p=3 vs p=4 (法 23): 異p間の100%完全一致",
        "QR_23: 41==47 [478.3k], 23N: 23==23 [43.5k]",
    )
    _plot_coset_heatmap(
        axes[1],
        t_c2,
        "p=3 vs p=4 (法 47): 原始全7ループが厳密包含",
        "p=3 の全原始ループが p=4 の2本(2, 10)に完全分割 (V=1.0)",
    )
    _plot_coset_heatmap(
        axes[2],
        t_c3,
        "p=4 vs p=5 (法 11): QNR_11 10本を1本で包含",
        "p=5 の QNR_11 全10ループが p=4 ループ 8 (454.5k) に包含",
    )
    fig.suptitle("Fig 2. 異なる倍率 p 間（p=3 vs 4, p=4 vs 5）の完全一致と厳密包含 (N=1,000,000)", fontsize=12.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p2 = charts_dir / "fig2_cross_p_equality_and_inclusion.png"
    fig.savefig(p2, bbox_inches="tight")
    plt.close(fig)
    created.append(p2)

    # --- Fig 3: Composite Jacobi & Shifted gcd=1 walls ---
    fig, axes = plt.subplots(1, 3, figsize=(17.5, 5.6), dpi=180)
    t_j = _find_table(p2_tables, 5, [63, 42, 21], 5, [63, 42, 105])
    t_s7 = _find_table(p2_tables, 7, [11, 16, 21, 26, 1], 7, [11, 16, 21, 26, 31])
    t_s9 = _find_table(p3_tables, 9, [15, 22, 29, 36, 43, 50, 1], 9, [15, 22, 29, 36, 43, 50, 57])
    _plot_coset_heatmap(
        axes[0],
        t_j,
        "p=5 合成数ヤコビ記号壁 (法 21 = 3×7)",
        "J=+1 の3ループ(26,38,41)がループ58 [285.7k] に厳密包含",
    )
    _plot_coset_heatmap(
        axes[1],
        t_s7,
        "p=7 gcd=1 シフト合同壁 (法 5, c=1)",
        "補集合 1==23 [800k 完全一致] ＋ n≡4(mod 5) 3重包含",
    )
    _plot_coset_heatmap(
        axes[2],
        t_s9,
        "p=9 gcd=1 シフト平方剰余壁 (法 7, c=1)",
        "固定類 n≡6 と QR_7-1 / QNR_7-1 の3平行世界へ完全隔離",
    )
    fig.suptitle("Fig 3. 合成数ヤコビ記号壁および gcd(Q)=1 シフト合同による隔離・包含 (N=1,000,000)", fontsize=12.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p3 = charts_dir / "fig3_jacobi_and_shifted_walls.png"
    fig.savefig(p3, bbox_inches="tight")
    plt.close(fig)
    created.append(p3)

    # --- Fig 4: Higher-order residue cosets (idx = 3, 5, 7, 12) ---
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 11.8), dpi=180)
    t_h3 = _find_table(p3_tables, 8, [76, 19, 95, 38, 114, 57], 8, [76, 19, 95, 38, 114, 190])
    t_h5 = _find_table(p3_tables, 6, [124, 93, 62, 31], 6, [124, 93, 62, 186])
    t_h7 = _find_table(p3_tables, 7, [215, 172, 129, 86, 43], 7, [215, 172, 129, 86, 301])
    t_h12 = _find_table(p3_tables, 9, [511, 438, 365, 292, 219, 146, 73], 9, [511, 438, 365, 292, 219, 146, 657])
    _plot_coset_heatmap(axes[0, 0], t_h3, "p=8, m=19: 3次剰余（指数 3）", "3個の独立コセットブロック＋19N (リーク=0)")
    _plot_coset_heatmap(axes[0, 1], t_h5, "p=6, m=31: 5次剰余（指数 5）", "5個の独立コセットブロック＋31N (リーク=0)")
    _plot_coset_heatmap(axes[1, 0], t_h7, "p=7, m=43: 7次剰余（指数 7）", "7個の独立コセットブロック＋43N (リーク=0)")
    _plot_coset_heatmap(axes[1, 1], t_h12, "p=9, m=73: 12次剰余（指数 12）", "12個の独立コセットブロック＋73N (リーク=0)")
    fig.suptitle("Fig 4. p >= 6 に出現する平方剰余を超えた高次剰余の平行世界 (N=1,000,000)", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    p4 = charts_dir / "fig4_higher_order_residues.png"
    fig.savefig(p4, bbox_inches="tight")
    plt.close(fig)
    created.append(p4)

    # --- Fig 5: Nested & Orthogonal Cross-p hierarchies ---
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 5.8), dpi=180)
    t_nest = _find_table(p3_tables, 4, [146, 73], 9, [511, 438, 365, 292, 219, 146, 73])
    t_orth = _find_table(p3_tables, 6, [19, 38, 57, 76], 8, [76, 19, 95, 38, 114, 57])
    _plot_coset_heatmap(
        axes[0],
        t_nest,
        "入れ子階層: p=4 (法73, 指数2) ⊃ p=9 (法73, 指数12)",
        "QR_73 / QNR_73 の各ブロックが p=9 の 6 コセットを厳密内包",
        use_join_col_order=True,
    )
    _plot_coset_heatmap(
        axes[1],
        t_orth,
        "直交部分群: p=6 (法19, 指数2) vs p=8 (法19, 指数3)",
        "平方コセット(2) × 立方コセット(3) が全6区画へ混合（19Nのみ隔離）",
    )
    fig.suptitle("Fig 5. 異なる p 間の乗法部分群の包含（入れ子）と直交対照 (N=1,000,000)", fontsize=12.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p5 = charts_dir / "fig5_nested_and_orthogonal_cross_p.png"
    fig.savefig(p5, bbox_inches="tight")
    plt.close(fig)
    created.append(p5)

    # --- Fig 6: Scaling of Cramer's V vs N ---
    with (out / "phase2_scaling_1m.csv").open("r", encoding="utf-8") as f:
        srows = list(csv.DictReader(f))
    by_pair: dict[tuple[int, str, int, str], dict[int, float]] = {}
    for r in srows:
        if r["prim_cramers_v"] == "":
            continue
        k = (int(r["p_a"]), r["q_a"], int(r["p_b"]), r["q_b"])
        by_pair.setdefault(k, {})[int(r["n_max"])] = float(r["prim_cramers_v"])

    curve_specs = [
        ((4, "[26, 13]", 4, "[26, 91]"), "p4:(26,13)-(26,91) mod 13 [完全一致, V=1.0]", "#0072B2", "o", "-", 2.8),
        ((3, "[47]", 4, "[188, 94]"), "p3:(47) vs p4:(188,94) mod 47 [異p厳密包含, V=1.0]", "#009E73", "s", "--", 2.0),
        ((3, "[23]", 4, "[161, 115]"), "p3:(23) vs p4:(161,115) mod 23 [異p一致]", "#56B4E9", "^", "-", 2.0),
        ((5, "[63, 42, 21]", 5, "[63, 42, 105]"), "p5:(63,42,21)-(63,42,105) mod 21 [ヤコビ壁]", "#CC79A7", "D", "-", 2.0),
        ((5, "[31, 10, 49]", 5, "[31, 22, 49]"), "p5:(31,10,49)-(31,22,49) mod 3 [シフトgcd=1]", "#E69F00", "v", "-", 2.0),
        ((4, "[209, 88]", 5, "[11, 22, 77]"), "p4:(209,88) vs p5:(11,22,77) mod 11 [異p包含]", "#332288", "P", "-", 2.0),
        ((4, "[11, 1]", 4, "[44, 4]"), "p4:(11,1)-(44,4) [非コセット p倍兄弟]", "#D55E00", "o", "--", 2.0),
        ((5, "[7, 2, 1]", 5, "[35, 10, 5]"), "p5:(7,2,1)-(35,10,5) [非コセット p倍兄弟]", "#882255", "s", "--", 2.0),
        ((5, "[3, 2, 1]", 5, "[3, 2, 53]"), "p5:(3,2,1)-(3,2,53) [対照: 互いに素]", "#666666", "x", ":", 1.8),
        ((4, "[2, 1]", 4, "[5, 1]"), "p4:(2,1)-(5,1) [対照: 互いに素]", "#999999", "+", ":", 1.8),
        ((4, "[2, 19]", 4, "[5, 13]"), "p4:(2,19)-(5,13) [対照: 互いに素]", "#BBBBBB", ".", ":", 1.8),
    ]
    fig, ax = plt.subplots(figsize=(10.5, 6.2), dpi=180)
    for key, label, col, mk, ls, lw in curve_specs:
        if key not in by_pair:
            continue
        pts = sorted(by_pair[key].items())
        xs = [x for x, _ in pts]
        ys = [max(y, 1e-4) for _, y in pts]
        ax.loglog(xs, ys, label=label, color=col, marker=mk, linestyle=ls, linewidth=lw, markersize=6)

    ns_ref = np.array([10000, 1000000], dtype=float)
    ax.loglog(ns_ref, 0.08 * (ns_ref / 10000.0) ** (-0.5), color="#333333", linestyle="-.", linewidth=1.2, label="参照線 ∝ N^(-1/2) (純ランダム減衰)")
    ax.set_xlabel("探索上限 N（対数スケール）", fontsize=10.5)
    ax.set_ylabel("原始 d-free 層 Cramér's V（対数スケール）", fontsize=10.5)
    ax.set_title("Fig 6. サンプルサイズ N に対する Cramér's V のスケーリング挙動 (10k → 1M)", fontsize=12, fontweight="bold")
    ax.set_ylim(5e-4, 1.45)
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8.3, framealpha=0.95, ncol=1)
    fig.tight_layout()
    p6 = charts_dir / "fig6_scaling_v_vs_n.png"
    fig.savefig(p6, bbox_inches="tight")
    plt.close(fig)
    created.append(p6)

    # --- Fig 7: Theoretical landscape across p=3..9 and m <= 120 ---
    ps = list(range(3, 10))
    smallest_idx2: list[int] = []
    smallest_idx3: list[int | None] = []
    pts_prime2: list[tuple[int, int]] = []
    pts_jacobi: list[tuple[int, int]] = []
    pts_high: list[tuple[int, int, int]] = []

    for p in ps:
        p2_first = None
        p3_first = None
        for m in range(3, 121):
            if math.gcd(m, p) != 1 or math.gcd(m, p - 1) != 1:
                continue
            cs = multiplicative_subgroup_cosets(p, m)
            if cs.index < 2:
                continue
            if is_prime(m):
                if cs.index == 2:
                    if p2_first is None:
                        p2_first = m
                    pts_prime2.append((p, m))
                else:
                    if p3_first is None:
                        p3_first = m
                    pts_high.append((p, m, cs.index))
            else:
                if cs.is_pure_composite_coupling:
                    pts_jacobi.append((p, m))
                elif cs.index >= 3:
                    # composite with higher-order structure (only mark minimal ones if prime factor didn't already have it)
                    pass
        smallest_idx2.append(p2_first if p2_first is not None else 0)
        smallest_idx3.append(p3_first)

    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(14.5, 5.6), dpi=180, gridspec_kw={"width_ratios": [1.0, 1.35]})
    x_pos = np.arange(len(ps))
    bars = ax_l.bar(x_pos, smallest_idx2, width=0.52, color="#0072B2", alpha=0.88, label="最小の指数2素数法 (平方剰余壁)")
    for b, val in zip(bars, smallest_idx2):
        ax_l.text(b.get_x() + b.get_width() / 2, val + 0.8, str(val), ha="center", va="bottom", fontsize=9.5, fontweight="bold")
    added_lbl3 = False
    for idx, val3 in enumerate(smallest_idx3):
        if val3 is not None:
            ax_l.scatter(
                [idx],
                [val3],
                color="#D55E00",
                s=90,
                zorder=5,
                marker="D",
                label="最小の高次剰余素数 (指数>=3)" if not added_lbl3 else None,
            )
            added_lbl3 = True
            ax_l.annotate(
                f"ℓ={val3}",
                (idx, val3),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                color="#A03000",
                fontweight="bold",
                bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85},
            )
    ax_l.set_xticks(x_pos)
    ax_l.set_xticklabels([f"p={p}\n(d={p-1})" for p in ps], fontsize=9)
    ax_l.set_ylabel("素数法 ℓ", fontsize=10)
    ax_l.set_ylim(0, max(smallest_idx2 + [v for v in smallest_idx3 if v]) + 8)
    ax_l.set_title("各 p で最初に現れる非自明コセットの素数法 ℓ", fontsize=10.5, fontweight="bold")
    ax_l.grid(axis="y", linestyle=":", alpha=0.5)
    ax_l.legend(loc="upper left", fontsize=8.5)

    if pts_prime2:
        ax_r.scatter([x for x, _ in pts_prime2], [y for _, y in pts_prime2], c="#0072B2", s=42, alpha=0.8, label="素数 平方剰余 (指数=2)")
    if pts_jacobi:
        ax_r.scatter([x for x, _ in pts_jacobi], [y for _, y in pts_jacobi], c="#009E73", marker="^", s=72, alpha=0.9, label="純合成数 ヤコビ壁 (CRT結合)")
    if pts_high:
        ax_r.scatter([x for x, _, _ in pts_high], [y for _, y, _ in pts_high], c="#D55E00", marker="D", s=85, zorder=5, label="高次剰余素数 (指数>=3)")
        for px, py, pidx in pts_high:
            ax_r.annotate(f"m={py}(I={pidx})", (px, py), xytext=(6, -3), textcoords="offset points", fontsize=7.8, color="#A03000", fontweight="bold")
    ax_r.set_xticks(ps)
    ax_r.set_xticklabels([f"p={p}" for p in ps], fontsize=9.5)
    ax_r.set_xlim(2.5, 9.85)
    ax_r.set_ylim(0, 125)
    ax_r.set_ylabel("法 m (<= 120)", fontsize=10)
    ax_r.set_title("H_p(m)=<p, p-1> の指数 I_p(m) >= 2 分布図", fontsize=10.5, fontweight="bold")
    ax_r.grid(True, linestyle=":", alpha=0.5)
    ax_r.legend(loc="upper left", fontsize=8.5)

    fig.suptitle("Fig 7. p=3〜9 における乗法部分群コセット壁の数論的マップ (m <= 120)", fontsize=12.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p7 = charts_dir / "fig7_theory_map_p3_to_p9.png"
    fig.savefig(p7, bbox_inches="tight")
    plt.close(fig)
    created.append(p7)

    return created
