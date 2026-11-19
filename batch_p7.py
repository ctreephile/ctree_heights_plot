#!/usr/bin/env python3
"""
Disk-Efficient Batch Grid Runner for (p, Q) = (7, [_, q1, q2, q3, q4, q5]).

For p = 7 (d = 6 = 2 * 3), divisibility requires:
  (7 * r + q_r) ≡ 0 (mod 6)  <=>  q_r ≡ 6 - r (mod 6) for r = 1..5.

Evaluates the 6^5 = 7,776 Cartesian grid (q_r = 6*k + (6-r), k = 0..5)
and stores results in `data/p7/summary_p7.db`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.engine import canonicalize_cycle

P_VAL = 7
D_VAL = P_VAL - 1  # 6
DEFAULT_LIMIT_Q = 6  # 6^5 = 7,776 systems

DEFAULT_DATA_DIR = Path("data/p7")
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "summary_p7.db"


def build_q_axes(limit_q: int) -> List[List[int]]:
    return [[D_VAL * k + (D_VAL - r) for k in range(limit_q)] for r in range(1, D_VAL)]


def compute_gini_metrics(counts: List[int]) -> Dict[str, float]:
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
    gini = max(0.0, min(1.0, (2.0 * weighted_sum) / (m * total) - (m + 1.0) / m))
    gini_norm = max(0.0, min(1.0, gini * (m / (m - 1.0))))
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


def evaluate_p7_system(
    q_tuple: Tuple[int, int, int, int, int], max_n: int, max_steps: int
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    q1, q2, q3, q4, q5 = q_tuple
    q_norm: List[Optional[int]] = [None, q1, q2, q3, q4, q5]
    gcd_q = math.gcd(q1, math.gcd(q2, math.gcd(q3, math.gcd(q4, q5))))

    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops_by_min: Dict[int, Dict[str, Any]] = {}
    next_loop_id = 1

    for start_n in range(1, max_n + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_index: Dict[int, int] = {}
        curr = start_n

        while curr not in steps_cache and curr not in path_index and len(path) <= max_steps:
            path_index[curr] = len(path)
            path.append(curr)
            r = curr % 6
            if r == 0:
                curr = curr // 6
            elif r == 1:
                curr = 7 * curr + q1
            elif r == 2:
                curr = 7 * curr + q2
            elif r == 3:
                curr = 7 * curr + q3
            elif r == 4:
                curr = 7 * curr + q4
            else:
                curr = 7 * curr + q5

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
            if min_val not in loops_by_min:
                lid = next_loop_id
                next_loop_id += 1
                loops_by_min[min_val] = {
                    "raw_loop_id": lid,
                    "min_value": min_val,
                    "max_value": max(canonical_members),
                    "length": len(canonical_members),
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

    sorted_loops = sorted(loops_by_min.values(), key=lambda x: x["min_value"])
    raw_to_rank = {lp["raw_loop_id"]: idx + 1 for idx, lp in enumerate(sorted_loops)}
    basin_counts = {idx + 1: 0 for idx in range(len(sorted_loops))}

    unresolved_count = 0
    max_obs_steps = 0
    max_step_n = 1
    total_resolved_steps = 0
    resolved_count = 0

    for n_val in range(1, max_n + 1):
        raw_lid, st = steps_cache[n_val]
        if raw_lid == 0 or st < 0:
            unresolved_count += 1
        else:
            rank_lid = raw_to_rank[raw_lid]
            basin_counts[rank_lid] += 1
            total_resolved_steps += st
            resolved_count += 1
            if st > max_obs_steps:
                max_obs_steps = st
                max_step_n = n_val

    avg_steps = (total_resolved_steps / resolved_count) if resolved_count > 0 else 0.0
    loops_records: List[Dict[str, Any]] = []
    counts_for_gini: List[int] = []

    for idx, lp in enumerate(sorted_loops):
        rank_lid = idx + 1
        members = lp["members"]
        l_div_count = sum(1 for m in members if m % 6 == 0)
        k_counts = [sum(1 for m in members if m % 6 == r) for r in range(1, 6)]
        k_mul_count = sum(k_counts)
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
                "k1_count": k_counts[0],
                "k2_count": k_counts[1],
                "k3_count": k_counts[2],
                "k4_count": k_counts[3],
                "k5_count": k_counts[4],
                "basin_count": b_cnt,
                "basin_share": b_share,
                "elements_json": json.dumps(members),
            }
        )

    gini_metrics = compute_gini_metrics(counts_for_gini)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "p": P_VAL,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "q4": q4,
        "q5": q5,
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


def worker_task(task: Tuple[Tuple[int, int, int, int, int], int, int]) -> Dict[str, Any]:
    q_tuple, max_n, max_steps = task
    return evaluate_p7_system(q_tuple, max_n, max_steps)


def init_summary_db(db_path: Path) -> sqlite3.Connection:
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
            q4               INTEGER NOT NULL,
            q5               INTEGER NOT NULL,
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
            k4_count      INTEGER NOT NULL,
            k5_count      INTEGER NOT NULL,
            basin_count   INTEGER NOT NULL,
            basin_share   REAL    NOT NULL,
            elements_json TEXT    NOT NULL,
            PRIMARY KEY (system_id, loop_id),
            FOREIGN KEY (system_id) REFERENCES systems(system_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_systems_q ON systems(q1, q2, q3, q4, q5);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_systems_gcd ON systems(gcd_q);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_systems_loops ON systems(num_loops);")
    return conn


def get_completed_keys(conn: sqlite3.Connection, max_n: int) -> Set[Tuple[int, int, int, int, int]]:
    cur = conn.execute(
        "SELECT q1, q2, q3, q4, q5 FROM systems WHERE p = ? AND n_max >= ?",
        (P_VAL, max_n),
    )
    return {(int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in cur.fetchall()}


def flush_batch_to_db(conn: sqlite3.Connection, batch_results: List[Dict[str, Any]]) -> None:
    if not batch_results:
        return
    with conn:
        for res in batch_results:
            conn.execute(
                """
                INSERT INTO systems (
                    p, q1, q2, q3, q4, q5, q_json, gcd_q, n_max, num_loops,
                    max_steps, max_step_n, avg_steps, unresolved_count,
                    gini, gini_norm, hhi, shannon_evenness, elapsed_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    res["p"], res["q1"], res["q2"], res["q3"], res["q4"], res["q5"],
                    res["q_json"], res["gcd_q"], res["n_max"], res["num_loops"],
                    res["max_steps"], res["max_step_n"], res["avg_steps"],
                    res["unresolved_count"], res["gini"], res["gini_norm"],
                    res["hhi"], res["shannon_evenness"], res["elapsed_ms"],
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
                    l_div_count, k_mul_count, k1_count, k2_count, k3_count, k4_count, k5_count,
                    basin_count, basin_share, elements_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sys_id, lp["loop_id"], lp["min_value"], lp["max_value"],
                        lp["length"], lp["l_div_count"], lp["k_mul_count"],
                        lp["k1_count"], lp["k2_count"], lp["k3_count"], lp["k4_count"], lp["k5_count"],
                        lp["basin_count"], lp["basin_share"], lp["elements_json"],
                    )
                    for lp in res["loops"]
                ],
            )


def run_batch_p7(
    limit_q: int = DEFAULT_LIMIT_Q,
    max_n: int = 100000,
    max_steps: int = 10000,
    db_path: Path = DEFAULT_DB_PATH,
    workers: int = 0,
    force_recompute: bool = False,
) -> None:
    axes = build_q_axes(limit_q)
    conn = init_summary_db(db_path)
    completed_keys = set() if force_recompute else get_completed_keys(conn, max_n)

    tasks: List[Tuple[Tuple[int, int, int, int, int], int, int]] = []
    for q_tup in itertools.product(*axes):
        if q_tup not in completed_keys:
            tasks.append((q_tup, max_n, max_steps))

    total_grid = limit_q ** 5
    remaining_tasks = len(tasks)
    if workers <= 0:
        workers = max(1, (os.cpu_count() or 4) - 1)

    print(f"=== p=7 Batch: {total_grid:,} systems (Remaining: {remaining_tasks:,}, Workers: {workers}) ===")
    t_start = time.perf_counter()
    completed_now = 0
    pending: List[Dict[str, Any]] = []

    if remaining_tasks > 0:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker_task, t) for t in tasks]
            for fut in as_completed(futures):
                res = fut.result()
                pending.append(res)
                completed_now += 1
                if len(pending) >= 200 or completed_now == remaining_tasks:
                    flush_batch_to_db(conn, pending)
                    pending.clear()
                    elapsed = time.perf_counter() - t_start
                    rate = completed_now / max(elapsed, 1e-6)
                    eta = (remaining_tasks - completed_now) / max(rate, 1e-6)
                    print(f"[{completed_now:5d}/{remaining_tasks}] Rate: {rate:.1f} sys/s | ETA: {eta:.1f}s")

    conn.close()
    print(f"=== Done in {time.perf_counter() - t_start:.2f}s -> {db_path} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--max-n", type=int, default=100000)
    parser.add_argument("--max-steps", type=int, default=10000)
    parser.add_argument("--limit-q", type=int, default=DEFAULT_LIMIT_Q)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run_batch_p7(
        limit_q=args.limit_q,
        max_n=args.max_n,
        max_steps=args.max_steps,
        db_path=args.db,
        workers=args.workers,
        force_recompute=args.force,
    )

