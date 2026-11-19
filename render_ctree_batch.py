"""
Batch renderer for (p, Q) Collatz CTree images matching the web app's default
LoopTreeModal style (root_mode='loop', max_height=10, orientation='BT',
highlightNodeRoles=True, showLabels=True).

Examples:
  # Render all 13 systems from docs/2026_1116/from_p4_q2_1.jpg:
  .venv/bin/python render_ctree_batch.py --preset from_p4_q2_1

  # Render a single (p, Q):
  .venv/bin/python render_ctree_batch.py --p 4 --q 2 10

  # Render multiple Qs for a given p:
  .venv/bin/python render_ctree_batch.py --p 4 --q-list "2,1; 2,10; 5,1; 14,10"
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

from backend.engine import CollatzPQEngine, validate_pq


PRESET_FROM_P4_Q2_1: List[Tuple[str, List[int]]] = [
    ("00_root", [2, 1]),
    ("L1", [2, 10]),
    ("L2_left", [14, 10]),
    ("L2_right", [2, 22]),
    ("L3_left", [26, 10]),
    ("L3_mid", [14, 22]),
    ("L3_right", [2, 34]),
    ("R1", [5, 1]),
    ("R2_left", [17, 1]),
    ("R2_right", [5, 13]),
    ("R3_left", [29, 1]),
    ("R3_mid", [17, 13]),
    ("R3_right", [5, 25]),
]


def layout_tree(
    tree_root: Dict[str, Any],
    orientation: str = "BT",
    sibling_spacing: float = 34.0,
    level_spacing: float = 75.0,
    sea_level_q: int = 1,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Replicate LoopTreeModal.svelte post-order layout."""
    leaf_cursor = 0.0

    def assign_coords(node: Dict[str, Any], depth: int) -> float:
        nonlocal leaf_cursor
        children = node.get("children") or []
        if not children:
            u = leaf_cursor
            leaf_cursor += 1.0
        else:
            child_us = [assign_coords(ch, depth + 1) for ch in children]
            u = (child_us[0] + child_us[-1]) / 2.0
        node["_u"] = u
        node["_depth"] = depth
        return u

    is_virtual_hub = bool(tree_root.get("is_virtual_hub"))
    if is_virtual_hub:
        for lc in tree_root.get("children") or []:
            assign_coords(lc, 0)
            leaf_cursor += 0.35
    else:
        assign_coords(tree_root, 0)

    def map_uv(u: float, depth: int) -> Tuple[float, float]:
        bx = u * sibling_spacing
        dy = depth * level_spacing
        if orientation == "TB":
            return bx, -dy
        if orientation == "BT":
            return bx, dy
        if orientation == "LR":
            return dy, -bx
        return -dy, -bx

    nodes: List[Dict[str, Any]] = []
    links: List[Dict[str, Any]] = []
    spine: List[Dict[str, Any]] = []

    def collect(node: Dict[str, Any]) -> Dict[str, Any]:
        x, y = map_uv(node["_u"], node["_depth"])
        item = {
            "n": node["n"],
            "height": node.get("height", node["_depth"]),
            "depth": node["_depth"],
            "r": node.get("r", 0),
            "branch_r": node.get("branch_r", 0),
            "is_loop": bool(node.get("is_loop", False)),
            "below_sea": node["n"] <= sea_level_q,
            "x": x,
            "y": y,
        }
        nodes.append(item)
        for ch in node.get("children") or []:
            ch_item = collect(ch)
            links.append(
                {
                    "x1": item["x"],
                    "y1": item["y"],
                    "x2": ch_item["x"],
                    "y2": ch_item["y"],
                    "branch_r": ch.get("branch_r", 0),
                }
            )
        return item

    if is_virtual_hub:
        loop_roots = [collect(lc) for lc in (tree_root.get("children") or [])]
        for i in range(len(loop_roots) - 1):
            spine.append(
                {
                    "x1": loop_roots[i]["x"],
                    "y1": loop_roots[i]["y"],
                    "x2": loop_roots[i + 1]["x"],
                    "y2": loop_roots[i + 1]["y"],
                }
            )
    else:
        collect(tree_root)

    return nodes, links, spine


def node_style(nd: Dict[str, Any], highlight_roles: bool = True, base_radius: float = 6.0) -> Tuple[str, float]:
    """Match LoopTreeModal.svelte getNodeFillColor & getNodeRadiusPx."""
    if nd["is_loop"]:
        return "#dc2626", base_radius * 1.3
    if not highlight_roles:
        return "#0284c7", base_radius
    if nd["r"] != 0 or nd["branch_r"] != 0:
        return "#dc2626", base_radius * 1.15
    if nd["below_sea"]:
        return "#0284c7", max(2.5, base_radius * 0.78)
    return "#94a3b8", max(2.5, base_radius * 0.78)


def render_ctree_png(
    engine: CollatzPQEngine,
    p: int,
    q_vals: List[int],
    out_path: Path,
    *,
    loop_id: Optional[int] = None,
    root_mode: str = "loop",
    root_n: Optional[int] = None,
    max_height: int = 10,
    max_nodes: int = 15000,
    orientation: str = "BT",
    show_labels: bool = True,
    highlight_roles: bool = True,
    tag: str = "",
) -> Dict[str, Any]:
    """Build CTree via CollatzPQEngine and render PNG matching app defaults."""
    res = engine.build_loop_tree(
        p=p,
        q_input=q_vals,
        loop_id=loop_id,
        root_n=root_n,
        root_mode=root_mode,
        max_height=max_height,
        max_nodes=max_nodes,
    )

    sea_level_q = max(q_vals) if q_vals else 1
    nodes, links, spine = layout_tree(
        res["tree"],
        orientation=orientation,
        sibling_spacing=34.0,
        level_spacing=75.0,
        sea_level_q=sea_level_q,
    )

    xs = [nd["x"] for nd in nodes]
    ys = [nd["y"] for nd in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(120.0, max_x - min_x)
    span_y = max(120.0, max_y - min_y)

    # Scale figure size proportionally while keeping crisp readability
    fig_w = max(8.0, min(26.0, span_x / 58.0 + 1.6))
    fig_h = max(5.5, min(14.0, span_y / 72.0 + 1.8))

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    # Loop spine at depth 0
    for sp in spine:
        ax.plot(
            [sp["x1"], sp["x2"]],
            [sp["y1"], sp["y2"]],
            color="#dc2626",
            linestyle=(0, (4, 3)),
            linewidth=1.5,
            alpha=0.75,
            zorder=1,
        )

    # Edges (solid for *d conduit, dashed for q_r branch)
    for lk in links:
        ls = "-" if lk["branch_r"] == 0 else (0, (3, 2))
        ax.plot(
            [lk["x1"], lk["x2"]],
            [lk["y1"], lk["y2"]],
            color="#64748b",
            linestyle=ls,
            linewidth=1.3,
            alpha=0.85,
            zorder=2,
        )

    # Nodes & labels
    # Use scatter for crisp circular markers regardless of aspect ratio
    for nd in nodes:
        color, rad = node_style(nd, highlight_roles=highlight_roles, base_radius=6.0)
        size_pts2 = (rad * 1.1) ** 2
        ax.scatter(
            [nd["x"]],
            [nd["y"]],
            s=size_pts2,
            c=color,
            edgecolors="#ffffff",
            linewidths=0.6,
            alpha=0.95,
            zorder=3,
        )
        if show_labels:
            ax.text(
                nd["x"],
                nd["y"] + 11.0,
                str(nd["n"]),
                fontsize=6.5 if len(nodes) > 120 else 8.0,
                color="#0f172a",
                ha="center",
                va="bottom",
                zorder=4,
            )

    pad_x = max(35.0, span_x * 0.05)
    pad_y = max(35.0, span_y * 0.09)
    ax.set_xlim(min_x - pad_x, max_x + pad_x)
    ax.set_ylim(min_y - pad_y * 0.6, max_y + pad_y)
    ax.axis("off")

    mods = [q % p for q in q_vals]
    loop_members = res.get("loop_members") or []
    loop_str = f"Loop #{res.get('loop_id')} (len={len(loop_members)}, min={min(loop_members)})" if loop_members else f"Root={res.get('root_n')}"
    prefix = f"[{tag}] " if tag else ""
    ax.set_title(
        f"{prefix}p={p}, Q={q_vals} (mod {p}={mods}) | {loop_str} | H={max_height}, nodes={res['total_nodes']}",
        fontsize=11,
        fontweight="bold",
        color="#0f172a",
        pad=10,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, facecolor="#ffffff")
    plt.close(fig)
    return res


def parse_q_list(raw: str) -> List[List[int]]:
    items: List[List[int]] = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        items.append([int(x.strip()) for x in part.split(",") if x.strip()])
    return items


def get_loop_ids_ordered(engine: CollatzPQEngine, p: int, q_vals: List[int]) -> List[int]:
    """Ensure [1..2000] is computed for (p, Q) and return all discovered loop_ids sorted by min_value."""
    validation = validate_pq(p, q_vals)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    q_norm = validation["q_normalized"]
    with engine._get_conn() as conn:
        system_id = engine._get_or_create_system(conn, p, q_norm)
    if not engine._loops_mem.get(system_id):
        engine.compute_range(p=p, q_input=q_norm, n_start=1, n_end=2000)
    loops = sorted(engine._loops_mem[system_id].values(), key=lambda x: x["min_value"])
    return [int(lp["loop_id"]) for lp in loops]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render (p, Q) CTree PNGs matching the web app default view.")
    parser.add_argument("--p", type=int, default=4, help="Multiplier p (default: 4).")
    parser.add_argument("--q", type=int, nargs="+", help="Single Q vector, e.g. --q 2 10.")
    parser.add_argument("--q-list", type=str, help="Semicolon-separated Q vectors, e.g. '2,1; 2,10; 5,1'.")
    parser.add_argument("--preset", choices=["from_p4_q2_1"], help="Built-in preset batch.")
    parser.add_argument("--loop-id", type=str, default=None, help="Specific loop_id or 'all' (default: min_value loop).")
    parser.add_argument("--root-mode", choices=["loop", "single"], default="loop")
    parser.add_argument("--root-n", type=int, default=None)
    parser.add_argument("--max-height", type=int, default=10, help="Tree height (app default: 10).")
    parser.add_argument("--max-nodes", type=int, default=15000)
    parser.add_argument("--orientation", choices=["BT", "TB", "LR", "RL"], default="BT")
    parser.add_argument("--no-labels", action="store_true", help="Hide integer node labels.")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/ctree_batch"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    jobs: List[Tuple[str, int, List[int]]] = []
    if args.preset == "from_p4_q2_1":
        if args.out_dir == Path("outputs/ctree_batch"):
            args.out_dir = Path("outputs/ctree_from_p4_q2_1")
            args.out_dir.mkdir(parents=True, exist_ok=True)
        for tag, q_vals in PRESET_FROM_P4_Q2_1:
            jobs.append((tag, 4, q_vals))
    elif args.q_list:
        for idx, q_vals in enumerate(parse_q_list(args.q_list), start=1):
            jobs.append((f"{idx:02d}", args.p, q_vals))
    elif args.q:
        jobs.append(("", args.p, args.q))
    else:
        parser.error("Specify one of --preset, --q, or --q-list.")

    loop_all = args.loop_id is not None and args.loop_id.strip().lower() == "all"
    single_loop_id: Optional[int] = None
    if args.loop_id is not None and not loop_all:
        try:
            single_loop_id = int(args.loop_id)
        except ValueError:
            parser.error(f"--loop-id must be an integer or 'all' (got {args.loop_id!r}).")

    engine = CollatzPQEngine(db_path=args.out_dir / "_engine_cache.db")

    for tag, p, q_vals in jobs:
        q_slug = "_".join(str(x) for x in q_vals)
        target_loop_ids: List[Optional[int]] = (
            list(get_loop_ids_ordered(engine, p, q_vals)) if loop_all else [single_loop_id]
        )
        for lid in target_loop_ids:
            loop_suffix = f"_loop{lid}" if (loop_all or single_loop_id is not None) else ""
            fname = (
                f"{tag}_p{p}_Q{q_slug}{loop_suffix}_h{args.max_height}.png"
                if tag
                else f"ctree_p{p}_Q{q_slug}{loop_suffix}_h{args.max_height}.png"
            )
            out_path = args.out_dir / fname
            res = render_ctree_png(
                engine,
                p,
                q_vals,
                out_path,
                loop_id=lid,
                root_mode=args.root_mode,
                root_n=args.root_n,
                max_height=args.max_height,
                max_nodes=args.max_nodes,
                orientation=args.orientation,
                show_labels=not args.no_labels,
                tag=tag,
            )
            print(f"Saved {out_path} (loop_id={res.get('loop_id')}, nodes={res['total_nodes']}, truncated={res['truncated']})")


if __name__ == "__main__":
    main()
