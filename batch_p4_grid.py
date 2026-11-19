#!/usr/bin/env python3
"""
Batch 30x30 Grid Runner for (p, Q) = (4, [_, q1, q2]).

Requirements (docs/2026_1031/request.txt):
- Leverages the project's backend engine & SQLite schema.
- Evaluates (p, Q) = (4, [_, q1, q2]) for:
    - Horizontal header (columns): q1 in [2, 5, 8, 11, ..., 89] (30 values)
    - Vertical header (rows):      q2 in [1, 4, 7, 10, ..., 88] (30 values)
- Tests initial values n = 1 .. 100,000 for each (q1, q2) pair to detect loops.
- Saves 900 independent SQLite database files in `DB/`:
    `DB/p4_{q1}_{q2}.db` (e.g., `DB/p4_2_1.db`)
- Saves 900 PNG (1800x1000) and 900 SVG plots in `Images/`:
    `Images/p4_{q1}_{q2}.png` and `Images/p4_{q1}_{q2}.svg`
  with the (p, Q) parameters and the loop legend displayed at the top.
- Outputs a 30x30 CSV file for spreadsheet import containing the number of
  loops for each (q1, q2) cell.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator, ScalarFormatter

from backend.engine import (
    DEFAULT_PALETTE,
    canonicalize_cycle,
    format_loop_label,
    step_pq,
    validate_pq,
)
from backend.logger import get_logger

logger = get_logger("batch_p4")

P_VAL = 4
D_VAL = P_VAL - 1  # 3

DEFAULT_Q1_LIST = list(range(2, 90, 3))  # 2, 5, 8, ..., 89 (30 values)
DEFAULT_Q2_LIST = list(range(1, 89, 3))  # 1, 4, 7, ..., 88 (30 values)

DEFAULT_DB_DIR = Path("DB")
DEFAULT_IMG_DIR = Path("Images")
DEFAULT_CSV_PATH = Path("outputs/p4_loop_counts_30x30.csv")


def compute_and_save_single_db(
    db_path: Path,
    p: int,
    q1: int,
    q2: int,
    max_n: int,
    max_steps: int,
) -> Dict[str, Any]:
    """
    Compute (p=4, Q=[None, q1, q2]) for n = 1..max_n and persist into an
    independent single-file SQLite database `db_path` using the backend schema.
    """
    q_norm: List[Optional[int]] = [None, q1, q2]
    d = p - 1

    # Check if DB already exists and is complete (for fast resume)
    if db_path.exists() and db_path.stat().st_size > 0:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.execute(
                "SELECT system_id, max_computed_n FROM systems WHERE p = ? AND q_json = ?",
                (p, json.dumps(q_norm)),
            )
            row = cur.fetchone()
            if row and int(row[1]) >= max_n:
                sys_id = int(row[0])
                loops_raw = conn.execute(
                    "SELECT loop_id, min_value, length, members_json FROM loops WHERE system_id = ? ORDER BY min_value",
                    (sys_id,),
                ).fetchall()
                loops_list = []
                for idx, (lid, min_v, length, m_json) in enumerate(loops_raw):
                    members = json.loads(m_json)
                    loops_list.append(
                        {
                            "loop_id": int(lid),
                            "rank": idx + 1,
                            "min_value": int(min_v),
                            "length": int(length),
                            "members": members,
                            "label": format_loop_label(idx + 1, members),
                            "color": DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)],
                        }
                    )
                pts_rows = conn.execute(
                    "SELECT n, loop_id, steps FROM steps_cache WHERE system_id = ? AND n <= ? ORDER BY n",
                    (sys_id, max_n),
                ).fetchall()
                conn.close()
                if len(pts_rows) == max_n:
                    pts_n = [r[0] for r in pts_rows]
                    pts_lid = [r[1] for r in pts_rows]
                    pts_steps = [r[2] for r in pts_rows]
                    max_obs = max((s for s in pts_steps if s >= 0), default=0)
                    return {
                        "q1": q1,
                        "q2": q2,
                        "num_loops": len(loops_list),
                        "loops": loops_list,
                        "points_n": pts_n,
                        "points_loop_id": pts_lid,
                        "points_steps": pts_steps,
                        "max_observed_steps": max_obs,
                        "resumed": True,
                    }
            conn.close()
        except Exception:
            # If existing file was partial/corrupted, recreate it cleanly
            try:
                db_path.unlink()
            except OSError:
                pass

    # Evaluate trajectories in memory first for maximum speed
    steps_cache: Dict[int, Tuple[int, int, int]] = {}  # n -> (next_n, loop_id, steps)
    loops_by_min: Dict[int, Dict[str, Any]] = {}  # min_val -> loop info
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
            r = curr % d
            curr = (curr // d) if r == 0 else (p * curr + (q1 if r == 1 else q2))

        if curr in steps_cache:
            _, target_lid, base_steps = steps_cache[curr]
            path_len = len(path)
            if target_lid == 0 or base_steps < 0:
                for idx, val in enumerate(path):
                    nxt = path[idx + 1] if idx + 1 < path_len else curr
                    steps_cache[val] = (nxt, 0, -1)
            else:
                for idx, val in enumerate(path):
                    st = base_steps + (path_len - idx)
                    nxt = path[idx + 1] if idx + 1 < path_len else curr
                    steps_cache[val] = (nxt, target_lid, st)
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
                    "loop_id": lid,
                    "min_value": min_val,
                    "length": cycle_len,
                    "members": canonical_members,
                }
            else:
                lid = loops_by_min[min_val]["loop_id"]

            for i, val in enumerate(raw_cycle):
                nxt = raw_cycle[(i + 1) % cycle_len]
                steps_cache[val] = (nxt, lid, 0)

            for idx in range(cycle_start):
                val = path[idx]
                nxt = path[idx + 1]
                st = cycle_start - idx
                steps_cache[val] = (nxt, lid, st)
        else:
            # Exceeded max_steps
            nxt_first = path[1] if len(path) > 1 else curr
            steps_cache[start_n] = (nxt_first, 0, -1)

    # Persist to single-file SQLite DB (`DB/p4_{q1}_{q2}.db`)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass

    conn = sqlite3.connect(db_path)
    try:
        # Use MEMORY journal + synchronous OFF during initial bulk load so no -wal/-shm files remain
        conn.execute("PRAGMA synchronous = OFF;")
        conn.execute("PRAGMA journal_mode = MEMORY;")
        conn.execute(
            """
            CREATE TABLE systems (
                system_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                p              INTEGER NOT NULL,
                q_json         TEXT    NOT NULL,
                max_computed_n INTEGER NOT NULL DEFAULT 0,
                UNIQUE (p, q_json)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE loops (
                system_id    INTEGER NOT NULL,
                loop_id      INTEGER NOT NULL,
                min_value    INTEGER NOT NULL,
                length       INTEGER NOT NULL,
                members_json TEXT    NOT NULL,
                PRIMARY KEY (system_id, loop_id),
                UNIQUE (system_id, min_value),
                FOREIGN KEY (system_id) REFERENCES systems(system_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE steps_cache (
                system_id INTEGER NOT NULL,
                n         INTEGER NOT NULL,
                next_n    INTEGER NOT NULL,
                loop_id   INTEGER NOT NULL,
                steps     INTEGER NOT NULL,
                PRIMARY KEY (system_id, n),
                FOREIGN KEY (system_id) REFERENCES systems(system_id)
            );
            """
        )

        with conn:
            conn.execute(
                "INSERT INTO systems (system_id, p, q_json, max_computed_n) VALUES (1, ?, ?, ?)",
                (p, json.dumps(q_norm), max_n),
            )
            conn.executemany(
                "INSERT INTO loops (system_id, loop_id, min_value, length, members_json) VALUES (1, ?, ?, ?, ?)",
                [
                    (
                        lp["loop_id"],
                        lp["min_value"],
                        lp["length"],
                        json.dumps(lp["members"]),
                    )
                    for lp in loops_by_min.values()
                ],
            )
            conn.executemany(
                "INSERT INTO steps_cache (system_id, n, next_n, loop_id, steps) VALUES (1, ?, ?, ?, ?)",
                [(n_val, nxt, lid, st) for n_val, (nxt, lid, st) in steps_cache.items()],
            )
    finally:
        conn.close()

    sorted_loops = sorted(loops_by_min.values(), key=lambda x: x["min_value"])
    loops_summary = []
    for idx, lp in enumerate(sorted_loops):
        loops_summary.append(
            {
                "loop_id": lp["loop_id"],
                "rank": idx + 1,
                "min_value": lp["min_value"],
                "length": lp["length"],
                "members": lp["members"],
                "label": format_loop_label(idx + 1, lp["members"]),
                "color": DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)],
            }
        )

    pts_n: List[int] = []
    pts_lid: List[int] = []
    pts_steps: List[int] = []
    max_obs = 0

    for n_val in range(1, max_n + 1):
        _, lid, st = steps_cache[n_val]
        pts_n.append(n_val)
        pts_lid.append(lid)
        pts_steps.append(st)
        if st > max_obs:
            max_obs = st

    return {
        "q1": q1,
        "q2": q2,
        "num_loops": len(loops_summary),
        "loops": loops_summary,
        "points_n": pts_n,
        "points_loop_id": pts_lid,
        "points_steps": pts_steps,
        "max_observed_steps": max_obs,
        "resumed": False,
    }


def render_pair_images(
    result: Dict[str, Any],
    p: int,
    max_n: int,
    png_path: Path,
    svg_path: Path,
) -> None:
    """
    Generate both `Images/p4_{q1}_{q2}.png` (1800x1000) and `Images/p4_{q1}_{q2}.svg`
    with (p, Q) header and loop legend at the top.
    """
    q1 = result["q1"]
    q2 = result["q2"]
    loops = result["loops"]
    pts_n = result["points_n"]
    pts_lid = result["points_loop_id"]
    pts_steps = result["points_steps"]
    max_steps = result["max_observed_steps"]

    xs_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
    ys_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
    unresolved_x: List[int] = []
    unresolved_y: List[int] = []

    for n_val, lid, st in zip(pts_n, pts_lid, pts_steps):
        if lid == 0 or st < 0:
            unresolved_x.append(n_val)
            unresolved_y.append(0)
        elif lid in xs_by_loop:
            xs_by_loop[lid].append(n_val)
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

    # 9.0 in * 200 dpi = 1800 px, 5.0 in * 200 dpi = 1000 px
    fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=200)

    marker_size = 2.6 if max_n >= 50000 else 4.0
    legend_handles = []

    for lp in loops:
        lid = lp["loop_id"]
        color = lp["color"]
        xs = xs_by_loop[lid]
        ys = ys_by_loop[lid]
        # Use ax.plot with marker='.' and linestyle='none' for fast, clean rendering
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
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                label=lp["label"],
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

    # Top title displaying (p, Q) and total loop count
    ax.set_title(
        f"(p, Q) = ({p}, [_, {q1}, {q2}])    [Loops: {len(loops)},  N = 1..{max_n:,}]",
        fontsize=15,
        fontweight="bold",
        pad=10,
    )

    ax.set_xlabel("N", labelpad=6)
    ax.set_ylabel("iterN", labelpad=6)
    ax.set_xlim(0, max_n)

    # Add vertical headroom at top of plot so the loop legend fits cleanly
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

    # Place loop legend in the upper area of the plot
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
        font_sz = 9.5 if num_legend_items <= 6 else (8.2 if num_legend_items <= 12 else 7.2)
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
    svg_path.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(png_path, format="png", dpi=200)
    fig.savefig(svg_path, format="svg")
    plt.close(fig)


def process_one_pair(task: Tuple[int, int, int, int, str, str, bool]) -> Tuple[int, int, int, float, bool]:
    """
    Worker function executed in child process for a single (q1, q2) pair.
    Returns (q1, q2, num_loops, elapsed_sec, resumed).
    """
    q1, q2, max_n, max_steps, db_dir_str, img_dir_str, skip_images = task
    t0 = time.perf_counter()

    stem = f"p{P_VAL}_{q1}_{q2}"
    db_path = Path(db_dir_str) / f"{stem}.db"
    png_path = Path(img_dir_str) / f"{stem}.png"
    svg_path = Path(img_dir_str) / f"{stem}.svg"

    res = compute_and_save_single_db(
        db_path=db_path,
        p=P_VAL,
        q1=q1,
        q2=q2,
        max_n=max_n,
        max_steps=max_steps,
    )

    if not skip_images:
        if not (res["resumed"] and png_path.exists() and svg_path.exists()):
            render_pair_images(
                result=res,
                p=P_VAL,
                max_n=max_n,
                png_path=png_path,
                svg_path=svg_path,
            )

    elapsed = time.perf_counter() - t0
    return q1, q2, res["num_loops"], elapsed, res["resumed"]


def write_grid_csv(
    csv_path: Path,
    q1_list: List[int],
    q2_list: List[int],
    loop_counts: Dict[Tuple[int, int], int],
) -> None:
    """
    Write the 30x30 spreadsheet CSV table:
      - First row (horizontal header): ["q2 \\ q1", 2, 5, 8, ..., 89]
      - Each subsequent row: [q2_val, count(q1=2, q2), count(q1=5, q2), ...]
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["q2 \\ q1"] + [str(q1) for q1 in q1_list])
        for q2 in q2_list:
            row = [str(q2)]
            for q1 in q1_list:
                val = loop_counts.get((q1, q2), "")
                row.append(str(val) if val != "" else "")
            writer.writerow(row)


def run_batch(
    q1_list: List[int] = DEFAULT_Q1_LIST,
    q2_list: List[int] = DEFAULT_Q2_LIST,
    max_n: int = 100000,
    max_steps: int = 10000,
    db_dir: Path = DEFAULT_DB_DIR,
    img_dir: Path = DEFAULT_IMG_DIR,
    csv_path: Path = DEFAULT_CSV_PATH,
    workers: int = 0,
    skip_images: bool = False,
) -> Dict[Tuple[int, int], int]:
    """Run the full grid evaluation across all (q1, q2) combinations."""
    db_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    tasks: List[Tuple[int, int, int, int, str, str, bool]] = []
    for q2 in q2_list:
        for q1 in q1_list:
            v = validate_pq(P_VAL, [None, q1, q2])
            if not v["strictly_divisible"]:
                raise ValueError(f"Invalid (q1={q1}, q2={q2}): {v['warnings']}")
            tasks.append((q1, q2, max_n, max_steps, str(db_dir), str(img_dir), skip_images))

    total_tasks = len(tasks)
    if workers <= 0:
        workers = max(1, (os.cpu_count() or 4) - 1)

    logger.info(
        "Starting p=4 batch grid run: %d x %d = %d pairs, max_n=%d, workers=%d, db_dir=%s, img_dir=%s",
        len(q1_list),
        len(q2_list),
        total_tasks,
        max_n,
        workers,
        db_dir,
        img_dir,
    )
    print(
        f"=== Starting (p=4, Q=[_, q1, q2]) Batch Run: {len(q1_list)}x{len(q2_list)} = {total_tasks} pairs ==="
    )
    print(f"Initial values N : 1 .. {max_n:,}")
    print(f"DB directory     : {db_dir.resolve()}")
    print(f"Images directory : {img_dir.resolve()}")
    print(f"CSV output path  : {csv_path.resolve()}")
    print(f"Parallel workers : {workers}")

    t_start = time.perf_counter()
    loop_counts: Dict[Tuple[int, int], int] = {}
    completed = 0

    if workers == 1:
        for t in tasks:
            q1, q2, n_loops, elapsed, resumed = process_one_pair(t)
            loop_counts[(q1, q2)] = n_loops
            completed += 1
            if completed % 10 == 0 or completed == total_tasks:
                write_grid_csv(csv_path, q1_list, q2_list, loop_counts)
                print(
                    f"[{completed}/{total_tasks}] p4_{q1}_{q2}: {n_loops} loops ({elapsed:.2f}s)"
                )
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_pair = {executor.submit(process_one_pair, t): (t[0], t[1]) for t in tasks}
            for fut in as_completed(future_to_pair):
                q1, q2, n_loops, elapsed, resumed = fut.result()
                loop_counts[(q1, q2)] = n_loops
                completed += 1
                logger.info(
                    "Progress [%d/%d] p4_%d_%d -> loops=%d (%.2fs, resumed=%s)",
                    completed,
                    total_tasks,
                    q1,
                    q2,
                    n_loops,
                    elapsed,
                    resumed,
                )
                if completed % 25 == 0 or completed == total_tasks:
                    write_grid_csv(csv_path, q1_list, q2_list, loop_counts)
                    total_elapsed = time.perf_counter() - t_start
                    rate = completed / max(total_elapsed, 1e-6)
                    eta = (total_tasks - completed) / max(rate, 1e-6)
                    print(
                        f"[{completed:3d}/{total_tasks}] p4_{q1}_{q2} -> {n_loops} loops "
                        f"| Elapsed: {total_elapsed:.1f}s | ETA: {eta:.1f}s"
                    )

    write_grid_csv(csv_path, q1_list, q2_list, loop_counts)
    # Also write a copy in the root directory for convenience
    root_csv = Path("p4_loop_counts_30x30.csv")
    if csv_path.resolve() != root_csv.resolve():
        write_grid_csv(root_csv, q1_list, q2_list, loop_counts)

    total_time = time.perf_counter() - t_start
    logger.info(
        "Completed p=4 batch grid run (%d pairs) in %.2f seconds. CSV saved to %s",
        total_tasks,
        total_time,
        csv_path,
    )
    print(f"=== Completed {total_tasks} pairs in {total_time:.2f}s ===")
    print(f"CSV saved to: {csv_path} (and {root_csv})")
    return loop_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 30x30 (p=4, Q=[_, q1, q2]) batch analysis, DB creation, plotting, and CSV generation."
    )
    parser.add_argument(
        "-n",
        "--max-n",
        type=int,
        default=100000,
        help="Maximum initial value N to test per (q1, q2) pair (default: 100000).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10000,
        help="Max step limit before marking trajectory unresolved (default: 10000).",
    )
    parser.add_argument(
        "--db-dir",
        type=Path,
        default=DEFAULT_DB_DIR,
        help="Directory to store the 900 SQLite .db files (default: DB).",
    )
    parser.add_argument(
        "--img-dir",
        type=Path,
        default=DEFAULT_IMG_DIR,
        help="Directory to store the PNG and SVG plot files (default: Images).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Path for the output 30x30 CSV file (default: outputs/p4_loop_counts_30x30.csv).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Number of parallel worker processes (0 = auto).",
    )
    parser.add_argument(
        "--limit-q1",
        type=int,
        default=30,
        help="Number of q1 values to process (default: 30 -> 2, 5, ..., 89).",
    )
    parser.add_argument(
        "--limit-q2",
        type=int,
        default=30,
        help="Number of q2 values to process (default: 30 -> 1, 4, ..., 88).",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Only generate SQLite DBs and CSV, skipping PNG/SVG rendering.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    q1_list = DEFAULT_Q1_LIST[: args.limit_q1]
    q2_list = DEFAULT_Q2_LIST[: args.limit_q2]
    run_batch(
        q1_list=q1_list,
        q2_list=q2_list,
        max_n=args.max_n,
        max_steps=args.max_steps,
        db_dir=args.db_dir,
        img_dir=args.img_dir,
        csv_path=args.csv,
        workers=args.workers,
        skip_images=args.skip_images,
    )


if __name__ == "__main__":
    main()

