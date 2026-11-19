"""
Dark-Field Snow Crystal Growth Engine & Animated GIF Renderer for (p, Q) CTree.

Inspired by Ukichiro Nakaya's scientific films of snow crystal growth under dark-field
illumination: as generation k advances along a clone multiplier g^k (e.g. *3^k for p=3,
*2^k for p=4, *5^k for p=5, *6^k / *2^k / *3^k for p=6), the inner levels near the loop
freeze into a permanent Fibonacci crystal while new branches nucleate at the crystallization
front.
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

from backend.engine import CollatzPQEngine


def default_clone_multiplier(p: int) -> int:
    if p == 4:
        return 2
    return p


def permute_q_by_multiplier(p: int, q_base: List[Optional[int]], mult: int) -> List[Optional[int]]:
    """
    When scaling n -> mult * n in T_{p, Q}, the conjugate system Q' satisfies:
      q'_{r'} = mult * q_r  where r' = (mult * r) mod (p - 1).
    """
    d = p - 1
    if math.gcd(mult, d) != 1:
        return [None] + [mult * int(q_base[r]) for r in range(1, d)]
    q_new: List[Optional[int]] = [None] * d
    for r in range(1, d):
        r_prime = (mult * r) % d
        q_new[r_prime] = mult * int(q_base[r])
    return q_new


def compute_crystal_generations(
    engine: CollatzPQEngine,
    p: int,
    q_input: List[Optional[int]],
    loop_id: Optional[int] = 1,
    root_n: Optional[int] = None,
    root_mode: str = "loop",
    max_height: int = 8,
    max_gen: int = 5,
    base_multiplier: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compute CTree across generations k = 0, 1, ..., max_gen where Q^{(k)} is scaled
    by M_k = base_multiplier^k, and classify every node into:
      - 'core':    loop root node (h = 0)
      - 'frozen':  belongs to a height level h that has already reached 100% saturation
      - 'newborn': newly sprouted in generation k (normalized n / M_k was not in gen k-1)
      - 'outer':   inherited from gen k-1 but in an outer height level not yet fully frozen
    """
    g = base_multiplier if (base_multiplier and base_multiplier >= 2) else default_clone_multiplier(p)
    d = p - 1

    # First resolve generation 0 tree to get base loop members / root_n
    gen0_tree_res = engine.build_loop_tree(
        p=p,
        q_input=q_input,
        loop_id=loop_id,
        root_n=root_n,
        root_mode=root_mode,
        max_height=max_height,
        max_nodes=12000,
    )
    base_loop_min = gen0_tree_res["loop"]["min_value"]
    base_root_n = root_n if (root_mode == "single" and root_n) else base_loop_min

    generations: List[Dict[str, Any]] = []
    prev_norm_nodes: Set[str] = set()
    prev_spectrum: List[int] = []

    for k in range(max_gen + 1):
        mult_k = g ** k
        q_k = permute_q_by_multiplier(p, gen0_tree_res["q"], mult_k)

        if k == 0:
            tree_res = gen0_tree_res
        else:
            # Build tree directly from scaled loop or scaled root_n
            if root_mode == "single":
                tree_res = engine.build_loop_tree(
                    p=p,
                    q_input=q_k,
                    root_n=base_root_n * mult_k,
                    root_mode="single",
                    max_height=max_height,
                    max_nodes=12000,
                )
            else:
                # Find the matching scaled loop by tracing base_loop_min * mult_k
                tree_res = _build_scaled_loop_tree(
                    engine=engine,
                    p=p,
                    q_k=q_k,
                    scaled_loop_seed=base_loop_min * mult_k,
                    max_height=max_height,
                )

        # Compute height spectrum N_k(h) and normalized node keys
        by_h: Dict[int, int] = {h: 0 for h in range(max_height + 1)}
        curr_norm_nodes: Set[str] = set()

        def scan_collect(nd: Dict[str, Any]) -> None:
            if not nd.get("is_virtual_hub"):
                h = int(nd.get("height", 0))
                by_h[h] = by_h.get(h, 0) + 1
                norm_key = _norm_key(int(nd["n"]), mult_k)
                curr_norm_nodes.add(norm_key)
            for ch in nd.get("children", []):
                scan_collect(ch)

        scan_collect(tree_res["tree"])
        spectrum = [by_h.get(h, 0) for h in range(max_height + 1)]

        # Determine frozen frontier height: highest contiguous h from 0 where N_k(h) == N_{k-1}(h)
        frozen_height = 0
        if k > 0 and prev_spectrum:
            for h in range(1, max_height + 1):
                if spectrum[h] == prev_spectrum[h]:
                    frozen_height = h
                else:
                    break

        # Annotate every node in tree_res["tree"] with crystal_state
        counts_by_state = {"core": 0, "frozen": 0, "newborn": 0, "outer": 0}

        def annotate_nodes(nd: Dict[str, Any]) -> None:
            if not nd.get("is_virtual_hub"):
                h = int(nd.get("height", 0))
                norm_key = _norm_key(int(nd["n"]), mult_k)
                if nd.get("is_loop") or h == 0:
                    state = "core"
                elif k > 0 and norm_key not in prev_norm_nodes:
                    state = "newborn"
                elif k > 0 and h <= frozen_height:
                    state = "frozen"
                else:
                    state = "outer" if k > 0 else "frozen"
                nd["crystal_state"] = state
                nd["norm_label"] = norm_key
                counts_by_state[state] += 1
            for ch in nd.get("children", []):
                annotate_nodes(ch)

        annotate_nodes(tree_res["tree"])

        generations.append(
            {
                "generation": k,
                "multiplier": mult_k,
                "base_multiplier": g,
                "q": q_k,
                "frozen_height": frozen_height,
                "spectrum": spectrum,
                "total_nodes": tree_res["total_nodes"],
                "counts_by_state": counts_by_state,
                "loop": tree_res["loop"],
                "tree": tree_res["tree"],
            }
        )
        prev_norm_nodes = curr_norm_nodes
        prev_spectrum = spectrum

    return {
        "p": p,
        "base_q": gen0_tree_res["q"],
        "base_multiplier": g,
        "max_height": max_height,
        "max_gen": max_gen,
        "generations": generations,
    }


def _norm_key(n_val: int, mult_k: int) -> str:
    g = math.gcd(n_val, mult_k)
    num = n_val // g
    den = mult_k // g
    return f"{num}" if den == 1 else f"{num}/{den}"


def _build_scaled_loop_tree(
    engine: CollatzPQEngine,
    p: int,
    q_k: List[Optional[int]],
    scaled_loop_seed: int,
    max_height: int,
) -> Dict[str, Any]:
    """
    Trace scaled_loop_seed to extract its exact cycle in Q^{(k)} and build its CTree
    without needing a full 1..100,000 range scan.
    """
    d = p - 1
    curr = scaled_loop_seed
    cycle: List[int] = []
    seen: Set[int] = set()
    while curr not in seen and len(cycle) < 500:
        seen.add(curr)
        cycle.append(curr)
        r = curr % d
        curr = (curr // d) if r == 0 else (p * curr + int(q_k[r]))

    from backend.engine import canonicalize_cycle, format_loop_label, predecessors_pq

    members = canonicalize_cycle(cycle)
    loop_set = set(members)
    visited: Set[int] = set(members)
    node_count = len(members)
    max_nodes = 12000
    truncated = False

    def build_sub(val: int, h: int, br: int, formula_str: str) -> Dict[str, Any]:
        nonlocal node_count, truncated
        r_val = val % d
        node_obj: Dict[str, Any] = {
            "n": val,
            "height": h,
            "r": r_val,
            "branch_r": br,
            "formula": formula_str,
            "is_loop": (h == 0 and val in loop_set),
            "children": [],
        }
        if h >= max_height or node_count >= max_nodes:
            if h < max_height and node_count >= max_nodes:
                truncated = True
            return node_obj
        for p_info in predecessors_pq(val, p, d, q_k):
            m = p_info["n"]
            if m in visited:
                continue
            if node_count >= max_nodes:
                truncated = True
                break
            visited.add(m)
            node_count += 1
            node_obj["children"].append(build_sub(m, h + 1, p_info["r"], p_info["formula"]))
        return node_obj

    loop_children = [build_sub(m_val, 0, m_val % d, "Loop Member (h=0)") for m_val in members]
    elements_detail = []
    for idx, m_val in enumerate(members):
        r_val = m_val % d
        nxt = members[(idx + 1) % len(members)]
        rule_str = f"{m_val} / {d} = {nxt}" if r_val == 0 else f"{p}*{m_val} + ({q_k[r_val]}) = {nxt}"
        elements_detail.append({"index": idx, "n": m_val, "r": r_val, "next_n": nxt, "rule": rule_str})

    return {
        "p": p,
        "q": q_k,
        "root_mode": "loop",
        "max_height": max_height,
        "total_nodes": node_count,
        "truncated": truncated,
        "loop": {
            "loop_id": 1,
            "rank": 1,
            "min_value": members[0],
            "max_value": max(members),
            "length": len(members),
            "label": format_loop_label(1, members),
            "members": members,
            "elements_detail": elements_detail,
        },
        "tree": {
            "n": members[0],
            "height": -1,
            "is_virtual_hub": True,
            "label": format_loop_label(1, members),
            "children": loop_children,
        },
    }


def render_crystal_growth_gif(
    crystal_data: Dict[str, Any],
    layout_mode: str = "radial",
    frame_duration_ms: int = 900,
    show_labels: bool = False,
) -> bytes:
    """
    Render a Dark-Field Microscopy style animated GIF of CTree crystal growth
    across generations k = 0 .. max_gen.
    """
    p = crystal_data["p"]
    g = crystal_data["base_multiplier"]
    max_h = crystal_data["max_height"]
    generations = crystal_data["generations"]

    frames: List[Image.Image] = []

    for gen in generations:
        k = gen["generation"]
        mult_k = gen["multiplier"]
        q_str = ", ".join(str(x) for x in gen["q"][1:])
        frozen_h = gen["frozen_height"]
        counts = gen["counts_by_state"]
        spec_str = ", ".join(str(v) for v in gen["spectrum"])

        nodes, links, spine = _compute_2d_coords(gen["tree"], max_h, layout_mode)

        fig = plt.figure(figsize=(8.5, 8.5), dpi=130, facecolor="#030712")
        ax = fig.add_axes([0.03, 0.08, 0.94, 0.80], facecolor="#030712")
        ax.set_aspect("equal")
        ax.axis("off")

        # Draw subtle dark-field concentric height rings in radial mode
        if layout_mode == "radial":
            for h_ring in range(1, max_h + 1):
                r_ring = 1.0 + h_ring * 1.0
                is_frz = (k > 0 and h_ring <= frozen_h)
                circle = plt.Circle(
                    (0, 0),
                    r_ring,
                    fill=False,
                    color="#38bdf8" if is_frz else "#1e293b",
                    linestyle="-" if is_frz else ":",
                    linewidth=0.9 if is_frz else 0.5,
                    alpha=0.28 if is_frz else 0.35,
                )
                ax.add_patch(circle)

        # Draw loop spine
        if spine:
            for s_pt, t_pt in spine:
                ax.plot(
                    [s_pt[0], t_pt[0]],
                    [s_pt[1], t_pt[1]],
                    color="#7dd3fc",
                    lw=2.2,
                    alpha=0.85,
                    zorder=2,
                )

        # Draw branches with dark-field glow (outer halo + bright core)
        for lk in links:
            sx, sy = lk["source"]
            tx, ty = lk["target"]
            st = lk["state"]
            if st == "newborn":
                col, glow_col, lw = "#fde047", "#f59e0b", 1.8
            elif st == "frozen" or st == "core":
                col, glow_col, lw = "#e0f2fe", "#38bdf8", 1.5
            else:
                col, glow_col, lw = "#60a5fa", "#1d4ed8", 1.0

            ax.plot([sx, tx], [sy, ty], color=glow_col, lw=lw * 2.8, alpha=0.28, zorder=3)
            ax.plot([sx, tx], [sy, ty], color=col, lw=lw, alpha=0.92, zorder=4)

        # Draw nodes by crystal state
        for st_key, col, halo_col, sz in [
            ("outer", "#93c5fd", "#2563eb", 18),
            ("frozen", "#e0f2fe", "#38bdf8", 28),
            ("newborn", "#fef08a", "#f59e0b", 38),
            ("core", "#ffffff", "#7dd3fc", 52),
        ]:
            pts = [nd for nd in nodes if nd["state"] == st_key]
            if not pts:
                continue
            xs = [pt["x"] for pt in pts]
            ys = [pt["y"] for pt in pts]
            ax.scatter(xs, ys, s=sz * 2.6, color=halo_col, alpha=0.32, edgecolors="none", zorder=5)
            ax.scatter(xs, ys, s=sz, color=col, alpha=0.98, edgecolors="none", zorder=6)

        if show_labels and len(nodes) <= 220:
            for nd in nodes:
                ax.text(
                    nd["x"],
                    nd["y"] + 0.16,
                    str(nd["n"]),
                    color="#e2e8f0",
                    fontsize=6.5,
                    ha="center",
                    va="bottom",
                    zorder=7,
                )

        lim = (max_h + 1.8) if layout_mode == "radial" else None
        if lim:
            ax.set_xlim(-lim, lim)
            ax.set_ylim(-lim, lim)

        fig.text(
            0.5,
            0.94,
            f"Dark-Field CTree Crystal Growth  |  p={p},  Generation k={k}  (×{g}^{k} = ×{mult_k})",
            color="#f8fafc",
            fontsize=13,
            fontweight="bold",
            ha="center",
        )
        fig.text(
            0.5,
            0.905,
            f"Q^({k}) = [_, {q_str}]   |   Frozen Zone: h ≤ {frozen_h}   |   Total Nodes: {gen['total_nodes']} "
            f"(Frozen: {counts['frozen']+counts['core']}, Newborn Sprouts: {counts['newborn']})",
            color="#7dd3fc",
            fontsize=9.5,
            ha="center",
        )
        fig.text(
            0.5,
            0.035,
            f"Height Spectrum N(h) = [{spec_str}]",
            color="#cbd5e1",
            fontsize=9,
            family="monospace",
            ha="center",
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor="#030712")
        plt.close(fig)
        buf.seek(0)
        frames.append(Image.open(buf).convert("P", palette=Image.Palette.ADAPTIVE, colors=256))

    out_gif = io.BytesIO()
    if frames:
        durations = [frame_duration_ms] * len(frames)
        durations[-1] = int(frame_duration_ms * 1.8)  # Hold final crystal frame longer
        frames[0].save(
            out_gif,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
        )
    return out_gif.getvalue()


def _compute_2d_coords(
    root: Dict[str, Any], max_h: int, layout_mode: str = "radial"
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Tuple[Tuple[float, float], Tuple[float, float]]]]:
    leaf_cursor = 0.0

    def assign_u(nd: Dict[str, Any], depth: int) -> float:
        nonlocal leaf_cursor
        chs = nd.get("children", [])
        if not chs:
            u = leaf_cursor
            leaf_cursor += 1.0
        else:
            child_us = [assign_u(c, depth + 1) for c in chs]
            u = (child_us[0] + child_us[-1]) / 2.0
        nd["_u"] = u
        nd["_depth"] = depth
        return u

    is_hub = bool(root.get("is_virtual_hub"))
    if is_hub:
        for lc in root.get("children", []):
            assign_u(lc, 0)
            leaf_cursor += 0.5
    else:
        assign_u(root, 0)

    total_span = max(1.0, leaf_cursor)
    nodes: List[Dict[str, Any]] = []
    links: List[Dict[str, Any]] = []
    spine: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []

    def map_xy(u: float, depth: int) -> Tuple[float, float]:
        if layout_mode == "radial":
            angle = (2.0 * math.pi * (u + 0.25)) / total_span
            radius = 1.0 + depth * 1.0
            return (radius * math.cos(angle), radius * math.sin(angle))
        else:
            x = (u - total_span / 2.0) * 0.45
            y = depth * 1.0 - max_h / 2.0
            return (x, y)

    def collect(nd: Dict[str, Any]) -> Dict[str, Any]:
        x, y = map_xy(nd["_u"], nd["_depth"])
        item = {
            "n": nd["n"],
            "height": nd.get("height", 0),
            "state": nd.get("crystal_state", "frozen"),
            "x": x,
            "y": y,
        }
        nodes.append(item)
        for ch in nd.get("children", []):
            ch_item = collect(ch)
            links.append(
                {
                    "source": (x, y),
                    "target": (ch_item["x"], ch_item["y"]),
                    "state": ch_item["state"],
                }
            )
        return item

    if is_hub:
        loop_pts = []
        for lc in root.get("children", []):
            it = collect(lc)
            loop_pts.append((it["x"], it["y"]))
        if len(loop_pts) >= 2:
            for i in range(len(loop_pts)):
                spine.append((loop_pts[i], loop_pts[(i + 1) % len(loop_pts)]))
    else:
        collect(root)

    return nodes, links, spine
