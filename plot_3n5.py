#!/usr/bin/env python3
"""
3n+5 Problem (Generalized Collatz) Step Counter & Plotter.

- Computes the number of steps for each starting integer n (1..max_n) to reach
  any of the cycles (loops) in the 3n+5 system:
    - Even: n -> n // 2
    - Odd:  n -> 3n + 5
- Dynamically identifies and records cycles during trajectory evaluation.
- Persists discovered loops and all evaluated values (initial & intermediate)
  in an SQLite database (outputs/collatz_3n5.db) and reuses them to avoid
  redundant computation.
- Outputs a 6-color scatter plot as both a 1800x1000 PNG and a zoomable SVG.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Tuple

import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, ScalarFormatter


DEFAULT_DB_PATH = Path("outputs/collatz_3n5.db")
DEFAULT_PNG_PATH = Path("outputs/iter_3n5.png")
DEFAULT_SVG_PATH = Path("outputs/iter_3n5.svg")


def next_3n5(n: int) -> int:
    """Perform one step of the 3n+5 operation."""
    return (n >> 1) if (n & 1) == 0 else (3 * n + 5)


def canonicalize_cycle(cycle: List[int]) -> List[int]:
    """Rotate a cycle list so that its minimum element comes first."""
    min_val = min(cycle)
    min_idx = cycle.index(min_val)
    return cycle[min_idx:] + cycle[:min_idx]


def format_loop_label(loop_id: int, members: List[int]) -> str:
    """Format a human-readable legend label for a loop."""
    length = len(members)
    if length <= 8:
        seq_str = "[" + ", ".join(str(x) for x in members) + "]"
    else:
        head = ", ".join(str(x) for x in members[:3])
        tail = str(members[-1])
        seq_str = f"[{head}, ..., {tail}]"
    return f"Loop {loop_id} (len={length}): {seq_str}"


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize SQLite schema and performance PRAGMAs."""
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -64000;")  # ~64MB page cache

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS loops (
            loop_id      INTEGER PRIMARY KEY,
            min_value    INTEGER NOT NULL UNIQUE,
            length       INTEGER NOT NULL,
            members_json TEXT    NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS steps_cache (
            n       INTEGER PRIMARY KEY,
            next_n  INTEGER NOT NULL,
            loop_id INTEGER NOT NULL,
            steps   INTEGER NOT NULL,
            FOREIGN KEY (loop_id) REFERENCES loops(loop_id)
        );
        """
    )
    conn.commit()


def load_cache_from_db(
    conn: sqlite3.Connection,
) -> Tuple[Dict[int, Dict], Dict[int, Tuple[int, int]]]:
    """
    Load known loops and cached node results from SQLite into memory.

    Returns:
        loops_by_id: {loop_id: {"loop_id": int, "min_value": int, "length": int, "members": list[int]}}
        cache: {n: (loop_id, steps)}
    """
    loops_by_id: Dict[int, Dict] = {}
    cur = conn.execute(
        "SELECT loop_id, min_value, length, members_json FROM loops ORDER BY loop_id"
    )
    for loop_id, min_val, length, members_json in cur:
        loops_by_id[loop_id] = {
            "loop_id": loop_id,
            "min_value": min_val,
            "length": length,
            "members": json.loads(members_json),
        }

    cache: Dict[int, Tuple[int, int]] = {}
    cur = conn.execute("SELECT n, loop_id, steps FROM steps_cache")
    for n, loop_id, steps in cur:
        cache[n] = (loop_id, steps)

    return loops_by_id, cache


def compute_and_persist(
    conn: sqlite3.Connection, max_n: int
) -> Tuple[Dict[int, Dict], Dict[int, Tuple[int, int]], int, int]:
    """
    Compute 3n+5 steps for 1..max_n using existing SQLite data + in-memory memoization,
    then bulk-save any newly discovered loops and evaluated numbers back to SQLite.
    """
    loops_by_id, cache = load_cache_from_db(conn)
    new_loops: List[Tuple[int, int, int, str]] = []
    new_nodes: List[Tuple[int, int, int, int]] = []

    next_loop_id = max(loops_by_id.keys(), default=0) + 1

    for start_n in range(1, max_n + 1):
        if start_n in cache:
            continue

        path: List[int] = []
        path_index: Dict[int, int] = {}
        curr = start_n

        while curr not in cache and curr not in path_index:
            path_index[curr] = len(path)
            path.append(curr)
            curr = next_3n5(curr)

        if curr in cache:
            # Hit an already known number: backpropagate steps along path
            target_loop_id, base_steps = cache[curr]
            path_len = len(path)
            for idx, val in enumerate(path):
                steps = base_steps + (path_len - idx)
                nxt = path[idx + 1] if idx + 1 < path_len else curr
                cache[val] = (target_loop_id, steps)
                new_nodes.append((val, nxt, target_loop_id, steps))
        else:
            # Discovered a new cycle starting at path_index[curr]
            cycle_start = path_index[curr]
            raw_cycle = path[cycle_start:]
            canonical_members = canonicalize_cycle(raw_cycle)
            min_val = canonical_members[0]
            cycle_len = len(canonical_members)

            loop_id = next_loop_id
            next_loop_id += 1

            loops_by_id[loop_id] = {
                "loop_id": loop_id,
                "min_value": min_val,
                "length": cycle_len,
                "members": canonical_members,
            }
            new_loops.append(
                (loop_id, min_val, cycle_len, json.dumps(canonical_members))
            )

            # Register all members of the cycle with steps = 0
            for i, val in enumerate(raw_cycle):
                nxt = raw_cycle[(i + 1) % cycle_len]
                cache[val] = (loop_id, 0)
                new_nodes.append((val, nxt, loop_id, 0))

            # Register the pre-period path leading into the cycle
            for idx in range(cycle_start):
                val = path[idx]
                nxt = path[idx + 1]
                steps = cycle_start - idx
                cache[val] = (loop_id, steps)
                new_nodes.append((val, nxt, loop_id, steps))

    # Persist new loops and nodes in a single transaction
    if new_loops or new_nodes:
        with conn:
            if new_loops:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO loops (loop_id, min_value, length, members_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    new_loops,
                )
            if new_nodes:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO steps_cache (n, next_n, loop_id, steps)
                    VALUES (?, ?, ?, ?)
                    """,
                    new_nodes,
                )

    return loops_by_id, cache, len(new_loops), len(new_nodes)


def plot_results(
    loops_by_id: Dict[int, Dict],
    cache: Dict[int, Tuple[int, int]],
    max_n: int,
    png_path: Path,
    svg_path: Path,
) -> None:
    """
    Create the 6-color scatter plot of N vs iterN and save as:
      - 1800x1000 px PNG
      - Vector SVG
    """
    # Distinct 6-color palette (high contrast, colorblind-friendly)
    palette = [
        "#0072B2",  # Blue
        "#D55E00",  # Vermilion / Orange-Red
        "#009E73",  # Bluish Green
        "#CC79A7",  # Reddish Purple
        "#E69F00",  # Orange / Amber
        "#56B4E9",  # Sky Blue
    ]

    # Sort loops deterministically by min_value so colors/labels are always consistent
    sorted_loops = sorted(loops_by_id.values(), key=lambda d: d["min_value"])

    # Group points (n, steps) by loop_id for 1..max_n
    xs_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in sorted_loops}
    ys_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in sorted_loops}

    max_steps = 0
    for n in range(1, max_n + 1):
        loop_id, steps = cache[n]
        xs_by_loop[loop_id].append(n)
        ys_by_loop[loop_id].append(steps)
        if steps > max_steps:
            max_steps = steps

    # Configure matplotlib style to match reference docs/images/iter.png
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif", "STIXGeneral"],
            "mathtext.fontset": "stix",
            "axes.labelsize": 18,
            "xtick.labelsize": 15,
            "ytick.labelsize": 15,
            "legend.fontsize": 10.5,
        }
    )

    # 9 inches * 200 dpi = 1800 px width, 5 inches * 200 dpi = 1000 px height
    fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=200)

    # Adjust marker size based on point density
    marker_size = 4.0 if max_n <= 20000 else 2.2

    for idx, lp in enumerate(sorted_loops):
        lid = lp["loop_id"]
        color = palette[idx % len(palette)]
        label = format_loop_label(idx + 1, lp["members"])
        ax.scatter(
            xs_by_loop[lid],
            ys_by_loop[lid],
            s=marker_size,
            c=color,
            label=label,
            alpha=0.88,
            edgecolors="none",
            rasterized=False,  # Keep vector points in SVG for sharp zooming
        )

    ax.set_xlabel("N", labelpad=8)
    ax.set_ylabel("iterN", labelpad=8)

    ax.set_xlim(0, max_n)
    # Leave headroom at the top for the legend so points are not obscured
    y_top = max(int(max_steps * 1.22), 50)
    # Round y_top up to a clean multiple of 50
    y_top = ((y_top + 49) // 50) * 50
    ax.set_ylim(0, y_top)

    # Use 10 major intervals on X-axis (0, 1, 2, ..., 10 x 10^k) matching iter.png
    if max_n >= 10 and max_n % 10 == 0:
        ax.xaxis.set_major_locator(MultipleLocator(max_n / 10))
    if max_n >= 10000:
        exp = max(int(math.floor(math.log10(max_n))) - 1, 3)
        formatter = ScalarFormatter(useMathText=True)
        formatter.set_scientific(True)
        formatter.set_powerlimits((exp, exp))
        ax.xaxis.set_major_formatter(formatter)

    # Inward ticks on all 4 sides + subtle dotted grid
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

    # Add legend for the 6 loops
    leg = ax.legend(
        loc="upper left",
        ncol=2,
        frameon=True,
        facecolor="white",
        edgecolor="#cccccc",
        framealpha=0.92,
        markerscale=2.5,
        columnspacing=1.2,
        handletextpad=0.4,
    )

    # Adjust margins explicitly so saved PNG stays strictly 1800x1000 pixels
    fig.subplots_adjust(left=0.085, right=0.975, bottom=0.14, top=0.95)

    png_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(png_path, format="png", dpi=200)
    fig.savefig(svg_path, format="svg")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute and plot step counts for the 3n+5 problem."
    )
    parser.add_argument(
        "-n",
        "--max-n",
        type=int,
        default=10000,
        help="Maximum initial value N on the horizontal axis (default: 10000).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--png",
        type=Path,
        default=DEFAULT_PNG_PATH,
        help=f"Output PNG path (default: {DEFAULT_PNG_PATH}).",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        default=DEFAULT_SVG_PATH,
        help=f"Output SVG path (default: {DEFAULT_SVG_PATH}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_n < 1:
        raise ValueError("--max-n must be a positive integer (>= 1).")

    args.db.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        loops_by_id, cache, num_new_loops, num_new_nodes = compute_and_persist(
            conn, args.max_n
        )
    finally:
        conn.close()
    t_calc = time.perf_counter() - t0

    print(f"=== 3n+5 Calculation Complete (N = 1 .. {args.max_n}) ===")
    print(f"Calculation + DB sync time : {t_calc * 1000:.2f} ms")
    print(f"Total cached numbers in DB : {len(cache):,}")
    print(f"Newly added numbers to DB  : {num_new_nodes:,}")
    print(f"Discovered loops ({len(loops_by_id)})       :")

    sorted_loops = sorted(loops_by_id.values(), key=lambda d: d["min_value"])
    for idx, lp in enumerate(sorted_loops, start=1):
        count_in_range = sum(
            1 for n in range(1, args.max_n + 1) if cache[n][0] == lp["loop_id"]
        )
        print(
            f"  - {format_loop_label(idx, lp['members'])} "
            f"-> {count_in_range:,} initial values in [1..{args.max_n}]"
        )

    t1 = time.perf_counter()
    plot_results(loops_by_id, cache, args.max_n, args.png, args.svg)
    t_plot = time.perf_counter() - t1
    print(f"Plot generation time       : {t_plot * 1000:.2f} ms")
    print(f"Saved PNG (1800x1000)      : {args.png}")
    print(f"Saved SVG (vector)         : {args.svg}")


if __name__ == "__main__":
    main()
