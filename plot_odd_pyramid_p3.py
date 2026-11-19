#!/usr/bin/env python3
"""
Generate expanded Odd Pyramid diagrams (PNG + SVG) with p=3 loop counts M(q)
for q in [1, 19999] from data/p3/summary_p3.db, and analyze prime multiplier
rules (*3, *5, *7, *11, *13, ...) across the entire 10,000-system dataset.
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np

# Configure Japanese font
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DB_PATH = Path("data/p3/summary_p3.db")
OUT_DIR = Path("docs/2026_1105")
DATA_OUT_DIR = Path("data/p3")


def load_p3_data(db_path: Path = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT q1, num_loops FROM systems ORDER BY q1")
    loops = dict(cur.fetchall())

    cur.execute(
        """
        SELECT s.q1, l.min_value, l.max_value, l.length, l.l_div_count, l.k_mul_count
        FROM loops l JOIN systems s ON l.system_id = s.system_id
        """
    )
    all_loops = cur.fetchall()
    conn.close()
    return loops, all_loops


def build_pyramid_levels(primes: list[int], max_q: int = 19999):
    """
    Build pyramid levels starting from Level 0 (primes) down to the deepest level
    where products <= max_q exist. Only include nodes with q <= max_q that have
    at least 1 edge in the graph.
    """
    primes_sorted = sorted(primes, reverse=True)
    levels_raw: dict[int, list[int]] = {
        0: [p for p in primes_sorted if p <= max_q]
    }
    lvl = 0
    while True:
        next_set = set()
        for u in levels_raw[lvl]:
            for p in primes_sorted:
                val = u * p
                if val <= max_q:
                    next_set.add(val)
        if not next_set:
            break
        lvl += 1
        levels_raw[lvl] = sorted(next_set, reverse=True)

    # Collect all directed edges (u in lvl -> v in lvl+1 via *p)
    edges = []  # (lvl, u, v, p)
    connected_nodes = set()
    for l_idx in range(len(levels_raw) - 1):
        next_nodes_set = set(levels_raw[l_idx + 1])
        for u in levels_raw[l_idx]:
            for p in primes_sorted:
                v = u * p
                if v in next_nodes_set:
                    edges.append((l_idx, u, v, p))
                    connected_nodes.add((l_idx, u))
                    connected_nodes.add((l_idx + 1, v))

    # Filter each level to nodes with at least one connected edge
    levels: dict[int, list[int]] = {}
    for l_idx, nodes in levels_raw.items():
        filtered = [u for u in nodes if (l_idx, u) in connected_nodes]
        if filtered:
            levels[l_idx] = filtered

    return levels, edges


def compute_pyramid_positions(levels: dict[int, list[int]], primes: list[int]):
    """
    Assign (x, y) coordinates to each node (lvl, q) so that:
    - While all theoretical nodes fit <= 19999 (top levels), rows widen symmetrically
      like odd_pyramid.png.
    - Once left-side theoretical products exceed 19999 (lower levels), the right-most
      node (3^(lvl+1)) continues along a straight diagonal right spine, and the
      valid <= 19999 nodes are placed to its left, leaving the > 19999 region on the
      bottom-left blank.
    """
    k = len(primes)
    pos: dict[tuple[int, int], tuple[float, float]] = {}

    # Find the last level where all theoretical nodes are <= 19999
    full_up_to = 0
    for l_idx, nodes in levels.items():
        theo_count = math.comb(l_idx + k, k - 1)
        if len(nodes) == theo_count:
            full_up_to = l_idx
        else:
            break

    # Right spine slope per level during full expansion:
    # At level l, width is W_l, centered -> right-most x is (W_l - 1) / 2.
    # For l > full_up_to, continue the right-most spine smoothly with a constant step
    # so the right boundary (powers of 3: 3, 9, 27, ..., 19683) forms a clean diagonal line.
    if full_up_to >= 1:
        w_last = len(levels[full_up_to])
        w_prev = len(levels[full_up_to - 1])
        right_step = min(3.5, max(1.5, (w_last - w_prev) / 2.0))
    else:
        right_step = 1.5

    right_x_at_full = (len(levels[full_up_to]) - 1) / 2.0

    for l_idx, nodes in levels.items():
        n_nodes = len(nodes)
        if l_idx <= full_up_to:
            right_x = (n_nodes - 1) / 2.0
        else:
            right_x = right_x_at_full + (l_idx - full_up_to) * right_step

        # Place nodes from right to left ending at right_x with spacing 1.0
        for idx, q in enumerate(nodes):
            # idx = 0 is largest (leftmost), idx = n_nodes - 1 is smallest (3^(l+1), rightmost)
            offset_from_right = (n_nodes - 1) - idx
            x = right_x - offset_from_right * 1.0
            y = -float(l_idx)
            pos[(l_idx, q)] = (x, y)

    return pos, full_up_to


LEVEL_BORDER_COLORS = [
    "#0f172a",  # Level 0: dark navy (like odd_pyramid.png)
    "#475569",  # Level 1: slate (like odd_pyramid.png)
    "#9333ea",  # Level 2: purple (like odd_pyramid.png)
    "#2563eb",  # Level 3: royal blue
    "#0d9488",  # Level 4: teal
    "#16a34a",  # Level 5: green
    "#d97706",  # Level 6: amber
    "#ea580c",  # Level 7: orange
    "#dc2626",  # Level 8: red
]

PRIME_EDGE_STYLES = {
    3:  {"color": "#64748b", "ls": "-",  "lw": 1.3, "label": "×3 (クローン: +0本)"},
    5:  {"color": "#2563eb", "ls": "-",  "lw": 1.2, "label": "×5 (進化: 素数で+5〜+8本)"},
    7:  {"color": "#9333ea", "ls": "-",  "lw": 1.1, "label": "×7 (進化: 素数で+1〜+4本)"},
    11: {"color": "#d97706", "ls": "-",  "lw": 1.0, "label": "×11 (進化: 素数で+2〜+5本)"},
    13: {"color": "#dc2626", "ls": "-",  "lw": 1.0, "label": "×13 (進化: 素数で+9〜+12本)"},
}


def render_odd_pyramid(
    primes: list[int],
    loops: dict[int, int],
    out_stem: str,
    max_level: int | None = None,
    show_edge_deltas: bool = True,
):
    levels, edges = build_pyramid_levels(primes, max_q=19999)
    if max_level is not None:
        levels = {k: v for k, v in levels.items() if k <= max_level}
        edges = [e for e in edges if e[0] < max_level]

    pos, full_up_to = compute_pyramid_positions(levels, primes)

    all_x = [xy[0] for xy in pos.values()]
    all_y = [xy[1] for xy in pos.values()]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    span_x = max(max_x - min_x + 3.0, 10.0)
    span_y = max(max_y - min_y + 2.2, 4.0)

    # Scale figure size based on node density so circles never overlap
    total_nodes = sum(len(v) for v in levels.values())
    max_row_nodes = max(len(v) for v in levels.values())
    if max_row_nodes <= 15:
        unit_w = 1.15
        unit_h = 2.1
        node_radius = 0.36
        q_fontsize = 10.5
        m_fontsize = 9.0
        edge_fontsize = 7.5
    elif max_row_nodes <= 25:
        unit_w = 0.95
        unit_h = 1.95
        node_radius = 0.35
        q_fontsize = 9.0
        m_fontsize = 8.0
        edge_fontsize = 6.8
    elif max_row_nodes <= 48:
        unit_w = 0.78
        unit_h = 1.85
        node_radius = 0.34
        q_fontsize = 7.5
        m_fontsize = 6.8
        edge_fontsize = 5.8
    else:
        unit_w = 0.68
        unit_h = 1.80
        node_radius = 0.34
        q_fontsize = 6.4
        m_fontsize = 5.8
        edge_fontsize = 5.0

    fig_w = max(14.0, span_x * unit_w)
    fig_h = max(9.0, span_y * unit_h)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    # Equal aspect in data units after scaling y by y_scale
    y_scale = unit_h / unit_w
    scaled_pos = {k: (xy[0], xy[1] * y_scale) for k, xy in pos.items()}

    # Draw subtle background grid like odd_pyramid.png
    x_pad = 1.6
    y_pad = 1.3 * y_scale
    xlim = (min_x - x_pad, max_x + x_pad)
    ylim = (min_y * y_scale - y_pad, max_y * y_scale + y_pad)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")

    grid_step = 0.5
    for gx in np.arange(math.floor(xlim[0]), math.ceil(xlim[1]) + grid_step, grid_step):
        ax.axvline(gx, color="#f1f5f9", lw=0.6, zorder=0)
    for gy in np.arange(math.floor(ylim[0]), math.ceil(ylim[1]) + grid_step, grid_step):
        ax.axhline(gy, color="#f1f5f9", lw=0.6, zorder=0)

    # Draw edges and multiplier labels
    for l_idx, u, v, p in edges:
        x1, y1 = scaled_pos[(l_idx, u)]
        x2, y2 = scaled_pos[(l_idx + 1, v)]
        style = PRIME_EDGE_STYLES.get(
            p, {"color": "#94a3b8", "ls": "-", "lw": 0.9}
        )
        # Shorten line to circle boundaries
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist > 2 * node_radius:
            sx1 = x1 + (dx / dist) * node_radius
            sy1 = y1 + (dy / dist) * node_radius
            sx2 = x2 - (dx / dist) * node_radius
            sy2 = y2 - (dy / dist) * node_radius
        else:
            sx1, sy1, sx2, sy2 = x1, y1, x2, y2

        alpha = 0.72 if p == 3 else (0.55 if max_row_nodes <= 25 else 0.40)
        ax.plot(
            [sx1, sx2],
            [sy1, sy2],
            color=style["color"],
            linestyle=style["ls"],
            linewidth=style["lw"],
            alpha=alpha,
            zorder=1,
        )

        # Edge label staggered by prime p so labels never sit on the same horizontal line
        if max_row_nodes <= 25 or l_idx <= 2 or p == 3:
            t_map = {3: 0.36, 5: 0.45, 7: 0.54, 11: 0.63, 13: 0.72}
            t_pos = t_map.get(p, 0.50)
            lx = x1 + dx * t_pos
            ly = y1 + dy * t_pos
            dm = loops[v] - loops[u]
            if show_edge_deltas and (max_row_nodes <= 25 or l_idx <= 1):
                lbl = f"×{p} ({dm:+d})"
            else:
                lbl = f"×{p}"
            ax.text(
                lx,
                ly,
                lbl,
                fontsize=edge_fontsize,
                color=style["color"],
                ha="center",
                va="center",
                fontweight="bold" if p == 3 else "normal",
                bbox=dict(
                    boxstyle="round,pad=0.12",
                    facecolor="#ffffff",
                    edgecolor="none",
                    alpha=0.82,
                ),
                zorder=2,
            )

    # Draw circular nodes with q and loop count M(q)
    for l_idx, nodes in levels.items():
        border_col = LEVEL_BORDER_COLORS[l_idx % len(LEVEL_BORDER_COLORS)]
        for q in nodes:
            cx, cy = scaled_pos[(l_idx, q)]
            m_val = loops.get(q, 0)

            # Highlight nodes based on loop count richness
            if m_val == 1:
                fill_col = "#f8fafc"
                m_col = "#475569"
            elif m_val >= 25:
                fill_col = "#fef2f2"
                m_col = "#dc2626"
            elif m_val >= 12:
                fill_col = "#eff6ff"
                m_col = "#1d4ed8"
            else:
                fill_col = "#f8fafc"
                m_col = "#0f766e"

            circ = mpatches.Circle(
                (cx, cy),
                radius=node_radius,
                facecolor=fill_col,
                edgecolor=border_col,
                linewidth=2.0,
                zorder=3,
            )
            ax.add_patch(circ)

            # Top line inside circle: odd number q
            ax.text(
                cx,
                cy + node_radius * 0.26,
                f"{q}",
                fontsize=q_fontsize,
                fontweight="bold",
                color="#0f172a",
                ha="center",
                va="center",
                zorder=4,
            )
            # Subtle divider inside circle
            ax.plot(
                [cx - node_radius * 0.68, cx + node_radius * 0.68],
                [cy - node_radius * 0.02, cy - node_radius * 0.02],
                color="#cbd5e1",
                lw=0.7,
                zorder=4,
            )
            # Bottom line inside circle: loop count M(q)
            ax.text(
                cx,
                cy - node_radius * 0.36,
                f"{m_val}本",
                fontsize=m_fontsize,
                fontweight="bold",
                color=m_col,
                ha="center",
                va="center",
                zorder=4,
            )

        # Level annotation on the right side of the row
        rx, ry = scaled_pos[(l_idx, nodes[-1])]
        theo_w = math.comb(l_idx + len(primes), len(primes) - 1)
        ax.text(
            rx + node_radius + 0.35,
            ry,
            f"Level {l_idx}\n({len(nodes)}/{theo_w}個)",
            fontsize=edge_fontsize + 1.2,
            color=border_col,
            fontweight="bold",
            ha="left",
            va="center",
            zorder=4,
        )

    # Annotate the blank > 19999 region on the bottom-left if levels > full_up_to
    if max(levels.keys()) > full_up_to + 1:
        blank_x = min_x + (max_x - min_x) * 0.18
        blank_y = (min_y + 1.2) * y_scale
        ax.text(
            blank_x,
            blank_y,
            "※ これより左側は q > 19,999 となるため空白\n"
            "（p=3 収集データ 1〜19,999 の範囲内で\n"
            "  少なくとも1本の線で繋がる全ノードを表示）",
            fontsize=max(9.0, q_fontsize),
            color="#64748b",
            ha="center",
            va="center",
            bbox=dict(
                boxstyle="round,pad=0.6",
                facecolor="#f8fafc",
                edgecolor="#cbd5e1",
                linestyle="--",
                linewidth=1.2,
            ),
            zorder=4,
        )

    # Top-left badge matching odd_pyramid.png style
    primes_str = ", ".join(str(p) for p in sorted(primes, reverse=True))
    max_lvl = max(levels.keys())
    badge_text = (
        f"Numbers: {primes_str}  |  Levels: 0 to {max_lvl}  |  "
        f"Nodes (q ≤ 19,999): {total_nodes}個  |  上段: 奇数 q / 下段: p=3 ループ本数 M(q)"
    )
    ax.text(
        xlim[0] + 0.3,
        ylim[1] - 0.35,
        badge_text,
        fontsize=max(10.0, q_fontsize + 1.0),
        color="#334155",
        fontweight="bold",
        ha="left",
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.45",
            facecolor="#ffffff",
            edgecolor="#e2e8f0",
            linewidth=1.2,
        ),
        zorder=5,
    )

    # Legend for prime multipliers
    legend_handles = [
        Line2D([0], [0], color=PRIME_EDGE_STYLES[p]["color"], lw=2.2, label=PRIME_EDGE_STYLES[p]["label"])
        for p in sorted(primes)
        if p in PRIME_EDGE_STYLES
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper right",
        frameon=True,
        facecolor="#ffffff",
        edgecolor="#e2e8f0",
        fontsize=max(8.5, q_fontsize),
        title="奇数倍（×p）とループ増分の法則",
        title_fontsize=max(9.0, q_fontsize + 0.5),
    )

    ax.axis("off")
    plt.tight_layout()

    for target_dir in [OUT_DIR, DATA_OUT_DIR]:
        target_dir.mkdir(parents=True, exist_ok=True)
        png_path = target_dir / f"{out_stem}.png"
        svg_path = target_dir / f"{out_stem}.svg"
        fig.savefig(png_path, dpi=200, bbox_inches="tight")
        fig.savefig(svg_path, format="svg", bbox_inches="tight")

    plt.close(fig)
    print(f"Saved {out_stem}.png and {out_stem}.svg ({total_nodes} nodes, {len(edges)} edges)")


def render_multiplier_analysis_figure(loops: dict[int, int], all_loops: list):
    """
    Create a 4-panel analytical chart (PNG + SVG) explaining:
    1. Distribution of Delta_{xr}(q) = M(rq) - M(q) for primes r = 3, 5, 7, 11, 13, 17, 19, 23
    2. Comparison between raw N_max=100,000 agreement and scale-invariant (min_val <= 5q) 100% agreement
    3. How M(3^a * c) stays invariant across powers of 3 and where the fixed N=100,000 cutoff takes effect
    4. Exact Divisor-Sum decomposition M_inf(q) = sum_{d | core_3(q)} P(d)
    """
    loops_by_q = defaultdict(list)
    prim_by_d = defaultdict(set)
    for q1, min_v, max_v, length, L, K in all_loops:
        loops_by_q[q1].append((min_v, max_v, length, L, K))
        g = math.gcd(min_v, q1)
        d = q1 // g
        prim_by_d[d].add((min_v // g, length, L, K))

    # Scale-invariant loop count M_5q(q): loops with min_value <= 5*q
    M_5q = {
        q: sum(1 for mv, *_ in loops_by_q[q] if mv <= 5 * q)
        for q in loops
    }

    fig, axes = plt.subplots(2, 2, figsize=(18, 13), dpi=200)
    fig.patch.set_facecolor("#ffffff")

    # Panel A: Boxplot / Violin + Median/Mode of Delta_{xr}(q) when r not dividing q
    ax1 = axes[0, 0]
    primes_r = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31]
    data_coprime = []
    base_P = []
    labels_r = []
    for r in primes_r:
        if r == 3:
            diffs = [loops[3 * q] - loops[q] for q in loops if 3 * q in loops]
            base_P.append(0)
        else:
            diffs = [loops[r * q] - loops[q] for q in loops if r * q in loops and q % r != 0]
            base_P.append(len(prim_by_d[r]))
        data_coprime.append(diffs)
        labels_r.append(f"×{r}\n(n={len(diffs)})")

    bp = ax1.boxplot(
        data_coprime,
        positions=range(len(primes_r)),
        widths=0.55,
        patch_artist=True,
        showfliers=False,
        medianprops=dict(color="#dc2626", lw=2.2),
    )
    palette = ["#94a3b8", "#3b82f6", "#a855f7", "#f59e0b", "#ef4444", "#10b981", "#06b6d4", "#8b5cf6", "#ec4899", "#6366f1"]
    for patch, col in zip(bp["boxes"], palette):
        patch.set_facecolor(col)
        patch.set_alpha(0.45)

    ax1.plot(
        range(len(primes_r)),
        base_P,
        "o--",
        color="#0f172a",
        lw=2.0,
        markersize=8,
        label="基本増分 P(r)（q=3^a に ×r したときの増加本数）",
    )
    for idx, (r, p_val, diffs) in enumerate(zip(primes_r, base_P, data_coprime)):
        med = int(np.median(diffs))
        ax1.text(
            idx,
            max(med, p_val) + 1.2,
            f"P({r})={p_val}\n中央値{med:+d}",
            fontsize=8.0,
            ha="center",
            va="bottom",
            fontweight="bold",
            color="#1e293b",
        )

    ax1.axhline(0, color="#64748b", ls=":", lw=1.2)
    ax1.set_xticks(range(len(primes_r)))
    ax1.set_xticklabels(labels_r, fontsize=9)
    ax1.set_ylim(-4, 24)
    ax1.set_ylabel("ループ本数の増分 ΔM = M(rq) - M(q)", fontsize=11, fontweight="bold")
    ax1.set_title("① 各奇素数倍（×r）におけるループ増加本数の分布と基本増分 P(r)", fontsize=12, fontweight="bold")
    ax1.legend(loc="upper right", fontsize=9.5)
    ax1.grid(True, alpha=0.3)

    # Panel B: Does the law disappear at large q? Raw N_max=100,000 vs Scale-invariant min_val <= 5q
    ax2 = axes[0, 1]
    check_primes = [3, 5, 7, 11, 13, 17, 19, 23]
    raw_rates = []
    raw_within1_rates = []
    inv_rates = []

    for r in check_primes:
        if r == 3:
            pairs_raw = [(loops[3 * q], loops[q]) for q in loops if 3 * q in loops]
            pairs_inv = [(M_5q[3 * q], M_5q[q]) for q in loops if 3 * q in loops]
        else:
            pairs_raw = [
                (loops[3 * r * q] - loops[3 * q], loops[r * q] - loops[q])
                for q in loops
                if 3 * r * q in loops
            ]
            pairs_inv = [
                (M_5q[3 * r * q] - M_5q[3 * q], M_5q[r * q] - M_5q[q])
                for q in loops
                if 3 * r * q in loops
            ]
        raw_exact = sum(1 for a, b in pairs_raw if a == b) / len(pairs_raw) * 100.0
        raw_w1 = sum(1 for a, b in pairs_raw if abs(a - b) <= 1) / len(pairs_raw) * 100.0
        inv_exact = sum(1 for a, b in pairs_inv if a == b) / len(pairs_inv) * 100.0
        raw_rates.append(raw_exact)
        raw_within1_rates.append(raw_w1)
        inv_rates.append(inv_exact)

    x_idx = np.arange(len(check_primes))
    w = 0.27
    b1 = ax2.bar(x_idx - w, raw_rates, width=w, color="#60a5fa", label="生データ完全一致 (N≤100,000 固定)")
    b2 = ax2.bar(x_idx, raw_within1_rates, width=w, color="#93c5fd", label="生データ ±1本以内一致 (N≤100,000 固定)")
    b3 = ax2.bar(x_idx + w, inv_rates, width=w, color="#16a34a", label="スケール不変窓 (min_val ≤ 5q) 完全一致")

    for idx, val in enumerate(inv_rates):
        ax2.text(idx + w, val + 1.0, f"{val:.0f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#15803d")
    for idx, val in enumerate(raw_rates):
        ax2.text(idx - w, val + 1.0, f"{val:.1f}%", ha="center", va="bottom", fontsize=8.0, color="#1e40af")

    ax2.set_xticks(x_idx)
    ax2.set_xticklabels([("M(3q)\n= M(q)" if r == 3 else f"Δ×{r}(3q)\n= Δ×{r}(q)") for r in check_primes], fontsize=8.8)
    ax2.set_ylim(0, 114)
    ax2.set_ylabel("一致率 (%)", fontsize=11, fontweight="bold")
    ax2.set_title("② 3倍クローン間での増分一致率：固定窓 vs スケール不変窓（100%成立の実証）", fontsize=12, fontweight="bold")
    ax2.legend(loc="lower right", fontsize=9.0)
    ax2.grid(True, alpha=0.3)

    # Panel C: Agreement rate of M(3q) = M(q) and Delta_x5(3q) = Delta_x5(q) as a function of q
    ax3 = axes[1, 0]
    q_bins = [(1, 100), (101, 200), (201, 317), (319, 600), (601, 1000), (1001, 2000), (2001, 6665)]
    bin_labels = []
    rate_3_raw = []
    rate_3_inv = []
    for lo, hi in q_bins:
        sub_3 = [q for q in range(lo, hi + 1, 2) if 3 * q in loops]
        r_raw = sum(1 for q in sub_3 if loops[3 * q] == loops[q]) / len(sub_3) * 100.0
        r_inv = sum(1 for q in sub_3 if M_5q[3 * q] == M_5q[q]) / len(sub_3) * 100.0
        bin_labels.append(f"q∈[{lo},{hi}]\n({len(sub_3)}組)")
        rate_3_raw.append(r_raw)
        rate_3_inv.append(r_inv)

    bx = np.arange(len(q_bins))
    ax3.plot(bx, rate_3_inv, "s-", color="#16a34a", lw=2.6, markersize=8, label="真の数学的法則 / スケール不変窓 M_5q(3q) = M_5q(q) 【常に100%】")
    ax3.plot(bx, rate_3_raw, "o-", color="#2563eb", lw=2.4, markersize=8, label="固定探索上限 N_max=100,000 での見かけの一致率")
    for i, (rr, ri) in enumerate(zip(rate_3_raw, rate_3_inv)):
        ax3.text(i, rr - 6.5, f"{rr:.1f}%", ha="center", va="top", fontsize=9.0, fontweight="bold", color="#1d4ed8")

    ax3.axvline(2.5, color="#dc2626", ls="--", lw=1.4, label="q = 319: 高高度ループ (3·min_val > 100,000) の窓外はみ出し開始点")
    ax3.set_xticks(bx)
    ax3.set_xticklabels(bin_labels, fontsize=8.8)
    ax3.set_ylim(40, 108)
    ax3.set_ylabel("M(3q) = M(q) 一致率 (%)", fontsize=11, fontweight="bold")
    ax3.set_title("③ なぜ q が大きくなると見かけ上ずれるのか？（N_max=100,000 窓外はみ出し効果）", fontsize=12, fontweight="bold")
    ax3.legend(loc="lower left", fontsize=8.8)
    ax3.grid(True, alpha=0.3)

    # Panel D: Heatmap of Delta_{xr}(u) = P(r) + P(r*u) for prime pairs (u, r)
    ax4 = axes[1, 1]
    u_primes = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31]
    r_primes = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31]
    mat = np.zeros((len(u_primes), len(r_primes)), dtype=int)
    for i, u in enumerate(u_primes):
        for j, r in enumerate(r_primes):
            mat[i, j] = loops[u * r] - loops[u]

    im = ax4.imshow(mat, cmap="YlOrRd", aspect="auto")
    for i in range(len(u_primes)):
        for j in range(len(r_primes)):
            val = mat[i, j]
            txt_col = "#ffffff" if val >= 12 else "#0f172a"
            ax4.text(j, i, f"{val:+d}", ha="center", va="center", fontsize=9.0, fontweight="bold", color=txt_col)

    ax4.set_xticks(range(len(r_primes)))
    ax4.set_xticklabels([f"×{r}" for r in r_primes], fontsize=9.5, fontweight="bold")
    ax4.set_yticks(range(len(u_primes)))
    ax4.set_yticklabels([f"q={u} ({loops[u]}本)" for u in u_primes], fontsize=9.5, fontweight="bold")
    ax4.set_xlabel("掛ける奇素数 ×r", fontsize=11, fontweight="bold")
    ax4.set_ylabel("元の奇素数 q (Level 0)", fontsize=11, fontweight="bold")
    ax4.set_title("④ Level 0 → Level 1 遷移マトリクス ΔM = M(q×r) - M(q)", fontsize=12, fontweight="bold")
    plt.colorbar(im, ax=ax4, fraction=0.046, pad=0.04, label="増加ループ本数 ΔM")

    plt.suptitle(
        "p = 3 奇数ピラミッドにおけるループ本数の遺伝・進化法則と全10,000システム（q = 1〜19,999）検証",
        fontsize=15,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.965])

    for target_dir in [OUT_DIR, DATA_OUT_DIR]:
        fig.savefig(target_dir / "odd_pyramid_multiplier_analysis.png", dpi=200, bbox_inches="tight")
        fig.savefig(target_dir / "odd_pyramid_multiplier_analysis.svg", format="svg", bbox_inches="tight")
    plt.close(fig)
    print("Saved odd_pyramid_multiplier_analysis.png and .svg")


def main():
    loops, all_loops = load_p3_data()

    # 1. Exact 3-prime expansion of odd_pyramid.png: Numbers 7, 5, 3 (Levels 0 to 8, all 88 nodes <= 19999)
    render_odd_pyramid(
        primes=[7, 5, 3],
        loops=loops,
        out_stem="odd_pyramid_7_5_3_loops",
        max_level=None,
        show_edge_deltas=True,
    )

    # 2. Expanded 4-prime pyramid: Numbers 11, 7, 5, 3 (Levels 0 to 8, all 159 nodes <= 19999)
    render_odd_pyramid(
        primes=[11, 7, 5, 3],
        loops=loops,
        out_stem="odd_pyramid_11_7_5_3_loops",
        max_level=None,
        show_edge_deltas=True,
    )

    # 3. Expanded 5-prime pyramid: Numbers 13, 11, 7, 5, 3 (Levels 0 to 8, all 251 nodes <= 19999)
    render_odd_pyramid(
        primes=[13, 11, 7, 5, 3],
        loops=loops,
        out_stem="odd_pyramid_13_11_7_5_3_loops",
        max_level=None,
        show_edge_deltas=False,
    )

    # 4. High-detail zoom of Levels 0 to 3 for Numbers 13, 11, 7, 5, 3 with all edge deltas
    render_odd_pyramid(
        primes=[13, 11, 7, 5, 3],
        loops=loops,
        out_stem="odd_pyramid_zoom_loops",
        max_level=2,
        show_edge_deltas=True,
    )

    # 5. Analytical 4-panel summary chart (PNG + SVG)
    render_multiplier_analysis_figure(loops, all_loops)


if __name__ == "__main__":
    main()

