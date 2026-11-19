"""
Backend data & computation helpers for the interactive p=4 CTree-nodes heatmap
and primitive Q-family explorer.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
SUMMARY_900_PATH = ROOT_DIR / "outputs" / "p4_900dbs_summary.csv"
CATALOG_900_PATH = ROOT_DIR / "outputs" / "p4_all_loops_catalog.csv"
H10_GRID_PATH = ROOT_DIR / "outputs" / "p4_ctree_nodes_h10_30x30.csv"

_HEATMAP_CACHE: Dict[Tuple[int, int], Dict[str, Any]] = {}


def get_available_grid_sizes() -> List[int]:
    """Return sorted list of available p=4 grid sizes (e.g. [30, 80])."""
    sizes: List[int] = []
    if SUMMARY_900_PATH.exists():
        sizes.append(30)
    outputs_dir = ROOT_DIR / "outputs"
    if outputs_dir.exists():
        for p_dir in outputs_dir.glob("p4_grid_*x*"):
            if (p_dir / "summary.csv").exists():
                try:
                    n = int(p_dir.name.split("p4_grid_")[1].split("x")[0])
                    if n not in sizes:
                        sizes.append(n)
                except ValueError:
                    pass
    return sorted(sizes)


def canonical_base(q1: int, q2: int) -> Tuple[int, Tuple[int, int]]:
    """Return (g, (a, b)) where g=gcd(q1,q2) and (a, b) is the primitive p=4 base."""
    g = math.gcd(q1, q2)
    a, b = q1 // g, q2 // g
    if g % 3 == 2:
        return g, (b, a)
    return g, (a, b)


def reconstruct_loop_members(q1: int, q2: int, min_val: int) -> List[int]:
    """Reconstruct all members of a p=4 cycle starting from its min_value."""
    members = [min_val]
    curr = min_val
    for _ in range(100000):
        r = curr % 3
        if r == 0:
            curr //= 3
        elif r == 1:
            curr = 4 * curr + q1
        else:
            curr = 4 * curr + q2
        if curr == min_val:
            return members
        members.append(curr)
    raise RuntimeError(f"Failed to close p=4 loop from min_val={min_val} for Q=({q1}, {q2})")


def count_ctree_nodes_p4(q1: int, q2: int, loop_members: List[int], max_height: int) -> int:
    """Count total CTree nodes up to `max_height` (including h=0 loop members) via exact BFS."""
    q_by_mod: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    q_by_mod[q1 % 4].append((1, q1))
    q_by_mod[q2 % 4].append((2, q2))

    visited = set(loop_members)
    frontier = list(loop_members)

    for _ in range(1, max_height + 1):
        next_frontier: List[int] = []
        for y in frontier:
            c_div = 3 * y
            if c_div not in visited:
                visited.add(c_div)
                next_frontier.append(c_div)
            for r_idx, q_val in q_by_mod.get(y % 4, ()):
                if y > q_val:
                    cand = (y - q_val) // 4
                    if cand % 3 == r_idx and cand not in visited:
                        visited.add(cand)
                        next_frontier.append(cand)
        frontier = next_frontier
        if not frontier:
            break

    return len(visited)


def classify_personality(
    base_num_loops: int,
    base_max_loop_len: int,
    mean_nodes: float,
    mean_avg_steps: float,
) -> str:
    """Generate a concise Japanese personality tag for a Q-family."""
    tags: List[str] = []
    if base_num_loops == 1:
        tags.append("単ループ一本杉")
    elif base_max_loop_len >= 50:
        tags.append("巨大ループ搭載")
    else:
        tags.append(f"多ループ({base_num_loops}本)")

    if mean_nodes >= 10000:
        tags.append("超爆発型")
    elif mean_nodes >= 5000:
        tags.append("大型")
    elif mean_nodes <= 1500:
        tags.append("スリム省ノード型")
    else:
        tags.append("標準規模")

    if mean_avg_steps < 65.0:
        tags.append("超高速収束")
    elif mean_avg_steps > 95.0:
        tags.append("長距離軌道")

    return " / ".join(tags)


def load_p4_heatmap(max_height: int = 10, grid_size: Optional[int] = None) -> Dict[str, Any]:
    """Load (or compute & cache) the NxN p=4 heatmap dataset with family metadata."""
    max_height = max(1, min(int(max_height), 14))
    avail = get_available_grid_sizes()
    if grid_size is None:
        grid_size = avail[-1] if avail else 30
    cache_key = (grid_size, max_height)
    if cache_key in _HEATMAP_CACHE:
        return _HEATMAP_CACHE[cache_key]

    if grid_size == 30:
        summary_path = SUMMARY_900_PATH
        catalog_path = CATALOG_900_PATH
        nodes_grid_path = H10_GRID_PATH if max_height == 10 else None
    else:
        grid_dir = ROOT_DIR / "outputs" / f"p4_grid_{grid_size}x{grid_size}"
        summary_path = grid_dir / "summary.csv"
        catalog_path = grid_dir / "loops_catalog.csv"
        cand_nodes = grid_dir / f"ctree_nodes_h{max_height}.csv"
        nodes_grid_path = cand_nodes if cand_nodes.exists() else None
        if not summary_path.exists():
            raise ValueError(f"Grid size {grid_size}x{grid_size} not found at {summary_path}")

    q1_vals = [2 + 3 * i for i in range(grid_size)]
    q2_vals = [1 + 3 * j for j in range(grid_size)]

    # Load precomputed nodes grid if available
    nodes_map: Dict[Tuple[int, int], int] = {}
    if nodes_grid_path is not None and nodes_grid_path.exists():
        with nodes_grid_path.open(encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader)
            cols = [int(x) for x in header[1:]]
            for row in reader:
                q2 = int(row[0])
                for q1, val in zip(cols, row[1:]):
                    nodes_map[(q1, q2)] = int(val)
    else:
        loops_by_cell: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        with catalog_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                loops_by_cell[(int(row["q1"]), int(row["q2"]))].append(int(row["min_value"]))
        for q2 in q2_vals:
            for q1 in q1_vals:
                tot = 0
                for mv in loops_by_cell.get((q1, q2), ()):
                    members = reconstruct_loop_members(q1, q2, mv)
                    tot += count_ctree_nodes_p4(q1, q2, members, max_height)
                nodes_map[(q1, q2)] = tot

    cells: Dict[str, Dict[str, Any]] = {}
    fam_members: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    with summary_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            q1 = int(row["q1"])
            q2 = int(row["q2"])
            g, base = canonical_base(q1, q2)
            base_str = f"({base[0]},{base[1]})"
            lens = [int(x) for x in row["loop_lengths"].split(";") if x.strip()]
            n_val = nodes_map.get((q1, q2), 0)
            cell = {
                "key": f"{q1},{q2}",
                "q1": q1,
                "q2": q2,
                "gcd": g,
                "base": [base[0], base[1]],
                "base_str": base_str,
                "mod4": [q1 % 4, q2 % 4],
                "nodes": n_val,
                "num_loops": int(row["num_loops"]),
                "max_loop_len": max(lens, default=0),
                "loop_lengths": lens,
                "dom_share_pct": float(row["dominant_loop_share_pct"]),
                "avg_steps": float(row["avg_steps"]),
                "max_steps": int(row["max_steps"]),
                "is_extra": False,
            }
            cells[cell["key"]] = cell
            fam_members[base_str].append(cell)

    families: Dict[str, Dict[str, Any]] = {}
    for base_str, members in fam_members.items():
        members.sort(key=lambda c: c["gcd"])
        base_m = members[0]
        nodes_list = [c["nodes"] for c in members]
        steps_list = [c["avg_steps"] for c in members]
        mean_nodes = round(statistics.mean(nodes_list), 1)
        mean_steps = round(statistics.mean(steps_list), 2)
        families[base_str] = {
            "base": base_m["base"],
            "base_str": base_str,
            "member_keys": [c["key"] for c in members],
            "base_num_loops": base_m["num_loops"],
            "base_loop_lengths": base_m["loop_lengths"],
            "base_max_loop_len": base_m["max_loop_len"],
            "mean_nodes": mean_nodes,
            "min_nodes": min(nodes_list),
            "max_nodes": max(nodes_list),
            "mean_avg_steps": mean_steps,
            "personality": classify_personality(
                base_m["num_loops"], base_m["max_loop_len"], mean_nodes, mean_steps
            ),
        }

    result = {
        "max_height": max_height,
        "grid_size": grid_size,
        "available_grids": avail,
        "q1_vals": q1_vals,
        "q2_vals": q2_vals,
        "cells": cells,
        "families": families,
    }
    _HEATMAP_CACHE[cache_key] = result
    return result


def next_family_member_q(
    base_a: int,
    base_b: int,
    existing_qs: Iterable[Tuple[int, int]],
) -> Tuple[int, int, int]:
    """Find the smallest g >= 1 (gcd(g, 3) == 1) whose (q1, q2) is not in existing_qs."""
    existing = set(existing_qs)
    g = 1
    while True:
        if g % 3 != 0:
            q1, q2 = (g * base_b, g * base_a) if (g % 3 == 2) else (g * base_a, g * base_b)
            if (q1, q2) not in existing:
                return g, q1, q2
        g += 1


def compute_p4_cell(
    q1: int,
    q2: int,
    max_height: int = 10,
    n_max: int = 100000,
    max_steps_limit: int = 10000,
) -> Dict[str, Any]:
    """Evaluate T_{4,(q1,q2)} on 1..n_max and compute exact CTree nodes up to max_height."""
    if q1 < 1 or q1 % 3 != 2:
        raise ValueError(f"q1 must satisfy q1 >= 2 and q1 % 3 == 2 (got {q1})")
    if q2 < 1 or q2 % 3 != 1:
        raise ValueError(f"q2 must satisfy q2 >= 1 and q2 % 3 == 1 (got {q2})")

    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops: Dict[int, Dict[str, Any]] = {}
    next_lid = 1

    for start_n in range(1, n_max + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_idx: Dict[int, int] = {}
        curr = start_n

        while curr not in steps_cache and curr not in path_idx and len(path) <= max_steps_limit:
            path_idx[curr] = len(path)
            path.append(curr)
            r = curr % 3
            if r == 0:
                curr //= 3
            elif r == 1:
                curr = 4 * curr + q1
            else:
                curr = 4 * curr + q2

        if curr in steps_cache:
            ks, klid = steps_cache[curr]
            for i, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (ks + i, klid)
        elif curr in path_idx:
            c_start = path_idx[curr]
            cycle = path[c_start:]
            lid = next_lid
            next_lid += 1
            loops[lid] = {
                "min_value": min(cycle),
                "members": cycle,
                "length": len(cycle),
                "basin_count": 0,
            }
            for val in cycle:
                steps_cache[val] = (0, lid)
            for i, val in enumerate(reversed(path[:c_start]), start=1):
                steps_cache[val] = (i, lid)
        else:
            for val in path:
                steps_cache[val] = (-1, -1)

    total_steps = 0
    max_obs_steps = 0
    resolved = 0
    for n in range(1, n_max + 1):
        s, lid = steps_cache[n]
        if lid > 0:
            resolved += 1
            total_steps += s
            if s > max_obs_steps:
                max_obs_steps = s
            loops[lid]["basin_count"] += 1

    loop_list = sorted(loops.values(), key=lambda x: x["min_value"])
    lens = [lp["length"] for lp in loop_list]
    max_basin = max((lp["basin_count"] for lp in loop_list), default=0)
    dom_share = round(100.0 * max_basin / resolved, 2) if resolved else 0.0
    avg_steps = round(total_steps / resolved, 2) if resolved else 0.0

    total_nodes = sum(
        count_ctree_nodes_p4(q1, q2, lp["members"], max_height) for lp in loop_list
    )

    g, base = canonical_base(q1, q2)
    base_str = f"({base[0]},{base[1]})"

    return {
        "key": f"{q1},{q2}",
        "q1": q1,
        "q2": q2,
        "gcd": g,
        "base": [base[0], base[1]],
        "base_str": base_str,
        "mod4": [q1 % 4, q2 % 4],
        "nodes": total_nodes,
        "num_loops": len(loop_list),
        "max_loop_len": max(lens, default=0),
        "loop_lengths": lens,
        "dom_share_pct": dom_share,
        "avg_steps": avg_steps,
        "max_steps": max_obs_steps,
        "is_extra": True,
    }

