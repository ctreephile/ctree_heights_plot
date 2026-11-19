"""
Generalized (p, Q) Collatz Engine with SQLite persistence & in-memory caching.

Mathematical definition (from docs/pn_q.txt):
  - p: natural number (p >= 2, typically p >= 3)
  - divisor: d = p - 1
  - Q: [_, q_1, q_2, ..., q_{p-2}] of length d = p - 1
  - For any positive integer n, let r = n mod d:
      T_{p,Q}(n) = n / d         if r == 0
      T_{p,Q}(n) = p * n + q_r   if r != 0
    where q_r is chosen such that (p * n + q_r) is divisible by d.
"""

from __future__ import annotations

import io
import json
import math
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, ScalarFormatter

from backend.logger import get_logger

logger = get_logger("engine")

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "outputs" / "collatz_pq.db"

DEFAULT_PALETTE = [
    "#0072B2",  # Blue
    "#D55E00",  # Vermilion / Orange-Red
    "#009E73",  # Bluish Green
    "#CC79A7",  # Reddish Purple
    "#E69F00",  # Orange / Amber
    "#56B4E9",  # Sky Blue
    "#F0E442",  # Yellow
    "#332288",  # Indigo
    "#882255",  # Wine
    "#44AA99",  # Teal
]


def normalize_q(p: int, q_input: List[Optional[int]]) -> List[Optional[int]]:
    """
    Normalize Q into a list of length d = p - 1 where index 0 is None:
      [None, q_1, q_2, ..., q_{p-2}]

    Accepts either:
      - length (p - 1) list: [None/0/'_', q_1, ..., q_{p-2}]
      - length (p - 2) list: [q_1, ..., q_{p-2}]
    """
    if p < 2:
        raise ValueError(f"p must be a natural number >= 2 (got {p}).")
    d = p - 1
    if d == 1:
        return [None]

    cleaned: List[Optional[int]] = []
    for item in q_input:
        if item is None or item == "_" or item == "":
            cleaned.append(None)
        else:
            cleaned.append(int(item))

    if len(cleaned) == d:
        res: List[Optional[int]] = [None] + [int(x) if x is not None else 0 for x in cleaned[1:]]
    elif len(cleaned) == d - 1 and all(x is not None for x in cleaned):
        res = [None] + [int(x) for x in cleaned]
    else:
        raise ValueError(
            f"For p={p} (d={d}), Q must provide {d - 1} positive integers [q_1..q_{d - 1}] "
            f"or a length-{d} list [_, q_1..q_{d - 1}]. Got: {q_input}"
        )
    return res


def validate_pq(p: int, q_input: List[Optional[int]]) -> Dict[str, Any]:
    """
    Validate p and Q according to docs/pn_q.txt:
      1. p >= 2 (typically p >= 3)
      2. Each q_r (for r = 1..p-2) is a positive integer (> 0)
      3. For every r in 1..p-2, (p * r + q_r) % (p - 1) == 0
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(p, int) or p < 2:
        return {
            "valid": False,
            "p": p,
            "d": p - 1 if isinstance(p, int) else None,
            "q_normalized": [],
            "errors": ["p は 2 以上の自然数を指定してください。"],
            "warnings": [],
        }

    d = p - 1
    try:
        q_norm = normalize_q(p, q_input)
    except Exception as exc:
        return {
            "valid": False,
            "p": p,
            "d": d,
            "q_normalized": [],
            "errors": [str(exc)],
            "warnings": [],
        }

    for r in range(1, d):
        qr = q_norm[r]
        if qr is None or qr <= 0:
            errors.append(f"r={r} の要素 q_{r}={qr} は正の整数（> 0）である必要があります。")
            continue
        rem = (p * r + qr) % d
        if rem != 0:
            required_mod = (d - (p * r) % d) % d
            warnings.append(
                f"r={r}: p*n + q_{r} ({p}n + {qr}) が d={d} で割り切れません "
                f"(余り {rem}。d={d} で割り切れるには q_{r} ≡ {required_mod} (mod {d}) が必要です)。"
            )

    is_valid = len(errors) == 0
    logger.debug(
        "Validated (p=%s, Q=%s): valid=%s, errors=%d, warnings=%d",
        p,
        q_norm,
        is_valid,
        len(errors),
        len(warnings),
    )
    return {
        "valid": is_valid,
        "strictly_divisible": len(errors) == 0 and len(warnings) == 0,
        "p": p,
        "d": d,
        "q_normalized": q_norm,
        "errors": errors,
        "warnings": warnings,
    }


def step_pq(n: int, p: int, d: int, q_norm: List[Optional[int]]) -> int:
    """Compute a single step T_{p,Q}(n)."""
    r = n % d
    if r == 0:
        return n // d
    qr = q_norm[r]
    assert qr is not None
    return p * n + qr


def predecessors_pq(
    y: int, p: int, d: int, q_norm: List[Optional[int]]
) -> List[Dict[str, Any]]:
    """
    Compute all immediate inverse images (predecessors / CTree children "後")
    of y under T_{p,Q}, i.e., all positive integers m such that T_{p,Q}(m) = y.

    For example, in 3n+1 (p=3, d=2, Q=[_, 1]) with y=16:
      - r=0 branch: m = 2 * 16 = 32 (since 32 / 2 = 16)
      - r=1 branch: m = (16 - 1) / 3 = 5 (since 3*5 + 1 = 16 and 5 mod 2 = 1)
    """
    preds: List[Dict[str, Any]] = []

    # 1. r = 0 branch: m / d = y  =>  m = d * y
    m0 = d * y
    if m0 > 0 and (m0 % d) == 0:
        preds.append(
            {
                "n": m0,
                "r": 0,
                "branch_type": "div",
                "formula": f"{m0} / {d} = {y}",
            }
        )

    # 2. r != 0 branches: p * m + q_r = y  =>  m = (y - q_r) / p with m mod d == r
    for r in range(1, d):
        qr = q_norm[r]
        if qr is None:
            continue
        diff = y - qr
        if diff > 0 and (diff % p) == 0:
            mr = diff // p
            if mr > 0 and (mr % d) == r:
                preds.append(
                    {
                        "n": mr,
                        "r": r,
                        "branch_type": "mul_add",
                        "formula": f"{p}×{mr} + {qr} = {y}",
                    }
                )

    return preds


def canonicalize_cycle(cycle: List[int]) -> List[int]:
    """Rotate a cycle list so that its minimum element comes first."""
    min_val = min(cycle)
    min_idx = cycle.index(min_val)
    return cycle[min_idx:] + cycle[:min_idx]


def format_loop_label(loop_id: int, members: List[int]) -> str:
    """Format a human-readable legend label for a loop."""
    if loop_id == 0 or not members:
        return "Unresolved (Max Steps Exceeded)"
    length = len(members)
    if length <= 8:
        seq_str = "[" + ", ".join(str(x) for x in members) + "]"
    else:
        head = ", ".join(str(x) for x in members[:3])
        tail = str(members[-1])
        seq_str = f"[{head}, ..., {tail}]"
    return f"Loop {loop_id} (len={length}): {seq_str}"


class CollatzPQEngine:
    """
    Manages SQLite database persistence and in-memory trajectory caching
    across multiple (p, Q) parameter systems.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # In-memory cache keyed by system_id:
        #   _loops_mem[system_id] = {loop_id: loop_dict}
        #   _steps_mem[system_id] = {n: (next_n, loop_id, steps)}
        self._loops_mem: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._steps_mem: Dict[int, Dict[int, Tuple[int, int, int]]] = {}
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA cache_size = -64000;")
        return conn

    def _init_db(self) -> None:
        t0 = time.perf_counter()
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS systems (
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
                CREATE TABLE IF NOT EXISTS loops (
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
                CREATE TABLE IF NOT EXISTS steps_cache (
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
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("Initialized SQLite schema at %s (%.2f ms)", self.db_path, elapsed_ms)

    def _get_or_create_system(
        self, conn: sqlite3.Connection, p: int, q_norm: List[Optional[int]]
    ) -> int:
        q_json = json.dumps(q_norm)
        cur = conn.execute(
            "SELECT system_id FROM systems WHERE p = ? AND q_json = ?",
            (p, q_json),
        )
        row = cur.fetchone()
        if row is not None:
            system_id = int(row[0])
        else:
            with conn:
                cur = conn.execute(
                    "INSERT INTO systems (p, q_json, max_computed_n) VALUES (?, ?, 0)",
                    (p, q_json),
                )
                system_id = int(cur.lastrowid)
            logger.info("Registered new (p, Q) system_id=%d: p=%d, Q=%s", system_id, p, q_json)

        if system_id not in self._steps_mem:
            self._load_system_into_memory(conn, system_id)
        return system_id

    def _load_system_into_memory(self, conn: sqlite3.Connection, system_id: int) -> None:
        t0 = time.perf_counter()
        loops_dict: Dict[int, Dict[str, Any]] = {}
        cur = conn.execute(
            "SELECT loop_id, min_value, length, members_json FROM loops WHERE system_id = ? ORDER BY loop_id",
            (system_id,),
        )
        for loop_id, min_val, length, members_json in cur:
            loops_dict[int(loop_id)] = {
                "loop_id": int(loop_id),
                "min_value": int(min_val),
                "length": int(length),
                "members": json.loads(members_json),
            }

        steps_dict: Dict[int, Tuple[int, int, int]] = {}
        cur = conn.execute(
            "SELECT n, next_n, loop_id, steps FROM steps_cache WHERE system_id = ?",
            (system_id,),
        )
        for n, next_n, loop_id, steps in cur:
            steps_dict[int(n)] = (int(next_n), int(loop_id), int(steps))

        self._loops_mem[system_id] = loops_dict
        self._steps_mem[system_id] = steps_dict
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Loaded system_id=%d from SQLite into memory: %d loops, %d cached nodes (%.2f ms)",
            system_id,
            len(loops_dict),
            len(steps_dict),
            elapsed_ms,
        )

    def ensure_number_evaluated(
        self,
        system_id: int,
        start_n: int,
        p: int,
        d: int,
        q_norm: List[Optional[int]],
        max_steps: int,
        new_loops_out: List[Tuple[int, int, int, int, str]],
        new_nodes_out: List[Tuple[int, int, int, int, int]],
    ) -> Tuple[int, int, int]:
        """
        Evaluate a single starting integer `start_n` if not already in memory cache.
        Returns (next_n, loop_id, steps).
        """
        steps_cache = self._steps_mem[system_id]
        loops_by_id = self._loops_mem[system_id]

        if start_n in steps_cache:
            return steps_cache[start_n]

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
            curr = step_pq(curr, p, d, q_norm)

        if curr in steps_cache:
            _, target_loop_id, base_steps = steps_cache[curr]
            path_len = len(path)
            if target_loop_id == 0 or base_steps < 0:
                # Reached an unresolved trajectory
                for idx, val in enumerate(path):
                    nxt = path[idx + 1] if idx + 1 < path_len else curr
                    steps_cache[val] = (nxt, 0, -1)
            else:
                for idx, val in enumerate(path):
                    steps = base_steps + (path_len - idx)
                    nxt = path[idx + 1] if idx + 1 < path_len else curr
                    steps_cache[val] = (nxt, target_loop_id, steps)
                    new_nodes_out.append((system_id, val, nxt, target_loop_id, steps))
        elif curr in path_index:
            # Cycle detected!
            cycle_start = path_index[curr]
            raw_cycle = path[cycle_start:]
            canonical_members = canonicalize_cycle(raw_cycle)
            min_val = canonical_members[0]
            cycle_len = len(canonical_members)

            # Check if a loop with this min_val already exists
            existing_lid = None
            for lid, linfo in loops_by_id.items():
                if linfo["min_value"] == min_val:
                    existing_lid = lid
                    break

            if existing_lid is None:
                loop_id = max(loops_by_id.keys(), default=0) + 1
                loops_by_id[loop_id] = {
                    "loop_id": loop_id,
                    "min_value": min_val,
                    "length": cycle_len,
                    "members": canonical_members,
                }
                new_loops_out.append(
                    (system_id, loop_id, min_val, cycle_len, json.dumps(canonical_members))
                )
                logger.info(
                    "Discovered new loop for system_id=%d (p=%d, Q=%s): loop_id=%d, min=%d, len=%d",
                    system_id,
                    p,
                    q_norm,
                    loop_id,
                    min_val,
                    cycle_len,
                )
            else:
                loop_id = existing_lid

            # Register cycle members with steps = 0
            for i, val in enumerate(raw_cycle):
                nxt = raw_cycle[(i + 1) % cycle_len]
                steps_cache[val] = (nxt, loop_id, 0)
                new_nodes_out.append((system_id, val, nxt, loop_id, 0))

            # Register pre-period path leading into the cycle
            for idx in range(cycle_start):
                val = path[idx]
                nxt = path[idx + 1]
                steps = cycle_start - idx
                steps_cache[val] = (nxt, loop_id, steps)
                new_nodes_out.append((system_id, val, nxt, loop_id, steps))
        else:
            # Exceeded max_steps without hitting a cycle or cached node
            nxt_first = path[1] if len(path) > 1 else curr
            steps_cache[start_n] = (nxt_first, 0, -1)
            logger.warning(
                "Trajectory from n=%d (system_id=%d, p=%d, Q=%s) exceeded max_steps=%d",
                start_n,
                system_id,
                p,
                q_norm,
                max_steps,
            )

        return steps_cache[start_n]

    def compute_range(
        self,
        p: int,
        q_input: List[Optional[int]],
        n_start: int = 1,
        n_end: int = 10000,
        max_steps: int = 10000,
    ) -> Dict[str, Any]:
        """
        Compute trajectories for all n in [n_start, n_end], persist new results to SQLite,
        and return structured data for plotting.
        """
        if n_start < 1 or n_end < n_start:
            raise ValueError(f"Invalid range: n_start={n_start}, n_end={n_end}")

        validation = validate_pq(p, q_input)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))

        q_norm = validation["q_normalized"]
        d = p - 1

        t0 = time.perf_counter()
        logger.info(
            "Starting compute_range: p=%d, Q=%s, range=[%d..%d], max_steps=%d",
            p,
            q_norm,
            n_start,
            n_end,
            max_steps,
        )

        new_loops: List[Tuple[int, int, int, int, str]] = []
        new_nodes: List[Tuple[int, int, int, int, int]] = []

        with self._get_conn() as conn:
            system_id = self._get_or_create_system(conn, p, q_norm)

            for n in range(n_start, n_end + 1):
                self.ensure_number_evaluated(
                    system_id, n, p, d, q_norm, max_steps, new_loops, new_nodes
                )

            if new_loops or new_nodes:
                t_db0 = time.perf_counter()
                with conn:
                    if new_loops:
                        conn.executemany(
                            """
                            INSERT OR IGNORE INTO loops
                            (system_id, loop_id, min_value, length, members_json)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            new_loops,
                        )
                    if new_nodes:
                        conn.executemany(
                            """
                            INSERT OR IGNORE INTO steps_cache
                            (system_id, n, next_n, loop_id, steps)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            new_nodes,
                        )
                    conn.execute(
                        "UPDATE systems SET max_computed_n = MAX(max_computed_n, ?) WHERE system_id = ?",
                        (n_end, system_id),
                    )
                t_db_ms = (time.perf_counter() - t_db0) * 1000
                logger.info(
                    "Persisted %d new loops and %d new nodes to SQLite for system_id=%d (%.2f ms)",
                    len(new_loops),
                    len(new_nodes),
                    system_id,
                    t_db_ms,
                )

        steps_cache = self._steps_mem[system_id]
        loops_by_id = self._loops_mem[system_id]

        # Sort loops deterministically by min_value and assign display rank 1..K
        sorted_loops = sorted(loops_by_id.values(), key=lambda x: x["min_value"])
        loop_counts: Dict[int, int] = {lp["loop_id"]: 0 for lp in sorted_loops}
        unresolved_count = 0

        points_n: List[int] = []
        points_steps: List[int] = []
        points_loop_id: List[int] = []
        max_observed_steps = 0

        for n in range(n_start, n_end + 1):
            _, lid, st = steps_cache[n]
            points_n.append(n)
            points_steps.append(st)
            points_loop_id.append(lid)
            if lid == 0 or st < 0:
                unresolved_count += 1
            else:
                loop_counts[lid] = loop_counts.get(lid, 0) + 1
                if st > max_observed_steps:
                    max_observed_steps = st

        loops_summary: List[Dict[str, Any]] = []
        for idx, lp in enumerate(sorted_loops):
            lid = lp["loop_id"]
            color = DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)]
            loops_summary.append(
                {
                    "loop_id": lid,
                    "rank": idx + 1,
                    "min_value": lp["min_value"],
                    "length": lp["length"],
                    "members": lp["members"],
                    "label": format_loop_label(idx + 1, lp["members"]),
                    "color": color,
                    "count_in_range": loop_counts.get(lid, 0),
                }
            )

        if unresolved_count > 0:
            loops_summary.append(
                {
                    "loop_id": 0,
                    "rank": 0,
                    "min_value": -1,
                    "length": 0,
                    "members": [],
                    "label": f"Unresolved (>{max_steps} steps)",
                    "color": "#7F7F7F",
                    "count_in_range": unresolved_count,
                }
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Completed compute_range for system_id=%d [%d..%d]: %d loops, max_steps=%d, elapsed=%.2f ms",
            system_id,
            n_start,
            n_end,
            len(sorted_loops),
            max_observed_steps,
            elapsed_ms,
        )

        return {
            "system_id": system_id,
            "p": p,
            "d": d,
            "q": q_norm,
            "validation": validation,
            "n_start": n_start,
            "n_end": n_end,
            "max_steps_limit": max_steps,
            "max_observed_steps": max_observed_steps,
            "total_cached_nodes": len(steps_cache),
            "newly_added_nodes": len(new_nodes),
            "elapsed_ms": round(elapsed_ms, 2),
            "loops": loops_summary,
            "points": {
                "n": points_n,
                "steps": points_steps,
                "loop_id": points_loop_id,
            },
        }

    def get_node_details(
        self,
        p: int,
        q_input: List[Optional[int]],
        target_n: int,
        n_start: int = 1,
        n_end: int = 10000,
        max_steps: int = 10000,
        same_height_limit: int = 500,
    ) -> Dict[str, Any]:
        """
        Retrieve detailed neighborhood information for a right-clicked node `target_n`:
          1. Algorithmic Forward ("前": toward loop, i.e. T(n), T^2(n), ... up to loop)
          2. Algorithmic Backward / Predecessors ("後": inverse steps T^{-1}(n) and T^{-2}(n),
             e.g. for 16 in 3n+1 -> 32 and 5; while forward is 8)
          3. Numbers with the exact same height (`steps`) in [n_start, n_end].
        """
        if target_n < 1:
            raise ValueError("target_n must be >= 1")

        # Ensure the range and target_n are evaluated
        range_result = self.compute_range(
            p=p,
            q_input=q_input,
            n_start=min(n_start, target_n),
            n_end=max(n_end, target_n),
            max_steps=max_steps,
        )
        system_id = range_result["system_id"]
        q_norm = range_result["q"]
        d = p - 1

        new_loops: List[Tuple[int, int, int, int, str]] = []
        new_nodes: List[Tuple[int, int, int, int, int]] = []

        steps_cache = self._steps_mem[system_id]
        next_n, loop_id, target_steps = steps_cache[target_n]

        # Build rank/label lookup for loops
        loop_rank_map: Dict[int, Dict[str, Any]] = {
            lp["loop_id"]: lp for lp in range_result["loops"]
        }

        # 1. Forward trajectory ("前": toward loop)
        forward_orbit: List[Dict[str, Any]] = []
        curr = target_n
        visited_forward = set()
        step_idx = 0
        while curr not in visited_forward and step_idx <= min(max_steps, 500):
            visited_forward.add(curr)
            nxt, lid, st = self.ensure_number_evaluated(
                system_id, curr, p, d, q_norm, max_steps, new_loops, new_nodes
            )
            r = curr % d
            if r == 0:
                rule_str = f"{curr} / {d} = {nxt}"
            else:
                rule_str = f"{p}×{curr} + {q_norm[r]} = {nxt}"
            forward_orbit.append(
                {
                    "offset": step_idx,
                    "n": curr,
                    "r": r,
                    "next_n": nxt,
                    "rule": rule_str,
                    "steps": st,
                    "loop_id": lid,
                    "is_loop_member": (st == 0 and lid > 0),
                }
            )
            if st == 0 and step_idx > 0:
                break
            curr = nxt
            step_idx += 1

        immediate_forward = forward_orbit[1] if len(forward_orbit) > 1 else None

        # 2. Inverse steps / Predecessors ("後": m such that T(m) = target_n, and 2-step T^{-2}(target_n))
        preds_step1_raw = predecessors_pq(target_n, p, d, q_norm)
        predecessors_step1: List[Dict[str, Any]] = []
        predecessors_step2: List[Dict[str, Any]] = []

        for pred in preds_step1_raw:
            m1 = pred["n"]
            _, m1_lid, m1_steps = self.ensure_number_evaluated(
                system_id, m1, p, d, q_norm, max_steps, new_loops, new_nodes
            )
            pred_entry = {
                "step_distance": 1,
                "n": m1,
                "r": pred["r"],
                "branch_type": pred["branch_type"],
                "formula": pred["formula"],
                "target_n": target_n,
                "steps": m1_steps,
                "loop_id": m1_lid,
                "is_loop_member": (m1_steps == 0 and m1_lid > 0),
            }
            predecessors_step1.append(pred_entry)

            # 2-step predecessors (children of m1)
            preds_step2_raw = predecessors_pq(m1, p, d, q_norm)
            for pred2 in preds_step2_raw:
                m2 = pred2["n"]
                _, m2_lid, m2_steps = self.ensure_number_evaluated(
                    system_id, m2, p, d, q_norm, max_steps, new_loops, new_nodes
                )
                predecessors_step2.append(
                    {
                        "step_distance": 2,
                        "n": m2,
                        "r": pred2["r"],
                        "branch_type": pred2["branch_type"],
                        "formula": pred2["formula"],
                        "via_n": m1,
                        "steps": m2_steps,
                        "loop_id": m2_lid,
                        "is_loop_member": (m2_steps == 0 and m2_lid > 0),
                    }
                )

        # Persist any newly evaluated predecessor nodes to SQLite
        if new_loops or new_nodes:
            with self._get_conn() as conn:
                with conn:
                    if new_loops:
                        conn.executemany(
                            """
                            INSERT OR IGNORE INTO loops
                            (system_id, loop_id, min_value, length, members_json)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            new_loops,
                        )
                    if new_nodes:
                        conn.executemany(
                            """
                            INSERT OR IGNORE INTO steps_cache
                            (system_id, n, next_n, loop_id, steps)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            new_nodes,
                        )

        # 3. Numbers at the exact same height (`steps == target_steps`) within [n_start, n_end]
        same_height_nodes: List[Dict[str, Any]] = []
        total_same_height = 0
        for n in range(n_start, n_end + 1):
            nxt_v, lid_v, st_v = steps_cache[n]
            if st_v == target_steps:
                total_same_height += 1
                if len(same_height_nodes) < same_height_limit:
                    lp_info = loop_rank_map.get(lid_v, {})
                    same_height_nodes.append(
                        {
                            "n": n,
                            "steps": st_v,
                            "loop_id": lid_v,
                            "loop_rank": lp_info.get("rank", 0),
                            "next_n": nxt_v,
                            "r": n % d,
                            "diff_from_target": n - target_n,
                            "same_loop": (lid_v == loop_id),
                        }
                    )

        target_loop_info = loop_rank_map.get(loop_id, {})
        logger.info(
            "Fetched node details for n=%d (system_id=%d, steps=%d, loop_id=%d): "
            "%d 1-step preds, %d 2-step preds, %d same-height nodes",
            target_n,
            system_id,
            target_steps,
            loop_id,
            len(predecessors_step1),
            len(predecessors_step2),
            total_same_height,
        )

        return {
            "target": {
                "n": target_n,
                "r": target_n % d,
                "steps": target_steps,
                "next_n": next_n,
                "loop_id": loop_id,
                "loop_rank": target_loop_info.get("rank", 0),
                "loop_label": target_loop_info.get("label", ""),
                "loop_members": target_loop_info.get("members", []),
                "rule": forward_orbit[0]["rule"] if forward_orbit else "",
            },
            "algorithmic_neighbors": {
                "immediate_forward": immediate_forward,
                "predecessors_step1": predecessors_step1,
                "predecessors_step2": predecessors_step2,
                "forward_orbit": forward_orbit,
            },
            "same_height": {
                "height": target_steps,
                "total_count_in_range": total_same_height,
                "nodes": same_height_nodes,
            },
        }

    def build_loop_tree(
        self,
        p: int,
        q_input: List[Optional[int]],
        loop_id: Optional[int] = None,
        root_n: Optional[int] = None,
        root_mode: str = "loop",
        max_height: int = 10,
        max_nodes: int = 10000,
    ) -> Dict[str, Any]:
        """
        Build the inverse CTree (up to `max_height` levels of predecessors T_{p,Q}^{-1})
        rooted either at all members of a loop (`root_mode="loop"`) or at a specific
        starting integer `root_n` (`root_mode="single"`).
        """
        t0 = time.perf_counter()
        validation = validate_pq(p, q_input)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        q_norm = validation["q_normalized"]
        d = p - 1

        max_height = max(1, min(int(max_height), 25))
        max_nodes = max(50, min(int(max_nodes), 50000))

        with self._get_conn() as conn:
            system_id = self._get_or_create_system(conn, p, q_norm)

        # Ensure initial range is evaluated if no loops are loaded yet
        if not self._loops_mem.get(system_id):
            self.compute_range(p=p, q_input=q_norm, n_start=1, n_end=2000)

        loops_by_id = self._loops_mem[system_id]
        steps_cache = self._steps_mem[system_id]

        # Resolve target loop
        target_loop: Optional[Dict[str, Any]] = None
        if loop_id is not None and int(loop_id) in loops_by_id:
            target_loop = loops_by_id[int(loop_id)]
        elif root_n is not None and int(root_n) >= 1:
            rn = int(root_n)
            new_l: List[Tuple[int, int, int, int, str]] = []
            new_n: List[Tuple[int, int, int, int, int]] = []
            _, lid, _ = self.ensure_number_evaluated(
                system_id, rn, p, d, q_norm, 10000, new_l, new_n
            )
            if lid in loops_by_id:
                target_loop = loops_by_id[lid]

        if target_loop is None and loops_by_id:
            # Default to first loop ordered by min_value
            target_loop = sorted(loops_by_id.values(), key=lambda x: x["min_value"])[0]

        loop_members: List[int] = target_loop["members"] if target_loop else []
        loop_member_set = set(loop_members)

        # Format detailed loop member transitions
        loop_elements_detail: List[Dict[str, Any]] = []
        for idx, m_val in enumerate(loop_members):
            nxt_val = loop_members[(idx + 1) % len(loop_members)]
            r_val = m_val % d
            rule_str = (
                f"{m_val} / {d} = {nxt_val}"
                if r_val == 0
                else f"{p}×{m_val} + {q_norm[r_val]} = {nxt_val}"
            )
            loop_elements_detail.append(
                {
                    "index": idx,
                    "n": m_val,
                    "r": r_val,
                    "next_n": nxt_val,
                    "rule": rule_str,
                }
            )

        counts_by_height: Dict[int, int] = defaultdict(int)
        total_nodes_created = 0
        truncated = False

        def expand_subtree(
            curr_n: int,
            curr_height: int,
            branch_r: int,
            formula: str,
            is_loop_node: bool,
        ) -> Dict[str, Any]:
            nonlocal total_nodes_created, truncated
            total_nodes_created += 1
            counts_by_height[curr_height] += 1

            node_obj: Dict[str, Any] = {
                "n": curr_n,
                "height": curr_height,
                "r": curr_n % d,
                "branch_r": branch_r,
                "formula": formula,
                "is_loop": is_loop_node,
                "children": [],
            }

            if curr_height >= max_height:
                return node_obj
            if total_nodes_created >= max_nodes:
                truncated = True
                return node_obj

            preds = predecessors_pq(curr_n, p, d, q_norm)
            for pred in preds:
                m_child = pred["n"]
                # Avoid re-entering the cycle itself when expanding outward from the loop
                if m_child in loop_member_set:
                    continue
                if total_nodes_created >= max_nodes:
                    truncated = True
                    break
                child_node = expand_subtree(
                    curr_n=m_child,
                    curr_height=curr_height + 1,
                    branch_r=pred["r"],
                    formula=pred["formula"],
                    is_loop_node=False,
                )
                node_obj["children"].append(child_node)

            return node_obj

        if root_mode == "single" and root_n is not None and int(root_n) >= 1:
            start_val = int(root_n)
            # Determine actual step height of start_val if known
            base_h = 0
            if start_val in steps_cache:
                base_h = max(0, steps_cache[start_val][2])
            is_in_loop = start_val in loop_member_set
            # Expand up to base_h + max_height
            effective_limit = max_height

            def expand_from_single(
                curr_n: int,
                rel_depth: int,
                abs_height: int,
                branch_r: int,
                formula: str,
            ) -> Dict[str, Any]:
                nonlocal total_nodes_created, truncated
                total_nodes_created += 1
                counts_by_height[abs_height] += 1
                node_obj: Dict[str, Any] = {
                    "n": curr_n,
                    "height": abs_height,
                    "rel_depth": rel_depth,
                    "r": curr_n % d,
                    "branch_r": branch_r,
                    "formula": formula,
                    "is_loop": (curr_n in loop_member_set),
                    "children": [],
                }
                if rel_depth >= effective_limit:
                    return node_obj
                if total_nodes_created >= max_nodes:
                    truncated = True
                    return node_obj

                for pred in predecessors_pq(curr_n, p, d, q_norm):
                    m_child = pred["n"]
                    if m_child in loop_member_set and m_child != start_val:
                        continue
                    if m_child == start_val:
                        continue
                    if total_nodes_created >= max_nodes:
                        truncated = True
                        break
                    node_obj["children"].append(
                        expand_from_single(
                            curr_n=m_child,
                            rel_depth=rel_depth + 1,
                            abs_height=abs_height + 1,
                            branch_r=pred["r"],
                            formula=pred["formula"],
                        )
                    )
                return node_obj

            tree_root = expand_from_single(
                curr_n=start_val,
                rel_depth=0,
                abs_height=base_h,
                branch_r=start_val % d,
                formula="Root",
            )
        else:
            # Root mode == "loop": Root hub holds all loop members at height 0,
            # and each loop member expands its non-loop predecessors up to height `max_height`.
            loop_children: List[Dict[str, Any]] = []
            for m_val in loop_members:
                if total_nodes_created >= max_nodes:
                    truncated = True
                    break
                loop_children.append(
                    expand_subtree(
                        curr_n=m_val,
                        curr_height=0,
                        branch_r=m_val % d,
                        formula="Loop Member (h=0)",
                        is_loop_node=True,
                    )
                )
            min_v = target_loop["min_value"] if target_loop else 0
            tree_root = {
                "n": f"Loop (min={min_v})",
                "height": -1,
                "r": -1,
                "branch_r": -1,
                "formula": "Loop Hub",
                "is_loop": True,
                "is_virtual_hub": True,
                "children": loop_children,
            }

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Built CTree for p=%d, Q=%s, loop_id=%s, root_mode=%s, root_n=%s, max_height=%d -> %d nodes (%.2f ms)",
            p,
            q_norm,
            loop_id,
            root_mode,
            root_n,
            max_height,
            total_nodes_created,
            elapsed_ms,
        )

        return {
            "p": p,
            "d": d,
            "q": q_norm,
            "root_mode": root_mode,
            "root_n": root_n,
            "max_height": max_height,
            "total_nodes": total_nodes_created,
            "truncated": truncated,
            "elapsed_ms": round(elapsed_ms, 2),
            "counts_by_height": dict(sorted(counts_by_height.items())),
            "loop": {
                "loop_id": target_loop["loop_id"] if target_loop else 0,
                "min_value": target_loop["min_value"] if target_loop else 0,
                "length": target_loop["length"] if target_loop else 0,
                "members": loop_members,
                "elements": loop_members,
                "elements_detail": loop_elements_detail,
            },
            "tree": tree_root,
        }

    def export_plot_bytes(
        self,
        p: int,
        q_input: List[Optional[int]],
        n_start: int = 1,
        n_end: int = 10000,
        max_steps: int = 10000,
        fmt: str = "png",
        visible_loop_ids: Optional[List[int]] = None,
        custom_colors: Optional[Dict[str, str]] = None,
        node_size: float = 4.0,
        opacity: float = 0.88,
    ) -> bytes:
        """
        Render a publication-grade plot (1800x1000 PNG or vector SVG) matching plot_3n5.py.
        """
        res = self.compute_range(
            p=p, q_input=q_input, n_start=n_start, n_end=n_end, max_steps=max_steps
        )
        loops = res["loops"]
        pts_n = res["points"]["n"]
        pts_steps = res["points"]["steps"]
        pts_lid = res["points"]["loop_id"]

        visible_set = (
            set(int(x) for x in visible_loop_ids)
            if visible_loop_ids is not None
            else {lp["loop_id"] for lp in loops}
        )
        color_override = custom_colors or {}

        xs_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}
        ys_by_loop: Dict[int, List[int]] = {lp["loop_id"]: [] for lp in loops}

        max_y = 0
        for n_val, st_val, lid_val in zip(pts_n, pts_steps, pts_lid):
            if lid_val not in visible_set or st_val < 0:
                continue
            xs_by_loop[lid_val].append(n_val)
            ys_by_loop[lid_val].append(st_val)
            if st_val > max_y:
                max_y = st_val

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

        fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=200)
        marker_area = max(node_size, 0.5) ** 2

        for lp in loops:
            lid = lp["loop_id"]
            if lid not in visible_set:
                continue
            color = color_override.get(str(lid), lp["color"])
            ax.scatter(
                xs_by_loop.get(lid, []),
                ys_by_loop.get(lid, []),
                s=marker_area,
                c=color,
                label=lp["label"],
                alpha=opacity,
                edgecolors="none",
                rasterized=False,
            )

        ax.set_xlabel("N", labelpad=8)
        ax.set_ylabel("iterN", labelpad=8)
        ax.set_xlim(n_start if n_start > 1 else 0, n_end)

        y_top = max(int(max_y * 1.22), 50)
        y_top = ((y_top + 49) // 50) * 50
        ax.set_ylim(0, y_top)

        span = n_end - (0 if n_start == 1 else n_start)
        if span >= 10 and span % 10 == 0:
            ax.xaxis.set_major_locator(MultipleLocator(span / 10))
        if n_end >= 10000:
            exp = max(int(math.floor(math.log10(n_end))) - 1, 3)
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

        if any(lid in visible_set for lid in xs_by_loop):
            ax.legend(
                loc="upper left",
                ncol=2,
                frameon=True,
                facecolor="white",
                edgecolor="#cccccc",
                framealpha=0.92,
                markerscale=2.0,
                columnspacing=1.2,
                handletextpad=0.4,
            )

        fig.subplots_adjust(left=0.085, right=0.975, bottom=0.14, top=0.95)

        buf = io.BytesIO()
        fmt_clean = "svg" if fmt.lower() == "svg" else "png"
        fig.savefig(buf, format=fmt_clean, dpi=200)
        plt.close(fig)
        buf.seek(0)
        data = buf.read()
        logger.info(
            "Exported %s image (%d bytes) for p=%d, Q=%s, range=[%d..%d]",
            fmt_clean.upper(),
            len(data),
            p,
            res["q"],
            n_start,
            n_end,
        )
        return data

