#!/usr/bin/env python3
"""
Generate high-resolution PNG and SVG diagrams illustrating:
1. ctree_odd_skeleton_comparison.{png,svg}:
   - Full CTree vs Odd-Skeleton Tree (contracting *2^k even chains)
   - Side-by-side comparison of the twin length-8 loops of p=3, q=5:
     Loop 19 (49.58% share, sprouts h=1 rootlet 38 -> 11) vs
     Loop 23 (9.29% share, sealed at h=1, first odd branches at h=3: 97, 121, 153)
2. ctree_whole_tree_laws.{png,svg}:
   - 4-panel visual proof of the Three Whole-Tree Laws across the p=3 dataset:
     (A) Complete CTree freezing along *5, *7, *11 vs Fibonacci saturation along *3^a
     (B) Euler's Totient Law Share(Layer d) = phi(d) / m across composite systems
     (C) Twin-loop territory race (Loop 19 vs Loop 23 cumulative nodes vs altitude N)
     (D) Height spectrum N(h) & Sea-level boundary (n = q) effect
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = Path("docs/2026_1105")
DATA_OUT_DIR = Path("data/p3")
DB_PATH = Path("data/p3/summary_p3.db")


def build_full_ctree(q: int, root_loop: list[int], max_h: int = 8):
    """Build full CTree up to height max_h from root_loop for p=3."""
    visited = set(root_loop)
    nodes = {}
    children = defaultdict(list)

    for idx, n in enumerate(root_loop):
        nodes[n] = {"n": n, "h": 0, "is_loop": True, "is_odd": (n % 2 == 1), "order": idx}

    frontier = list(root_loop)
    for h in range(1, max_h + 1):
        nxt = []
        for x in frontier:
            # Even preimage: 2*x
            ev = 2 * x
            if ev not in visited:
                visited.add(ev)
                nodes[ev] = {"n": ev, "h": h, "is_loop": False, "is_odd": False, "parent": x, "branch_type": "even"}
                children[x].append(ev)
                nxt.append(ev)
            # Odd preimage: (x - q) / 3
            if x > q and (x - q) % 3 == 0:
                od = (x - q) // 3
                if od % 2 == 1 and od not in visited:
                    visited.add(od)
                    nodes[od] = {"n": od, "h": h, "is_loop": False, "is_odd": True, "parent": x, "branch_type": "odd"}
                    children[x].append(od)
                    nxt.append(od)
        frontier = nxt
    return nodes, children


def build_odd_skeleton_tree(q: int, root_loop: list[int], max_odd_depth: int = 3, max_k: int = 4):
    """
    Contract all *2^k even chains so only the odd branching nodes remain!
    Also compute exact full-CTree height h_full for every odd node.
    """
    full_nodes, _ = build_full_ctree(q, root_loop, max_h=16)
    odd_loop = [x for x in root_loop if x % 2 == 1]
    visited_odd = set(odd_loop)
    nodes = {}
    edges = []  # (u, v, k_doublings, via_even, h_full)

    for idx, u in enumerate(odd_loop):
        nodes[u] = {"n": u, "depth": 0, "is_loop": True, "order": idx, "h_full": 0}

    frontier = list(odd_loop)
    for d in range(1, max_odd_depth + 1):
        nxt = []
        for u in frontier:
            for k in range(1, max_k + 1):
                even_val = u * (1 << k)
                if even_val > q and (even_val - q) % 3 == 0:
                    v = (even_val - q) // 3
                    if v % 2 == 1 and v not in visited_odd:
                        visited_odd.add(v)
                        h_new = full_nodes[v]["h"] if v in full_nodes else (nodes[u]["h_full"] + k + 1)
                        nodes[v] = {
                            "n": v,
                            "depth": d,
                            "is_loop": False,
                            "h_full": h_new,
                            "via_k": k,
                            "via_even": even_val,
                        }
                        edges.append((u, v, k, even_val, h_new))
                        nxt.append(v)
        frontier = nxt
    return odd_loop, nodes, edges


def layout_hierarchical_tree(roots: list[int], children_map: dict[int, list[int]]):
    """Assign (x, y) coordinates via post-order leaf counting."""
    leaf_cursor = [0.0]
    pos = {}

    def dfs(u: int, depth: int) -> float:
        ch = children_map.get(u, [])
        if not ch:
            x = leaf_cursor[0]
            leaf_cursor[0] += 1.0
        else:
            xs = [dfs(v, depth + 1) for v in ch]
            x = 0.5 * (xs[0] + xs[-1])
        pos[u] = (x, float(depth))
        return x

    for r in roots:
        dfs(r, 0)
        leaf_cursor[0] += 0.6

    return pos


def render_skeleton_and_twins_figure():
    """
    Create a 2x2 showcase figure:
    Top-Left:  q=5 Loop 19 (49.6% share) Full CTree (h <= 6)
    Top-Right: q=5 Loop 23 ( 9.3% share) Full CTree (h <= 6)
    Bottom-Left:  q=5 Loop 19 Odd-Skeleton Tree (奇数骨格木: *2^k 直線を縮約し奇数分岐点のみ抽出)
    Bottom-Right: q=5 Loop 23 Odd-Skeleton Tree (奇数骨格木: 初段 h=1 封印と h=3 高高度分岐の対比)
    """
    loop19 = [19, 62, 31, 98, 49, 152, 76, 38]
    loop23 = [23, 74, 37, 116, 58, 29, 92, 46]

    fig, axes = plt.subplots(2, 2, figsize=(20, 14), dpi=200)
    fig.patch.set_facecolor("#ffffff")

    # --- Top Row: Full CTree up to h=6 for Loop 19 and Loop 23 ---
    for col_idx, (loop, name, share_str, accent_col) in enumerate([
        (loop19, "双子A：ループ19 [min=19, 周期8]", "吸引シェア 49.58% (49,575 / 100,000)", "#1d4ed8"),
        (loop23, "双子B：ループ23 [min=23, 周期8]", "吸引シェア  9.29% ( 9,286 / 100,000)", "#7c3aed"),
    ]):
        ax = axes[0, col_idx]
        nodes, children = build_full_ctree(5, loop, max_h=6)
        pos = layout_hierarchical_tree(loop, children)

        # Draw edges
        for u, ch_list in children.items():
            x1, y1 = pos[u]
            for v in ch_list:
                x2, y2 = pos[v]
                is_odd_branch = nodes[v]["is_odd"]
                ec = "#dc2626" if is_odd_branch else "#94a3b8"
                ls = "-" if is_odd_branch else ":"
                lw = 2.0 if is_odd_branch else 1.0
                ax.plot([x1, x2], [y1, y2], color=ec, ls=ls, lw=lw, zorder=1)

        # Spine connecting loop elements at h=0
        for i in range(len(loop) - 1):
            x1, y1 = pos[loop[i]]
            x2, y2 = pos[loop[i + 1]]
            ax.plot([x1, x2], [y1, y2], color="#0f172a", ls="--", lw=1.8, alpha=0.6, zorder=1)

        # Draw nodes
        for n_val, info in nodes.items():
            x, y = pos[n_val]
            if info["is_loop"]:
                fc = "#0f172a" if info["is_odd"] else "#475569"
                tc = "#ffffff"
                sz = 190
            elif info["is_odd"]:
                fc = "#dc2626"
                tc = "#991b1b"
                sz = 145
            else:
                fc = "#cbd5e1"
                tc = "#64748b"
                sz = 55

            ax.scatter([x], [y], s=sz, color=fc, edgecolors="#ffffff", linewidth=1.0, zorder=3)
            if info["is_loop"] or info["is_odd"] or info["h"] <= 2:
                fs = 8.2 if (info["is_loop"] or info["is_odd"]) else 6.8
                fw = "bold" if (info["is_loop"] or info["is_odd"]) else "normal"
                ax.text(
                    x,
                    y + (0.23 if not info["is_loop"] else -0.32),
                    f"{n_val}",
                    fontsize=fs,
                    fontweight=fw,
                    color=("#dc2626" if (info["is_odd"] and not info["is_loop"]) else "#0f172a"),
                    ha="center",
                    va="center",
                    bbox=dict(boxstyle="round,pad=0.1", facecolor="#ffffff", edgecolor="none", alpha=0.8) if info["is_odd"] else None,
                    zorder=4,
                )

        # Highlight h=1 rootlet on Loop 19 vs sealed h=1 on Loop 23
        if col_idx == 0:
            x11, y11 = pos[11]
            ax.annotate(
                "★ 初段 h=1 発根！\n38 → 11 = (38-5)/3\n低い奇数領域を一気に独占",
                xy=(x11, y11),
                xytext=(x11 - 6.0, y11 + 1.8),
                arrowprops=dict(arrowstyle="->", color="#dc2626", lw=2.0),
                fontsize=9.5,
                fontweight="bold",
                color="#b91c1c",
                bbox=dict(boxstyle="round,pad=0.35", facecolor="#fef2f2", edgecolor="#dc2626", lw=1.5),
                zorder=5,
            )
        else:
            x58, y58 = pos[58]
            ax.annotate(
                "× 初段 h=1・h=2 完全封印！\n空き偶数 58, 46 は mod 3 = 1 のため\nh=3 (97, 121, 153) まで奇数枝が出ない",
                xy=(x58, y58 + 0.5),
                xytext=(x58 - 7.5, y58 + 2.2),
                arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=2.0),
                fontsize=9.5,
                fontweight="bold",
                color="#5b21b6",
                bbox=dict(boxstyle="round,pad=0.35", facecolor="#f5f3ff", edgecolor="#7c3aed", lw=1.5),
                zorder=5,
            )

        ax.set_yticks(range(0, 7))
        ax.set_yticklabels([f"h={h}" for h in range(0, 7)], fontsize=9, fontweight="bold")
        ax.set_ylim(-0.7, 6.7)
        ax.set_xticks([])
        ax.grid(axis="y", color="#f1f5f9", lw=1.0)
        ax.set_title(
            f"【通常の CTree (h≤6)】{name} — {share_str}\n"
            f"（黒/灰: ループ要素, 赤丸: 奇数分岐ノード, 小灰丸: 2倍直線の偶数ノード — 全 {len(nodes)} ノード）",
            fontsize=11.0,
            fontweight="bold",
            color=accent_col,
        )

    # --- Bottom Row: Odd-Skeleton Tree (奇数骨格木) for Loop 19 and Loop 23 ---
    for col_idx, (loop, name, accent_col) in enumerate([
        (loop19, "双子A：ループ19 の「奇数骨格木 (Odd-Skeleton Tree)」", "#1d4ed8"),
        (loop23, "双子B：ループ23 の「奇数骨格木 (Odd-Skeleton Tree)」", "#7c3aed"),
    ]):
        ax = axes[1, col_idx]
        odd_roots, sk_nodes, sk_edges = build_odd_skeleton_tree(5, loop, max_odd_depth=3, max_k=4)
        sk_children = defaultdict(list)
        edge_info = {}
        for u, v, k, even_val, h_new in sk_edges:
            sk_children[u].append(v)
            edge_info[(u, v)] = (k, even_val, h_new)

        pos = layout_hierarchical_tree(odd_roots, sk_children)

        # Draw contracted edges
        for (u, v), (k, even_val, h_new) in edge_info.items():
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            col = "#dc2626" if h_new <= 2 else ("#2563eb" if h_new <= 4 else "#64748b")
            lw = 2.4 if h_new <= 2 else 1.5
            ax.plot([x1, x2], [y1, y2], color=col, lw=lw, alpha=0.8, zorder=1)
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            ax.text(
                mx,
                my,
                f"×2^{k}" if k > 1 else "×2",
                fontsize=7.2,
                color=col,
                ha="center",
                va="center",
                bbox=dict(boxstyle="round,pad=0.08", facecolor="#ffffff", edgecolor="none", alpha=0.85),
                zorder=2,
            )

        # Spine connecting odd loop roots
        for i in range(len(odd_roots) - 1):
            x1, y1 = pos[odd_roots[i]]
            x2, y2 = pos[odd_roots[i + 1]]
            ax.plot([x1, x2], [y1, y2], color="#0f172a", ls="--", lw=2.0, alpha=0.7, zorder=1)

        # Draw odd nodes with their value and original height h
        for n_val, info in sk_nodes.items():
            x, y = pos[n_val]
            d = info["depth"]
            h_f = info["h_full"]
            if info["is_loop"]:
                fc = "#0f172a"
                ec = "#0f172a"
                tc = "#ffffff"
                r_sz = 340
            elif h_f <= 2:
                fc = "#fef2f2"
                ec = "#dc2626"
                tc = "#991b1b"
                r_sz = 300
            elif n_val <= 50:
                fc = "#eff6ff"
                ec = "#2563eb"
                tc = "#1e40af"
                r_sz = 260
            else:
                fc = "#f8fafc"
                ec = "#475569"
                tc = "#0f172a"
                r_sz = 230

            ax.scatter([x], [y], s=r_sz * 1.45, facecolor=fc, edgecolor=ec, linewidth=2.2, zorder=3)
            ax.text(
                x,
                y,
                f"{n_val}",
                fontsize=8.8 if not info["is_loop"] else 9.2,
                fontweight="bold",
                color=tc,
                ha="center",
                va="center",
                zorder=4,
            )
            sub_lbl = f"h={h_f}" if not info["is_loop"] else "ループ根"
            ax.text(
                x,
                y - 0.23,
                sub_lbl,
                fontsize=7.4,
                fontweight="bold",
                color=ec if not info["is_loop"] else "#334155",
                ha="center",
                va="center",
                bbox=dict(boxstyle="round,pad=0.08", facecolor="#ffffff", edgecolor="none", alpha=0.85),
                zorder=4,
            )

        ax.set_yticks([0, 1, 2, 3])
        ax.set_yticklabels(["奇数世代 0\n(ループ内奇数)", "奇数世代 1\n(第1分岐)", "奇数世代 2\n(第2分岐)", "奇数世代 3\n(第3分岐)"], fontsize=9.5, fontweight="bold")
        ax.set_ylim(-0.45, 3.45)
        ax.set_xticks([])
        ax.grid(axis="y", color="#f1f5f9", lw=1.0)
        ax.set_title(
            f"【提案①：奇数骨格木】{name}\n"
            f"（偶数の ×2^k 直線を1本のエッジに縮約し、分岐点である奇数ノード {len(sk_nodes)} 個だけを抽出した骨格構造）",
            fontsize=11.0,
            fontweight="bold",
            color=accent_col,
        )

    plt.suptitle(
        "p = 3, q = 5 における「通常の CTree」と「奇数骨格木（Odd-Skeleton Tree）」の比較：なぜ双子ループ (19 vs 23) で5.3倍の格差がつくのか？",
        fontsize=14.5,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.965])

    for target_dir in [OUT_DIR, DATA_OUT_DIR]:
        target_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(target_dir / "ctree_odd_skeleton_comparison.png", dpi=200, bbox_inches="tight")
        fig.savefig(target_dir / "ctree_odd_skeleton_comparison.svg", format="svg", bbox_inches="tight")
    plt.close(fig)
    print("Saved ctree_odd_skeleton_comparison.png and .svg")


def ctree_profile(q: int, root_loop: list[int], max_h: int = 12) -> list[int]:
    visited = set(root_loop)
    frontier = set(root_loop)
    prof = [len(root_loop)]
    for _ in range(1, max_h + 1):
        nxt = set()
        for x in frontier:
            if (2 * x) not in visited:
                nxt.add(2 * x)
            if x > q and (x - q) % 3 == 0:
                op = (x - q) // 3
                if op % 2 == 1 and op not in visited:
                    nxt.add(op)
        visited |= nxt
        frontier = nxt
        prof.append(len(nxt))
    return prof


def render_whole_tree_laws_figure():
    """
    Create a 2x2 figure demonstrating the Three Whole-Tree Laws and the Twin Territory Race.
    """
    fig, axes = plt.subplots(2, 2, figsize=(19, 13.5), dpi=200)
    fig.patch.set_facecolor("#ffffff")

    # Panel A: Law 1 & Law 2 — CTree Height Spectrum N(h): Freezing under *5,*7,*11 vs Fibonacci Saturation under *3^a
    ax1 = axes[0, 0]
    hs = np.arange(0, 11)
    prof_coprime = ctree_profile(1, [1, 4, 2], max_h=10)
    ax1.plot(
        hs,
        prof_coprime,
        "o-",
        color="#0f172a",
        lw=3.0,
        markersize=8,
        label="q = 1, 5, 7, 11, 25, 35, 385 (×5,×7,×11 クローン木: 全7システムが100%完全重畳！)",
        zorder=5,
    )

    colors_3a = ["#3b82f6", "#8b5cf6", "#ec4899", "#ef4444"]
    for idx, a in enumerate([1, 2, 3, 4]):
        q_val = 3 ** a
        prof_a = ctree_profile(q_val, [q_val, 4 * q_val, 2 * q_val], max_h=10)
        lbl = f"q = 3^{a} = {q_val} (h ≤ {2*a+1} までフィボナッチ飽和完了)" if a < 4 else f"q = 3^4 = 81, 243, 729... (飽和極限木: 3,2,3,4,7,11,17,27,42,68,108)"
        ax1.plot(hs, prof_a, "s--", color=colors_3a[idx], lw=2.0, markersize=6.5, label=lbl)

    for h_i, val in enumerate(ctree_profile(81, [81, 324, 162], max_h=10)):
        if h_i >= 1:
            ax1.text(h_i, val + 3.0, f"{val}", fontsize=8.5, fontweight="bold", color="#b91c1c", ha="center")
    for h_i, val in enumerate(prof_coprime):
        ax1.text(h_i, max(0, val - 6.5), f"{val}", fontsize=8.0, fontweight="bold", color="#0f172a", ha="center")

    ax1.set_xticks(hs)
    ax1.set_xticklabels([f"h={h}" for h in hs], fontsize=9.5)
    ax1.set_ylim(-8, 122)
    ax1.set_ylabel("高さ h のノード数 N(h)", fontsize=11, fontweight="bold")
    ax1.set_title("① 木全体の高さスペクトル N(h)：×r (r≠3) の完全凍結と ×3^a のフィボナッチ飽和", fontsize=11.8, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=8.8)
    ax1.grid(True, alpha=0.3)

    # Panel B: Law 3 — Euler's Totient Law Share(Layer d) = phi(d) / m
    ax2 = axes[0, 1]
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    showcase_qs = [5, 7, 15, 25, 35, 55, 125, 175, 385]
    bar_x = np.arange(len(showcase_qs))
    # Collect shares by divisor d for each q
    all_ds = sorted({1, 5, 7, 11, 25, 35, 55, 77, 125, 175, 385})
    d_colors = {
        1: "#94a3b8",
        5: "#3b82f6",
        7: "#a855f7",
        11: "#f59e0b",
        25: "#1d4ed8",
        35: "#10b981",
        55: "#ec4899",
        77: "#06b6d4",
        125: "#1e3a8a",
        175: "#047857",
        385: "#dc2626",
    }

    bottoms = np.zeros(len(showcase_qs))
    used_ds = set()
    layer_data_by_q = {}
    for q_idx, q_val in enumerate(showcase_qs):
        cur.execute(
            """
            SELECT l.min_value, l.basin_share
            FROM loops l JOIN systems s ON l.system_id = s.system_id
            WHERE s.q1 = ?
            """,
            (q_val,),
        )
        m = q_val
        while m % 3 == 0:
            m //= 3
        by_d = defaultdict(float)
        for mv, bs in cur.fetchall():
            g = math.gcd(mv, m)
            d = m // g
            by_d[d] += bs * 100.0
        layer_data_by_q[q_val] = by_d
        used_ds.update(by_d.keys())

    for d in sorted(used_ds):
        vals = [layer_data_by_q[q_val].get(d, 0.0) for q_val in showcase_qs]
        ax2.bar(
            bar_x,
            vals,
            bottom=bottoms,
            width=0.58,
            color=d_colors.get(d, "#64748b"),
            edgecolor="#ffffff",
            linewidth=1.0,
            label=f"d={d} 層 (φ({d})={sum(1 for k in range(1, d+1) if math.gcd(k, d)==1)})",
        )
        for q_idx, v in enumerate(vals):
            if v >= 7.0:
                ax2.text(
                    q_idx,
                    bottoms[q_idx] + v / 2.0,
                    f"d={d}\n{v:.1f}%",
                    ha="center",
                    va="center",
                    fontsize=7.8,
                    fontweight="bold",
                    color="#ffffff" if d in (25, 125, 175, 385, 5, 7) else "#0f172a",
                )
        bottoms += np.array(vals)

    ax2.set_xticks(bar_x)
    ax2.set_xticklabels([f"q={q}\n({loops_count}本)" for q, loops_count in [(q, sum(1 for _ in layer_data_by_q[q])) for q in showcase_qs]], fontsize=9.0)
    # Fix label to show total loops of q
    cur.execute("SELECT q1, num_loops FROM systems WHERE q1 IN (5,7,15,25,35,55,125,175,385)")
    nl_map = dict(cur.fetchall())
    ax2.set_xticklabels([f"q={q}\n({nl_map[q]}本)" for q in showcase_qs], fontsize=9.0, fontweight="bold")
    ax2.set_ylim(0, 108)
    ax2.set_ylabel("吸引域シェア (%) = φ(d) / core_3(q)", fontsize=11, fontweight="bold")
    ax2.set_title("② 森全体の勢力図：オイラーの φ 関数則 Share(Layer d) = φ(d)/m（全10,000系で誤差 0.0004%）", fontsize=11.8, fontweight="bold")
    ax2.legend(loc="upper right", ncol=3, fontsize=7.8)
    ax2.grid(axis="y", alpha=0.3)

    # Panel C: Twin Loops Territory Race across Altitude N (Loop 19 vs Loop 23 in q=5)
    ax3 = axes[1, 0]
    loop19 = [19, 62, 31, 98, 49, 152, 76, 38]
    loop23 = [23, 74, 37, 116, 58, 29, 92, 46]
    nodes19, _ = build_full_ctree(5, loop19, max_h=22)
    nodes23, _ = build_full_ctree(5, loop23, max_h=22)
    vals19 = sorted(nodes19.keys())
    vals23 = sorted(nodes23.keys())

    thresholds = np.logspace(1, 5, 60)
    c19 = [np.searchsorted(vals19, t, side="right") for t in thresholds]
    c23 = [np.searchsorted(vals23, t, side="right") for t in thresholds]

    ax3.plot(thresholds, c19, "-", color="#1d4ed8", lw=2.8, label="双子A：ループ19 (h=1 で 38→11 に発根、シェア 49.58%)")
    ax3.plot(thresholds, c23, "-", color="#7c3aed", lw=2.8, label="双子B：ループ23 (h=1,2 封印、h=3 で 97,121,153 に発根、シェア 9.29%)")
    ax3.axvline(11, color="#dc2626", ls="--", lw=1.5, label="n = 11: ループ19 の初段根っこ (h=1)")
    ax3.axvline(97, color="#7c3aed", ls=":", lw=1.5, label="n = 97: ループ23 の最初の奇数枝 (h=3)")

    ax3.set_xscale("log")
    ax3.set_yscale("log")
    ax3.set_xlabel("数値の上限 X (対数スケール)", fontsize=11, fontweight="bold")
    ax3.set_ylabel("CTree (h≤22) 内で X 以下のノード数 (対数)", fontsize=11, fontweight="bold")
    ax3.set_title("③ 双子ループ（19 vs 23）の領土獲得レース：初段発根 (n=11) が生む5.3倍の恒久的リード", fontsize=11.8, fontweight="bold")
    ax3.legend(loc="upper left", fontsize=8.8)
    ax3.grid(True, which="both", alpha=0.3)

    # Panel D: Sea-Level Boundary (n = q) on Log-N Height Plot for q = 27 vs q = 25
    ax4 = axes[1, 1]
    nodes_q27, _ = build_full_ctree(27, [27, 108, 54], max_h=12)
    below_x = [n for n, info in nodes_q27.items() if n <= 27]
    below_y = [info["h"] for n, info in nodes_q27.items() if n <= 27]
    above_even_x = [n for n, info in nodes_q27.items() if n > 27 and not info["is_odd"]]
    above_even_y = [info["h"] for n, info in nodes_q27.items() if n > 27 and not info["is_odd"]]
    above_odd_x = [n for n, info in nodes_q27.items() if n > 27 and info["is_odd"]]
    above_odd_y = [info["h"] for n, info in nodes_q27.items() if n > 27 and info["is_odd"]]

    ax4.scatter(above_even_x, above_even_y, s=22, color="#94a3b8", alpha=0.65, label="海面上の偶数ノード (x > q: 次の奇数枝の母体)")
    ax4.scatter(above_odd_x, above_odd_y, s=55, color="#dc2626", alpha=0.9, label="海面上の奇数分岐ノード (x > q から (x-q)/3 で発根)")
    ax4.scatter(below_x, below_y, s=65, color="#0284c7", marker="D", label="海面下のノード (x ≤ q: (x-q)/3 ≤ 0 のため奇数分岐が封印される領域)")

    ax4.axvline(27, color="#0f172a", ls="--", lw=2.2, label="【海面ライン】 (x = q = 27)")
    ax4.axvspan(0.8, 27, color="#e0f2fe", alpha=0.35)
    ax4.text(
        4.5,
        10.5,
        "【海面下ゾーン (x ≤ q)】\n(x - q)/3 ≤ 0 となるため\nここから新しい奇数枝は\n1本も生えない（×2のみ）",
        fontsize=9.5,
        fontweight="bold",
        color="#0369a1",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#ffffff", edgecolor="#0284c7", lw=1.3),
    )
    ax4.text(
        180,
        2.2,
        "【地上繁殖ゾーン (x > q)】\n偶数 6k ごとに (x-q)/3 > 0 の\n奇数枝がフィボナッチ的に誕生",
        fontsize=9.5,
        fontweight="bold",
        color="#b91c1c",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fef2f2", edgecolor="#dc2626", lw=1.3),
    )

    ax4.set_xscale("log")
    ax4.set_xlim(0.8, 150000)
    ax4.set_ylim(-0.5, 12.8)
    ax4.set_xlabel("ノード値 x (対数スケール Log x)", fontsize=11, fontweight="bold")
    ax4.set_ylabel("CTree 高さ h", fontsize=11, fontweight="bold")
    ax4.set_title("④ 提案④：海面ライン (x = q) による「地下吸い込み口 (x≤q)」と「地上繁殖領域 (x>q)」の分離", fontsize=11.8, fontweight="bold")
    ax4.legend(loc="upper right", fontsize=8.5)
    ax4.grid(True, which="both", alpha=0.3)

    conn.close()

    plt.suptitle(
        "CTree（木全体）を貫く3大法則と、巨大な木を構造的に観察するための4つの視点",
        fontsize=15,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.965])

    for target_dir in [OUT_DIR, DATA_OUT_DIR]:
        fig.savefig(target_dir / "ctree_whole_tree_laws.png", dpi=200, bbox_inches="tight")
        fig.savefig(target_dir / "ctree_whole_tree_laws.svg", format="svg", bbox_inches="tight")
    plt.close(fig)
    print("Saved ctree_whole_tree_laws.png and .svg")


if __name__ == "__main__":
    render_skeleton_and_twins_figure()
    render_whole_tree_laws_figure()
