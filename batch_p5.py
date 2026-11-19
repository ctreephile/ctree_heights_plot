#!/usr/bin/env python3
"""
Disk-Efficient Batch Grid Runner for (p, Q) = (5, [_, q1, q2, q3]).

Follows the disk-saving architecture in `docs/HANDOFF.md`:
1. Single Master Aggregated SQLite DB (`data/p5/summary_p5.db`) with two tables:
     - `systems`: system_id, p, q_json, gcd_q, n_max, num_loops, max_steps,
                  max_step_n, avg_steps, unresolved_count, gini, gini_norm,
                  hhi, shannon_evenness, elapsed_ms
     - `loops`:   system_id, loop_id, min_value, max_value, length, l_div_count,
                  k_mul_count, k1_count, k2_count, k3_count, basin_count,
                  basin_share, elements_json
2. Lightweight PNG-only batch image generation (`data/p5/Images/`) with
   `--plot-mode none | interesting | all` (default: `interesting`).
3. Optional zlib-compressed trajectory binary persistence (`--save-compressed-nodes`)
   in `data/p5/trajectories/`.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import struct
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator, ScalarFormatter

from backend.engine import (
    DEFAULT_PALETTE,
    canonicalize_cycle,
    format_loop_label,
    validate_pq,
)
from backend.logger import get_logger

logger = get_logger("batch_p5")

P_VAL = 5
D_VAL = P_VAL - 1  # 4

# For p = 5 (d = 4), divisibility requires q_r ≡ 4 - r (mod 4):
#   r = 1: q1 ≡ 3 (mod 4) -> 3, 7, 11, ..., 79 (20 values for 20x20x20 = 8,000)
#   r = 2: q2 ≡ 2 (mod 4) -> 2, 6, 10, ..., 78 (20 values)
#   r = 3: q3 ≡ 1 (mod 4) -> 1, 5, 9, ..., 77  (20 values)
DEFAULT_LIMIT_Q = 20
DEFAULT_Q1_LIST = [4 * k + 3 for k in range(30)]  # Up to 30 values predefined
DEFAULT_Q2_LIST = [4 * k + 2 for k in range(30)]
DEFAULT_Q3_LIST = [4 * k + 1 for k in range(30)]

DEFAULT_DATA_DIR = Path("data/p5")
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "summary_p5.db"
DEFAULT_CSV_PATH = DEFAULT_DATA_DIR / "summary_p5.csv"
DEFAULT_LOOPS_CSV_PATH = DEFAULT_DATA_DIR / "loops_p5.csv"
DEFAULT_IMG_DIR = DEFAULT_DATA_DIR / "Images"
DEFAULT_TRAJ_DIR = DEFAULT_DATA_DIR / "trajectories"


def build_q_lists(limit_q1: int, limit_q2: int, limit_q3: int) -> Tuple[List[int], List[int], List[int]]:
    q1_list = [4 * k + 3 for k in range(limit_q1)]
    q2_list = [4 * k + 2 for k in range(limit_q2)]
    q3_list = [4 * k + 1 for k in range(limit_q3)]
    return q1_list, q2_list, q3_list


def compute_gini_metrics(counts: List[int]) -> Dict[str, float]:
    """
    Compute inequality metrics for a list of basin sizes `counts` across M loops:
      - gini: Standard Gini G in [0, (M-1)/M]
      - gini_norm: Normalized Gini G* = G * M / (M-1) in [0, 1] (for M >= 2)
      - hhi: Herfindahl-Hirschman Index sum(s_i^2)
      - shannon_evenness: Shannon Equitability in [0, 1]
    """
    m = len(counts)
    total = sum(counts)
    if m <= 1 or total <= 0:
        return {
            "gini": 0.0,
            "gini_norm": 0.0,
            "hhi": 1.0 if m == 1 and total > 0 else 0.0,
            "shannon_evenness": 1.0 if m == 1 else 0.0,
        }

    sorted_x = sorted(counts)
    weighted_sum = sum((idx + 1) * x for idx, x in enumerate(sorted_x))
    gini = (2.0 * weighted_sum) / (m * total) - (m + 1.0) / m
    gini = max(0.0, min(1.0, gini))

    gini_norm = gini * (m / (m - 1.0))
    gini_norm = max(0.0, min(1.0, gini_norm))

    shares = [x / total for x in sorted_x]
    hhi = sum(s * s for s in shares)

    entropy = -sum(s * math.log(s) for s in shares if s > 0)
    evenness = entropy / math.log(m) if m > 1 else 1.0

    return {
        "gini": gini,
        "gini_norm": gini_norm,
        "hhi": hhi,
        "shannon_evenness": evenness,
    }


def evaluate_p5_system(
    q1: int,
    q2: int,
    q3: int,
    max_n: int,
    max_steps: int,
    return_points: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate trajectories for (p=5, Q=[None, q1, q2, q3]) over n = 1..max_n
    purely in memory and compute all summary & loop statistics.
    """
    t0 = time.perf_counter()
    p = P_VAL
    d = D_VAL
    q_norm: List[Optional[int]] = [None, q1, q2, q3]
    gcd_q = math.gcd(math.gcd(q1, q2), q3)

    # n -> (loop_id, steps)
    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops_by_min: Dict[int, Dict[str, Any]] = {}
    next_loop_id = 1

    for start_n in range(1, max_n + 1):
        if start_n in steps_cache:
            continue

        path: List[int] = []
        path_index: Dict[int, int] = {}
        curr = start_n

        while (
            curr not in steps_cache
            and curr not in path_index
            and len(path) <= max_steps
        ):
            path_index[curr] = len(path)
            path.append(curr)
            r = curr & 3  # curr % 4 (since d = 4)
            if r == 0:
                curr = curr >> 2  # curr // 4
            elif r == 1:
                curr = 5 * curr + q1
            elif r == 2:
                curr = 5 * curr + q2
            else:
                curr = 5 * curr + q3

        if curr in steps_cache:
            target_lid, base_steps = steps_cache[curr]
            path_len = len(path)
            if target_lid == 0 or base_steps < 0:
                for val in path:
                    steps_cache[val] = (0, -1)
            else:
                for idx, val in enumerate(path):
                    steps_cache[val] = (target_lid, base_steps + (path_len - idx))
        elif curr in path_index:
            cycle_start = path_index[curr]
            raw_cycle = path[cycle_start:]
            canonical_members = canonicalize_cycle(raw_cycle)
            min_val = canonical_members[0]
            cycle_len = len(canonical_members)

            if min_val not in loops_by_min:
                lid = next_loop_id
                next_loop_id += 1
                loops_by_min[min_val] = {
                    "raw_loop_id": lid,
                    "min_value": min_val,
                    "max_value": max(canonical_members),
                    "length": cycle_len,
                    "members": canonical_members,
                }
            else:
                lid = loops_by_min[min_val]["raw_loop_id"]

            for val in raw_cycle:
                steps_cache[val] = (lid, 0)

            for idx in range(cycle_start):
                steps_cache[path[idx]] = (lid, cycle_start - idx)
        else:
            steps_cache[start_n] = (0, -1)

    # Sort loops deterministically by min_value and remap loop_id to 1..M
    sorted_loops = sorted(loops_by_min.values(), key=lambda x: x["min_value"])
    raw_to_rank: Dict[int, int] = {
        lp["raw_loop_id"]: idx + 1 for idx, lp in enumerate(sorted_loops)
    }

    basin_counts: Dict[int, int] = {idx + 1: 0 for idx in range(len(sorted_loops))}
    unresolved_count = 0
    max_obs_steps = 0
    max_step_n = 1
    total_resolved_steps = 0
    resolved_count = 0

    pts_lid: List[int] = []
    pts_steps: List[int] = []

    for n_val in range(1, max_n + 1):
        raw_lid, st = steps_cache[n_val]
        if raw_lid == 0 or st < 0:
            unresolved_count += 1
            if return_points:
                pts_lid.append(0)
                pts_steps.append(-1)
        else:
            rank_lid = raw_to_rank[raw_lid]
            basin_counts[rank_lid] += 1
            total_resolved_steps += st
            resolved_count += 1
            if st > max_obs_steps:
                max_obs_steps = st
                max_step_n = n_val
            if return_points:
                pts_lid.append(rank_lid)
                pts_steps.append(st)

    avg_steps = (total_resolved_steps / resolved_count) if resolved_count > 0 else 0.0

    loops_records: List[Dict[str, Any]] = []
    counts_for_gini: List[int] = []

    for idx, lp in enumerate(sorted_loops):
        rank_lid = idx + 1
        members = lp["members"]
        l_div_count = sum(1 for m in members if (m & 3) == 0)
        k1_count = sum(1 for m in members if (m & 3) == 1)
        k2_count = sum(1 for m in members if (m & 3) == 2)
        k3_count = sum(1 for m in members if (m & 3) == 3)
        k_mul_count = k1_count + k2_count + k3_count
        b_cnt = basin_counts[rank_lid]
        b_share = b_cnt / max(1, max_n)
        counts_for_gini.append(b_cnt)

        loops_records.append(
            {
                "loop_id": rank_lid,
                "min_value": lp["min_value"],
                "max_value": lp["max_value"],
                "length": lp["length"],
                "l_div_count": l_div_count,
                "k_mul_count": k_mul_count,
                "k1_count": k1_count,
                "k2_count": k2_count,
                "k3_count": k3_count,
                "basin_count": b_cnt,
                "basin_share": b_share,
                "members": members,
                "elements_json": json.dumps(members),
                "label": format_loop_label(rank_lid, members),
                "color": DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)],
            }
        )

    gini_metrics = compute_gini_metrics(counts_for_gini)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    res: Dict[str, Any] = {
        "p": p,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "q_json": json.dumps(q_norm),
        "gcd_q": gcd_q,
        "n_max": max_n,
        "num_loops": len(loops_records),
        "max_steps": max_obs_steps,
        "max_step_n": max_step_n,
        "avg_steps": round(avg_steps, 4),
        "unresolved_count": unresolved_count,
        "gini": round(gini_metrics["gini"], 6),
        "gini_norm": round(gini_metrics["gini_norm"], 6),
        "hhi": round(gini_metrics["hhi"], 6),
        "shannon_evenness": round(gini_metrics["shannon_evenness"], 6),
        "elapsed_ms": round(elapsed_ms, 2),
        "loops": loops_records,
    }
    if return_points:
        res["points_loop_id"] = pts_lid
        res["points_steps"] = pts_steps
    return res


def save_compressed_trajectory(
    traj_dir: Path,
    q1: int,
    q2: int,
    q3: int,
    pts_lid: List[int],
    pts_steps: List[int],
) -> Path:
    """
    Compress (steps: uint16, loop_id: uint8) arrays for n=1..max_n using zlib
    and save to `data/p5/trajectories/p5_{q1}_{q2}_{q3}.bin.zlib`.
    """
    traj_dir.mkdir(parents=True, exist_ok=True)
    out_path = traj_dir / f"p5_{q1}_{q2}_{q3}.bin.zlib"
    buf = bytearray(len(pts_steps) * 3)
    offset = 0
    for lid, st in zip(pts_lid, pts_steps):
        st_u16 = 65535 if st < 0 else min(st, 65534)
        lid_u8 = min(max(lid, 0), 255)
        struct.pack_into("<HB", buf, offset, st_u16, lid_u8)
        offset += 3
    compressed = zlib.compress(bytes(buf), level=6)
    out_path.write_bytes(compressed)
    return out_path


def render_p5_png(
    result: Dict[str, Any],
    png_path: Path,
) -> None:
    """
    Render lightweight high-definition PNG (1800x1000 px) for (p=5, Q=[_, q1, q2, q3]).
    """
    p = result["p"]
    q1, q2, q3 = result["q1"], result["q2"], result["q3"]
    max_n = result["n_max"]
    loops = result["loops"]
    pts_lid = result["points_loop_id"]
    pts_steps = result["points_steps"]
    max_steps = result["max_steps"]

    xs_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
    ys_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
    unresolved_x: List[int] = []
    unresolved_y: List[int] = []

    for idx, (lid, st) in enumerate(zip(pts_lid, pts_steps), start=1):
        if lid == 0 or st < 0:
            unresolved_x.append(idx)
            unresolved_y.append(0)
        elif lid in xs_by_loop:
            xs_by_loop[lid].append(idx)
            ys_by_loop[lid].append(st)

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif", "STIXGeneral"],
            "mathtext.fontset": "stix",
            "axes.labelsize": 17,
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
        }
    )

    fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=200)
    marker_size = 2.6 if max_n >= 50000 else 4.0
    legend_handles = []

    for lp in loops:
        lid = lp["loop_id"]
        color = lp["color"]
        xs = xs_by_loop[lid]
        ys = ys_by_loop[lid]
        ax.plot(
            xs,
            ys,
            linestyle="none",
            marker="o",
            markersize=marker_size,
            markerfacecolor=color,
            markeredgecolor="none",
            alpha=0.85,
        )
        share_pct = lp["basin_share"] * 100.0
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                label=f"{lp['label']} ({share_pct:.1f}%)",
                markerfacecolor=color,
                markeredgecolor="none",
                markersize=6.5,
            )
        )

    if unresolved_x:
        ax.plot(
            unresolved_x,
            unresolved_y,
            linestyle="none",
            marker="x",
            markersize=marker_size,
            color="#7F7F7F",
            alpha=0.7,
        )
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="x",
                color="none",
                label=f"Unresolved ({len(unresolved_x)})",
                markeredgecolor="#7F7F7F",
                markersize=6.5,
            )
        )

    ax.set_title(
        f"(p, Q) = ({p}, [_, {q1}, {q2}, {q3}])   "
        f"[Loops: {len(loops)}, G*={result['gini_norm']:.3f}, N=1..{max_n:,}]",
        fontsize=14.5,
        fontweight="bold",
        pad=10,
    )

    ax.set_xlabel("N", labelpad=6)
    ax.set_ylabel("iterN", labelpad=6)
    ax.set_xlim(0, max_n)

    num_legend_items = len(legend_handles)
    ncol = 2 if num_legend_items <= 8 else 3
    rows_needed = math.ceil(max(num_legend_items, 1) / ncol)
    headroom_factor = 1.18 + min(rows_needed * 0.055, 0.45)
    y_top = max(int(max_steps * headroom_factor), 50)
    y_top = ((y_top + 49) // 50) * 50
    ax.set_ylim(0, y_top)

    if max_n >= 10 and max_n % 10 == 0:
        ax.xaxis.set_major_locator(MultipleLocator(max_n / 10))
    if max_n >= 10000:
        exp = max(int(math.floor(math.log10(max_n))) - 1, 3)
        formatter = ScalarFormatter(useMathText=True)
        formatter.set_scientific(True)
        formatter.set_powerlimits((exp, exp))
        ax.xaxis.set_major_formatter(formatter)

    ax.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=True,
        length=6,
        width=0.9,
    )
    ax.grid(True, linestyle=":", linewidth=0.6, color="#888888", alpha=0.45)

    if legend_handles:
        max_display = 18
        displayed_handles = legend_handles[:max_display]
        if len(legend_handles) > max_display:
            displayed_handles.append(
                Line2D(
                    [0],
                    [0],
                    color="none",
                    label=f"... +{len(legend_handles) - max_display} more loops",
                )
            )
        font_sz = 9.0 if num_legend_items <= 6 else (7.8 if num_legend_items <= 12 else 6.8)
        ax.legend(
            handles=displayed_handles,
            loc="upper left",
            ncol=ncol,
            fontsize=font_sz,
            frameon=True,
            facecolor="white",
            edgecolor="#cccccc",
            framealpha=0.92,
            columnspacing=1.0,
            handletextpad=0.3,
        )

    fig.subplots_adjust(left=0.085, right=0.975, bottom=0.13, top=0.91)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, format="png", dpi=200)
    plt.close(fig)


def is_interesting_system(result: Dict[str, Any]) -> bool:
    """
    Heuristic to decide whether a (q1, q2, q3) system is 'interesting' enough
    for automatic PNG generation during `--plot-mode interesting`:
      - High loop count (num_loops >= 8)
      - Extremely egalitarian multi-loop CTree (num_loops >= 2 and gini_norm <= 0.12)
      - Extremely unequal multi-loop CTree with many loops (num_loops >= 5 and gini_norm >= 0.92)
      - Very high step height (max_steps >= 450)
      - Baseline cases like (3, 2, 1) or symmetric multiples q1/3 == q2/2 == q3/1
    """
    q1, q2, q3 = result["q1"], result["q2"], result["q3"]
    num_loops = result["num_loops"]
    gini_norm = result["gini_norm"]
    max_steps = result["max_steps"]

    if (q1, q2, q3) == (3, 2, 1):
        return True
    if q1 * 2 == q2 * 3 and q2 == 2 * q3 and q3 <= 25:
        # Pure scalar multiples of (3, 2, 1): k * (3, 2, 1)
        return True
    if num_loops >= 8:
        return True
    if num_loops >= 2 and gini_norm <= 0.12:
        return True
    if num_loops >= 5 and gini_norm >= 0.92:
        return True
    if max_steps >= 450:
        return True
    return False


def worker_task(
    task: Tuple[int, int, int, int, int, str, str, str, bool]
) -> Dict[str, Any]:
    """
    Child process worker for a single (q1, q2, q3) triplet.
    """
    q1, q2, q3, max_n, max_steps, plot_mode, img_dir_str, traj_dir_str, save_compressed = task

    need_points = (plot_mode in ("all", "interesting")) or save_compressed
    res = evaluate_p5_system(
        q1=q1,
        q2=q2,
        q3=q3,
        max_n=max_n,
        max_steps=max_steps,
        return_points=need_points,
    )

    if save_compressed and "points_loop_id" in res:
        save_compressed_trajectory(
            traj_dir=Path(traj_dir_str),
            q1=q1,
            q2=q2,
            q3=q3,
            pts_lid=res["points_loop_id"],
            pts_steps=res["points_steps"],
        )

    plotted = False
    if plot_mode == "all" or (plot_mode == "interesting" and is_interesting_system(res)):
        png_path = Path(img_dir_str) / f"p5_{q1}_{q2}_{q3}.png"
        render_p5_png(res, png_path)
        plotted = True

    # Strip large point arrays before returning across IPC pipe
    res.pop("points_loop_id", None)
    res.pop("points_steps", None)
    res["plotted"] = plotted
    return res


def init_summary_db(db_path: Path) -> sqlite3.Connection:
    """
    Initialize the single master aggregated SQLite database `summary_p5.db`
    as specified in `docs/HANDOFF.md` Section 5(B).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS systems (
            system_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            p                INTEGER NOT NULL,
            q1               INTEGER NOT NULL,
            q2               INTEGER NOT NULL,
            q3               INTEGER NOT NULL,
            q_json           TEXT    NOT NULL,
            gcd_q            INTEGER NOT NULL,
            n_max            INTEGER NOT NULL,
            num_loops        INTEGER NOT NULL,
            max_steps        INTEGER NOT NULL,
            max_step_n       INTEGER NOT NULL,
            avg_steps        REAL    NOT NULL,
            unresolved_count INTEGER NOT NULL DEFAULT 0,
            gini             REAL    NOT NULL,
            gini_norm        REAL    NOT NULL,
            hhi              REAL    NOT NULL,
            shannon_evenness REAL    NOT NULL,
            elapsed_ms       REAL    NOT NULL,
            UNIQUE (p, q_json)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS loops (
            system_id     INTEGER NOT NULL,
            loop_id       INTEGER NOT NULL,
            min_value     INTEGER NOT NULL,
            max_value     INTEGER NOT NULL,
            length        INTEGER NOT NULL,
            l_div_count   INTEGER NOT NULL,
            k_mul_count   INTEGER NOT NULL,
            k1_count      INTEGER NOT NULL,
            k2_count      INTEGER NOT NULL,
            k3_count      INTEGER NOT NULL,
            basin_count   INTEGER NOT NULL,
            basin_share   REAL    NOT NULL,
            elements_json TEXT    NOT NULL,
            PRIMARY KEY (system_id, loop_id),
            FOREIGN KEY (system_id) REFERENCES systems(system_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_systems_q ON systems(q1, q2, q3);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_systems_gcd ON systems(gcd_q);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_systems_loops ON systems(num_loops);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_loops_len ON loops(length, l_div_count, k_mul_count);")
    return conn


def get_completed_keys(conn: sqlite3.Connection, max_n: int) -> Set[Tuple[int, int, int]]:
    cur = conn.execute(
        "SELECT q1, q2, q3 FROM systems WHERE p = ? AND n_max >= ?",
        (P_VAL, max_n),
    )
    return {(int(r[0]), int(r[1]), int(r[2])) for r in cur.fetchall()}


def flush_batch_to_db(conn: sqlite3.Connection, batch_results: List[Dict[str, Any]]) -> None:
    if not batch_results:
        return
    with conn:
        for res in batch_results:
            # Upsert system record
            conn.execute(
                """
                INSERT INTO systems (
                    p, q1, q2, q3, q_json, gcd_q, n_max, num_loops,
                    max_steps, max_step_n, avg_steps, unresolved_count,
                    gini, gini_norm, hhi, shannon_evenness, elapsed_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(p, q_json) DO UPDATE SET
                    n_max            = excluded.n_max,
                    num_loops        = excluded.num_loops,
                    max_steps        = excluded.max_steps,
                    max_step_n       = excluded.max_step_n,
                    avg_steps        = excluded.avg_steps,
                    unresolved_count = excluded.unresolved_count,
                    gini             = excluded.gini,
                    gini_norm        = excluded.gini_norm,
                    hhi              = excluded.hhi,
                    shannon_evenness = excluded.shannon_evenness,
                    elapsed_ms       = excluded.elapsed_ms
                """,
                (
                    res["p"],
                    res["q1"],
                    res["q2"],
                    res["q3"],
                    res["q_json"],
                    res["gcd_q"],
                    res["n_max"],
                    res["num_loops"],
                    res["max_steps"],
                    res["max_step_n"],
                    res["avg_steps"],
                    res["unresolved_count"],
                    res["gini"],
                    res["gini_norm"],
                    res["hhi"],
                    res["shannon_evenness"],
                    res["elapsed_ms"],
                ),
            )
            row = conn.execute(
                "SELECT system_id FROM systems WHERE p = ? AND q_json = ?",
                (res["p"], res["q_json"]),
            ).fetchone()
            sys_id = int(row[0])

            conn.execute("DELETE FROM loops WHERE system_id = ?", (sys_id,))
            conn.executemany(
                """
                INSERT INTO loops (
                    system_id, loop_id, min_value, max_value, length,
                    l_div_count, k_mul_count, k1_count, k2_count, k3_count,
                    basin_count, basin_share, elements_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sys_id,
                        lp["loop_id"],
                        lp["min_value"],
                        lp["max_value"],
                        lp["length"],
                        lp["l_div_count"],
                        lp["k_mul_count"],
                        lp["k1_count"],
                        lp["k2_count"],
                        lp["k3_count"],
                        lp["basin_count"],
                        lp["basin_share"],
                        lp["elements_json"],
                    )
                    for lp in res["loops"]
                ],
            )


def export_csvs_from_db(
    conn: sqlite3.Connection,
    summary_csv_path: Path,
    loops_csv_path: Optional[Path] = None,
) -> None:
    """
    Export `summary_p5.csv` (and optionally `loops_p5.csv`) directly from `summary_p5.db`.
    """
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)
    sys_rows = conn.execute(
        """
        SELECT system_id, p, q1, q2, q3, gcd_q, n_max, num_loops,
               max_steps, max_step_n, avg_steps, unresolved_count,
               gini, gini_norm, hhi, shannon_evenness, elapsed_ms
        FROM systems
        ORDER BY q1, q2, q3
        """
    ).fetchall()

    # Fetch loop lengths per system for summary column
    loop_len_map: Dict[int, List[str]] = {}
    loop_share_map: Dict[int, float] = {}
    for sys_id, length, b_share in conn.execute(
        "SELECT system_id, length, basin_share FROM loops ORDER BY system_id, loop_id"
    ):
        sid = int(sys_id)
        loop_len_map.setdefault(sid, []).append(str(length))
        if b_share > loop_share_map.get(sid, 0.0):
            loop_share_map[sid] = float(b_share)

    with summary_csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "system_id",
                "p",
                "q1",
                "q2",
                "q3",
                "gcd_q",
                "n_max",
                "num_loops",
                "dominant_share_pct",
                "gini",
                "gini_norm",
                "hhi",
                "shannon_evenness",
                "max_steps",
                "max_step_n",
                "avg_steps",
                "unresolved_count",
                "elapsed_ms",
                "loop_lengths",
            ]
        )
        for row in sys_rows:
            sid = int(row[0])
            dom_pct = loop_share_map.get(sid, 0.0) * 100.0
            lens_str = ";".join(loop_len_map.get(sid, []))
            writer.writerow(
                [
                    sid,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    f"{dom_pct:.2f}",
                    f"{row[12]:.4f}",
                    f"{row[13]:.4f}",
                    f"{row[14]:.4f}",
                    f"{row[15]:.4f}",
                    row[8],
                    row[9],
                    f"{row[10]:.2f}",
                    row[11],
                    f"{row[16]:.1f}",
                    lens_str,
                ]
            )

    if loops_csv_path is not None:
        loops_csv_path.parent.mkdir(parents=True, exist_ok=True)
        loop_rows = conn.execute(
            """
            SELECT s.system_id, s.q1, s.q2, s.q3, s.gcd_q,
                   l.loop_id, l.min_value, l.max_value, l.length,
                   l.l_div_count, l.k_mul_count, l.k1_count, l.k2_count, l.k3_count,
                   l.basin_count, l.basin_share, l.elements_json
            FROM loops l
            JOIN systems s ON s.system_id = l.system_id
            ORDER BY s.q1, s.q2, s.q3, l.loop_id
            """
        ).fetchall()
        with loops_csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "system_id",
                    "q1",
                    "q2",
                    "q3",
                    "gcd_q",
                    "loop_id",
                    "min_value",
                    "max_value",
                    "length",
                    "l_div_count",
                    "k_mul_count",
                    "k1_count",
                    "k2_count",
                    "k3_count",
                    "basin_count",
                    "basin_share_pct",
                    "elements_preview",
                ]
            )
            for r in loop_rows:
                elems = json.loads(r[16])
                writer.writerow(
                    [
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        r[6],
                        r[7],
                        r[8],
                        r[9],
                        r[10],
                        r[11],
                        r[12],
                        r[13],
                        r[14],
                        f"{float(r[15]) * 100.0:.2f}",
                        json.dumps(elems[:8]),
                    ]
                )


def run_batch_p5(
    q1_list: Optional[List[int]] = None,
    q2_list: Optional[List[int]] = None,
    q3_list: Optional[List[int]] = None,
    max_n: int = 100000,
    max_steps: int = 10000,
    db_path: Path = DEFAULT_DB_PATH,
    csv_path: Path = DEFAULT_CSV_PATH,
    loops_csv_path: Optional[Path] = DEFAULT_LOOPS_CSV_PATH,
    img_dir: Path = DEFAULT_IMG_DIR,
    traj_dir: Path = DEFAULT_TRAJ_DIR,
    plot_mode: str = "interesting",
    save_compressed_nodes: bool = False,
    workers: int = 0,
    force_recompute: bool = False,
) -> Dict[Tuple[int, int, int], int]:
    """
    Run the 3D grid evaluation across all (q1, q2, q3) combinations for p=5
    and store results into the single master DB `summary_p5.db`.
    """
    if q1_list is None:
        q1_list = [4 * k + 3 for k in range(DEFAULT_LIMIT_Q)]
    if q2_list is None:
        q2_list = [4 * k + 2 for k in range(DEFAULT_LIMIT_Q)]
    if q3_list is None:
        q3_list = [4 * k + 1 for k in range(DEFAULT_LIMIT_Q)]

    conn = init_summary_db(db_path)
    completed_keys = set() if force_recompute else get_completed_keys(conn, max_n)

    tasks: List[Tuple[int, int, int, int, int, str, str, str, bool]] = []
    for q1 in q1_list:
        for q2 in q2_list:
            for q3 in q3_list:
                v = validate_pq(P_VAL, [None, q1, q2, q3])
                if not v["strictly_divisible"]:
                    raise ValueError(f"Invalid (q1={q1}, q2={q2}, q3={q3}): {v['warnings']}")
                if (q1, q2, q3) in completed_keys:
                    continue
                tasks.append(
                    (
                        q1,
                        q2,
                        q3,
                        max_n,
                        max_steps,
                        plot_mode,
                        str(img_dir),
                        str(traj_dir),
                        save_compressed_nodes,
                    )
                )

    total_grid = len(q1_list) * len(q2_list) * len(q3_list)
    remaining_tasks = len(tasks)
    if workers <= 0:
        workers = max(1, (os.cpu_count() or 4) - 1)

    print(
        f"=== Starting (p=5, Q=[_, q1, q2, q3]) Batch Run: "
        f"{len(q1_list)}x{len(q2_list)}x{len(q3_list)} = {total_grid:,} systems ==="
    )
    print(f"Initial values N   : 1 .. {max_n:,}")
    print(f"Master SQLite DB   : {db_path.resolve()}")
    print(f"Summary CSV path   : {csv_path.resolve()}")
    print(f"Plot mode          : {plot_mode} (Images dir: {img_dir.resolve()})")
    print(f"Already completed  : {len(completed_keys):,} / {total_grid:,} (Remaining: {remaining_tasks:,})")
    print(f"Parallel workers   : {workers}")

    t_start = time.perf_counter()
    completed_now = 0
    plotted_count = 0
    pending_db_buffer: List[Dict[str, Any]] = []
    flush_interval = 100

    if remaining_tasks > 0:
        if workers == 1:
            for t in tasks:
                res = worker_task(t)
                pending_db_buffer.append(res)
                completed_now += 1
                if res.get("plotted"):
                    plotted_count += 1
                if len(pending_db_buffer) >= flush_interval or completed_now == remaining_tasks:
                    flush_batch_to_db(conn, pending_db_buffer)
                    pending_db_buffer.clear()
                    elapsed = time.perf_counter() - t_start
                    rate = completed_now / max(elapsed, 1e-6)
                    eta = (remaining_tasks - completed_now) / max(rate, 1e-6)
                    print(
                        f"[{completed_now:5d}/{remaining_tasks}] p5_{res['q1']}_{res['q2']}_{res['q3']} "
                        f"-> {res['num_loops']} loops, G*={res['gini_norm']:.3f} "
                        f"| Rate: {rate:.1f} sys/s | ETA: {eta:.1f}s"
                    )
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(worker_task, t) for t in tasks]
                for fut in as_completed(futures):
                    res = fut.result()
                    pending_db_buffer.append(res)
                    completed_now += 1
                    if res.get("plotted"):
                        plotted_count += 1
                    if len(pending_db_buffer) >= flush_interval or completed_now == remaining_tasks:
                        flush_batch_to_db(conn, pending_db_buffer)
                        pending_db_buffer.clear()
                        elapsed = time.perf_counter() - t_start
                        rate = completed_now / max(elapsed, 1e-6)
                        eta = (remaining_tasks - completed_now) / max(rate, 1e-6)
                        print(
                            f"[{completed_now:5d}/{remaining_tasks}] p5_{res['q1']}_{res['q2']}_{res['q3']} "
                            f"-> {res['num_loops']} loops, G*={res['gini_norm']:.3f} "
                            f"| Plotted: {plotted_count} | Rate: {rate:.1f} sys/s | ETA: {eta:.1f}s"
                        )

    export_csvs_from_db(conn, csv_path, loops_csv_path)

    # Fetch loop counts map to return
    loop_counts: Dict[Tuple[int, int, int], int] = {}
    for q1, q2, q3, n_loops in conn.execute("SELECT q1, q2, q3, num_loops FROM systems WHERE p = ?", (P_VAL,)):
        loop_counts[(int(q1), int(q2), int(q3))] = int(n_loops)

    conn.close()
    total_time = time.perf_counter() - t_start
    db_size_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0.0
    print(f"=== Completed {total_grid:,} systems in {total_time:.2f}s ===")
    print(f"Master DB saved to : {db_path} ({db_size_mb:.2f} MB)")
    print(f"Summary CSV saved  : {csv_path}")
    if loops_csv_path:
        print(f"Loops CSV saved    : {loops_csv_path}")
    print(f"PNG plots rendered : {plotted_count} files in {img_dir}")
    return loop_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run disk-efficient (p=5, Q=[_, q1, q2, q3]) batch analysis into data/p5/summary_p5.db."
    )
    parser.add_argument(
        "-n",
        "--max-n",
        type=int,
        default=100000,
        help="Maximum initial value N to test per (q1, q2, q3) system (default: 100000).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10000,
        help="Max step limit before marking trajectory unresolved (default: 10000).",
    )
    parser.add_argument(
        "--limit-q",
        type=int,
        default=DEFAULT_LIMIT_Q,
        help="Default grid size per axis (default: 20 -> 20x20x20 = 8,000 systems).",
    )
    parser.add_argument(
        "--limit-q1",
        type=int,
        default=None,
        help="Override number of q1 values (default: uses --limit-q).",
    )
    parser.add_argument(
        "--limit-q2",
        type=int,
        default=None,
        help="Override number of q2 values (default: uses --limit-q).",
    )
    parser.add_argument(
        "--limit-q3",
        type=int,
        default=None,
        help="Override number of q3 values (default: uses --limit-q).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to the master aggregated SQLite DB (default: data/p5/summary_p5.db).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Path to the summary CSV output (default: data/p5/summary_p5.csv).",
    )
    parser.add_argument(
        "--loops-csv",
        type=Path,
        default=DEFAULT_LOOPS_CSV_PATH,
        help="Path to the loops catalog CSV output (default: data/p5/loops_p5.csv).",
    )
    parser.add_argument(
        "--img-dir",
        type=Path,
        default=DEFAULT_IMG_DIR,
        help="Directory for PNG plots (default: data/p5/Images).",
    )
    parser.add_argument(
        "--traj-dir",
        type=Path,
        default=DEFAULT_TRAJ_DIR,
        help="Directory for optional zlib-compressed node blobs (default: data/p5/trajectories).",
    )
    parser.add_argument(
        "--plot-mode",
        choices=["none", "interesting", "all"],
        default="interesting",
        help="PNG plotting policy: 'none' (no plots), 'interesting' (default, notable Q only), or 'all'.",
    )
    parser.add_argument(
        "--save-compressed-nodes",
        action="store_true",
        help="Save zlib-compressed (steps, loop_id) binary blobs in data/p5/trajectories/.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Number of parallel worker processes (0 = auto).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recomputation even if systems already exist in summary_p5.db.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lq1 = args.limit_q1 if args.limit_q1 is not None else args.limit_q
    lq2 = args.limit_q2 if args.limit_q2 is not None else args.limit_q
    lq3 = args.limit_q3 if args.limit_q3 is not None else args.limit_q
    q1_list, q2_list, q3_list = build_q_lists(lq1, lq2, lq3)

    run_batch_p5(
        q1_list=q1_list,
        q2_list=q2_list,
        q3_list=q3_list,
        max_n=args.max_n,
        max_steps=args.max_steps,
        db_path=args.db,
        csv_path=args.csv,
        loops_csv_path=args.loops_csv,
        img_dir=args.img_dir,
        traj_dir=args.traj_dir,
        plot_mode=args.plot_mode,
        save_compressed_nodes=args.save_compressed_nodes,
        workers=args.workers,
        force_recompute=args.force,
    )


if __name__ == "__main__":
    main()

