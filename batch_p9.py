#!/usr/bin/env python3
"""
Disk-Efficient Batch Grid Runner for (p, Q) = (9, [_, q1, q2, q3, q4, q5, q6, q7]).

For p = 9 = 3^2 (d = 8 = 2^3), divisibility requires:
  (9 * r + q_r) ≡ 0 (mod 8)  <=>  q_r ≡ 8 - r (mod 8) for r = 1..7.

Evaluates the 4^7 = 16,384 Cartesian grid (q_r = 8*k + (8-r), k = 0..3)
and stores results in `data/p9/summary_p9.db`.
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

P_VAL = 9
D_VAL = P_VAL - 1  # 8
DEFAULT_LIMIT_Q = 4  # 4^7 = 16,384 systems

DEFAULT_DATA_DIR = Path("data/p9")
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "summary_p9.db"


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


def evaluate_p9_system(
    q_tuple: Tuple[int, int, int, int, int, int, int], max_n: int, max_steps: int
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    q1, q2, q3, q4, q5, q6, q7 = q_tuple
    gcd_q = math.gcd(q1, math.gcd(q2, math.gcd(q3, math.gcd(q4, math.gcd(q5, math.gcd(q6, q7))))))

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
            r = curr % 8
            if r == 0:
                curr = curr // 8
            elif r == 1:
                curr = 9 * curr + q1
            elif r == 2:
                curr = 9 * curr + q2
            elif r == 3:
                curr = 9 * curr + q3
            elif r == 4:
                curr = 9 * curr + q4
            elif r == 5:
                curr = 9 * curr + q5
            elif r == 6:
                curr = 9 * curr + q6
            else:
                curr = 9 * curr + q7

        if curr in steps_cache:
            known_steps, known_loop_id = steps_cache[curr]
            for idx, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (known_steps + idx, known_loop_id)
        elif curr in path_index:
            loop_start = path_index[curr]
            raw_cycle = path[loop_start:]
            canon_cycle = canonicalize_cycle(raw_cycle)
            min_val = canon_cycle[0]
            if min_val not in loops_by_min:
                l_div = sum(1 for v in canon_cycle if v % 8 == 0)
                k_mul = len(canon_cycle) - l_div
                loops_by_min[min_val] = {
                    "loop_id": next_loop_id,
                    "elements": canon_cycle,
                    "min_value": min_val,
                    "max_value": max(canon_cycle),
                    "length": len(canon_cycle),
                    "l_div_count": l_div,
                    "k_mul_count": k_mul,
                }
                next_loop_id += 1
            loop_id = loops_by_min[min_val]["loop_id"]
            for val in path[loop_start:]:
                steps_cache[val] = (0, loop_id)
            for idx, val in enumerate(reversed(path[:loop_start]), start=1):
                steps_cache[val] = (idx, loop_id)
        else:
            for val in path:
                steps_cache[val] = (-1, 0)

    basin_counts: Dict[int, int] = {lp["loop_id"]: 0 for lp in loops_by_min.values()}
    unresolved_count = 0
    max_step_seen = 0
    max_step_n = 1
    total_steps_resolved = 0
    resolved_count = 0

    for n in range(1, max_n + 1):
        st, lid = steps_cache[n]
        if lid == 0 or st < 0:
            unresolved_count += 1
        else:
            basin_counts[lid] = basin_counts.get(lid, 0) + 1
            resolved_count += 1
            total_steps_resolved += st
            if st > max_step_seen:
                max_step_seen = st
                max_step_n = n

    avg_steps = (total_steps_resolved / resolved_count) if resolved_count > 0 else 0.0
    sorted_loops = sorted(loops_by_min.values(), key=lambda x: x["min_value"])
    counts_list: List[int] = []
    loops_out: List[Dict[str, Any]] = []

    for new_idx, lp in enumerate(sorted_loops, start=1):
        old_id = lp["loop_id"]
        b_cnt = basin_counts.get(old_id, 0)
        b_share = (b_cnt / resolved_count) if resolved_count > 0 else 0.0
        counts_list.append(b_cnt)
        loops_out.append(
            {
                "loop_id": new_idx,
                "min_value": lp["min_value"],
                "max_value": lp["max_value"],
                "length": lp["length"],
                "l_div_count": lp["l_div_count"],
                "k_mul_count": lp["k_mul_count"],
                "basin_count": b_cnt,
                "basin_share": b_share,
                "elements": lp["elements"],
            }
        )

    gini_metrics = compute_gini_metrics(counts_list)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "p": P_VAL,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "q4": q4,
        "q5": q5,
        "q6": q6,
        "q7": q7,
        "q_json": json.dumps([None, q1, q2, q3, q4, q5, q6, q7]),
        "gcd_q": gcd_q,
        "n_max": max_n,
        "num_loops": len(loops_out),
        "max_steps": max_step_seen,
        "max_step_n": max_step_n,
        "avg_steps": avg_steps,
        "unresolved_count": unresolved_count,
        "gini": gini_metrics["gini"],
        "gini_norm": gini_metrics["gini_norm"],
        "hhi": gini_metrics["hhi"],
        "shannon_evenness": gini_metrics["shannon_evenness"],
        "elapsed_ms": elapsed_ms,
        "loops": loops_out,
    }


def _worker_chunk(
    chunk: List[Tuple[int, int, int, int, int, int, int]], max_n: int, max_steps: int
) -> List[Dict[str, Any]]:
    return [evaluate_p9_system(q, max_n, max_steps) for q in chunk]


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS systems (
            system_id INTEGER PRIMARY KEY AUTOINCREMENT,
            p INTEGER NOT NULL,
            q1 INTEGER NOT NULL,
            q2 INTEGER NOT NULL,
            q3 INTEGER NOT NULL,
            q4 INTEGER NOT NULL,
            q5 INTEGER NOT NULL,
            q6 INTEGER NOT NULL,
            q7 INTEGER NOT NULL,
            q_json TEXT NOT NULL,
            gcd_q INTEGER NOT NULL,
            n_max INTEGER NOT NULL,
            num_loops INTEGER NOT NULL,
            max_steps INTEGER NOT NULL,
            max_step_n INTEGER NOT NULL,
            avg_steps REAL NOT NULL,
            unresolved_count INTEGER NOT NULL,
            gini REAL NOT NULL,
            gini_norm REAL NOT NULL,
            hhi REAL NOT NULL,
            shannon_evenness REAL NOT NULL,
            elapsed_ms REAL NOT NULL,
            UNIQUE(p, q1, q2, q3, q4, q5, q6, q7)
        );

        CREATE TABLE IF NOT EXISTS loops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            loop_id INTEGER NOT NULL,
            min_value INTEGER NOT NULL,
            max_value INTEGER NOT NULL,
            length INTEGER NOT NULL,
            l_div_count INTEGER NOT NULL,
            k_mul_count INTEGER NOT NULL,
            basin_count INTEGER NOT NULL,
            basin_share REAL NOT NULL,
            elements_json TEXT NOT NULL,
            FOREIGN KEY(system_id) REFERENCES systems(system_id),
            UNIQUE(system_id, loop_id)
        );

        CREATE INDEX IF NOT EXISTS idx_systems_q ON systems(q1, q2, q3, q4, q5, q6, q7);
        CREATE INDEX IF NOT EXISTS idx_systems_gcd ON systems(gcd_q);
        CREATE INDEX IF NOT EXISTS idx_loops_sys ON loops(system_id);
        """
    )
    conn.commit()
    return conn


def insert_batch(conn: sqlite3.Connection, results: List[Dict[str, Any]]) -> None:
    with conn:
        for res in results:
            cur = conn.execute(
                """
                INSERT INTO systems (
                    p, q1, q2, q3, q4, q5, q6, q7, q_json, gcd_q, n_max,
                    num_loops, max_steps, max_step_n, avg_steps, unresolved_count,
                    gini, gini_norm, hhi, shannon_evenness, elapsed_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(p, q1, q2, q3, q4, q5, q6, q7) DO UPDATE SET
                    n_max=excluded.n_max,
                    num_loops=excluded.num_loops,
                    max_steps=excluded.max_steps,
                    max_step_n=excluded.max_step_n,
                    avg_steps=excluded.avg_steps,
                    unresolved_count=excluded.unresolved_count,
                    gini=excluded.gini,
                    gini_norm=excluded.gini_norm,
                    hhi=excluded.hhi,
                    shannon_evenness=excluded.shannon_evenness,
                    elapsed_ms=excluded.elapsed_ms
                RETURNING system_id
                """,
                (
                    res["p"],
                    res["q1"],
                    res["q2"],
                    res["q3"],
                    res["q4"],
                    res["q5"],
                    res["q6"],
                    res["q7"],
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
            system_id = cur.fetchone()[0]
            conn.execute("DELETE FROM loops WHERE system_id = ?", (system_id,))
            for lp in res["loops"]:
                conn.execute(
                    """
                    INSERT INTO loops (
                        system_id, loop_id, min_value, max_value, length,
                        l_div_count, k_mul_count, basin_count, basin_share, elements_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        system_id,
                        lp["loop_id"],
                        lp["min_value"],
                        lp["max_value"],
                        lp["length"],
                        lp["l_div_count"],
                        lp["k_mul_count"],
                        lp["basin_count"],
                        lp["basin_share"],
                        json.dumps(lp["elements"]),
                    ),
                )


def run_batch_p9(
    limit_q: int = DEFAULT_LIMIT_Q,
    max_n: int = 5000,
    max_steps: int = 2000,
    workers: int = max(1, (os.cpu_count() or 4) - 1),
    chunk_size: int = 128,
    db_path: Path = DEFAULT_DB_PATH,
    overwrite: bool = False,
) -> Dict[str, Any]:
    conn = init_db(db_path)
    existing: Set[Tuple[int, int, int, int, int, int, int]] = set()
    if not overwrite:
        rows = conn.execute(
            "SELECT q1, q2, q3, q4, q5, q6, q7 FROM systems WHERE p = ? AND n_max >= ?",
            (P_VAL, max_n),
        ).fetchall()
        existing = {
            (int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]), int(r[6]))
            for r in rows
        }

    axes = build_q_axes(limit_q)
    all_tuples = [t for t in itertools.product(*axes) if t not in existing]
    total_target = len(all_tuples)
    print(
        f"[batch_p9] Target systems to compute: {total_target:,} "
        f"(already in DB: {len(existing):,}, limit_q={limit_q}, max_n={max_n}, workers={workers})"
    )

    t0 = time.perf_counter()
    if total_target > 0:
        chunks = [all_tuples[i : i + chunk_size] for i in range(0, total_target, chunk_size)]
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker_chunk, ch, max_n, max_steps): len(ch) for ch in chunks}
            for fut in as_completed(futures):
                res_list = fut.result()
                insert_batch(conn, res_list)
                done += len(res_list)
                elapsed = time.perf_counter() - t0
                rate = done / elapsed if elapsed > 0 else 0.0
                if done % 1024 == 0 or done == total_target:
                    print(f"  Progress: {done:,} / {total_target:,} ({done/total_target*100:.1f}%) | {rate:.1f} sys/s | {elapsed:.1f}s")

    total_in_db = conn.execute("SELECT COUNT(*) FROM systems WHERE p = ?", (P_VAL,)).fetchone()[0]
    conn.close()
    total_elapsed = time.perf_counter() - t0
    print(f"[batch_p9] Completed! Total systems in {db_path}: {total_in_db:,} ({total_elapsed:.2f}s)")
    return {"db_path": str(db_path), "total_systems": total_in_db, "elapsed_sec": total_elapsed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch runner for p=9 (7D Q grid)")
    parser.add_argument("--limit-q", type=int, default=DEFAULT_LIMIT_Q, help="Grid size per axis (default: 4 -> 4^7 = 16,384)")
    parser.add_argument("--max-n", type=int, default=5000, help="Max initial value n (default: 5000)")
    parser.add_argument("--max-steps", type=int, default=2000, help="Max trajectory steps (default: 2000)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    run_batch_p9(
        limit_q=args.limit_q,
        max_n=args.max_n,
        max_steps=args.max_steps,
        workers=args.workers,
        overwrite=args.overwrite,
    )

