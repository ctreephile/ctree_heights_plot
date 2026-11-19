"""
Phase 3: Test whether the q_r mod p collision effects (faster convergence, shorter loops,
and massive CTree width explosion) are amplified at larger even p (p=8, p=10) with low sea level.

Compares 4 groups (N=25 each) within the same low-sea-level range [1, 2*p*d]:
  1. every_step_c0:     q_r == 0 (mod p)     [every-step burst, gcd(Q) >= p]
  2. every_step_c_half: q_r == p/2 (mod p)   [every-step burst, -c == c mod p]
  3. alternating_c1:    q_r == 1 (mod p)     [alternating burst, gcd(Q) == 1]
  4. binary_distinct:   all q_r mod p distinct [<=2-way binary, gcd(Q) == 1]
"""

from __future__ import annotations

import math
import random
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from analyze_modp_collision import measure_ctree_bfs, write_csv


def crt_min_q(p: int, r: int, c: int) -> int:
    """Smallest positive q such that q % (p-1) == (-r) % (p-1) and q % p == c % p."""
    d = p - 1
    target_d = (-r) % d
    target_p = c % p
    for q in range(1, p * d + 1):
        if q % d == target_d and q % p == target_p:
            return q
    raise RuntimeError(f"CRT failed for p={p}, r={r}, c={c}")


def sample_q_collide(p: int, c: int, count: int, max_k: int, rng: random.Random) -> List[Tuple[int, ...]]:
    """Sample distinct Q tuples where all q_r == c (mod p) and k_r in [0..max_k]."""
    d = p - 1
    bases = [crt_min_q(p, r, c) for r in range(1, d)]
    seen = set()
    res: List[Tuple[int, ...]] = []
    attempts = 0
    while len(res) < count and attempts < count * 50:
        attempts += 1
        q_tup = tuple(b + rng.randint(0, max_k) * (p * d) for b in bases)
        if q_tup not in seen:
            seen.add(q_tup)
            res.append(q_tup)
    return res


def sample_q_binary_distinct(p: int, count: int, max_k: int, rng: random.Random) -> List[Tuple[int, ...]]:
    """Sample Q tuples with all q_r mod p distinct, gcd(Q)==1, in [1, (max_k+1)*p*d]."""
    d = p - 1
    seen = set()
    res: List[Tuple[int, ...]] = []
    attempts = 0
    while len(res) < count and attempts < count * 200:
        attempts += 1
        chosen_mods = rng.sample(range(p), d - 1)
        q_tup = tuple(crt_min_q(p, r, chosen_mods[r - 1]) + rng.randint(0, max_k) * (p * d) for r in range(1, d))
        if math.gcd(*q_tup) != 1:
            continue
        if q_tup not in seen:
            seen.add(q_tup)
            res.append(q_tup)
    return res


def evaluate_system(p: int, q_tup: Tuple[int, ...], max_n: int = 50000, max_steps: int = 3000) -> Dict[str, Any]:
    """Fast memoized evaluation of trajectories 1..max_n."""
    d = p - 1
    steps_cache: Dict[int, Tuple[int, int]] = {}
    loops: Dict[int, Dict[str, Any]] = {}
    next_lid = 1
    unresolved = 0

    for start_n in range(1, max_n + 1):
        if start_n in steps_cache:
            continue
        path: List[int] = []
        path_idx: Dict[int, int] = {}
        curr = start_n

        while curr not in steps_cache and curr not in path_idx and len(path) <= max_steps:
            path_idx[curr] = len(path)
            path.append(curr)
            r = curr % d
            if r == 0:
                curr //= d
            else:
                curr = p * curr + q_tup[r - 1]

        if curr in steps_cache:
            ks, klid = steps_cache[curr]
            for i, val in enumerate(reversed(path), start=1):
                steps_cache[val] = (ks + i, klid)
        elif curr in path_idx:
            c_start = path_idx[curr]
            cycle = path[c_start:]
            min_v = min(cycle)
            lid = next_lid
            next_lid += 1
            loops[lid] = {"min_value": min_v, "length": len(cycle), "basin_count": 0}
            for val in cycle:
                steps_cache[val] = (0, lid)
            for i, val in enumerate(reversed(path[:c_start]), start=1):
                steps_cache[val] = (i, lid)
        else:
            unresolved += 1
            for val in path:
                steps_cache[val] = (-1, -1)

    total_steps = 0
    max_obs_steps = 0
    resolved = 0
    for n in range(1, max_n + 1):
        s, lid = steps_cache[n]
        if lid > 0:
            resolved += 1
            total_steps += s
            if s > max_obs_steps:
                max_obs_steps = s
            loops[lid]["basin_count"] += 1

    loop_list = list(loops.values())
    top_loop = max(loop_list, key=lambda x: x["basin_count"]) if loop_list else {"min_value": 0, "length": 0, "basin_count": 0}
    max_len = max((x["length"] for x in loop_list), default=0)
    max_share = top_loop["basin_count"] / resolved if resolved else 0.0
    avg_steps = total_steps / resolved if resolved else 0.0

    return {
        "num_loops": len(loop_list),
        "max_len": max_len,
        "avg_steps": avg_steps,
        "max_steps": max_obs_steps,
        "unresolved": unresolved,
        "max_share": max_share,
        "top_loop_min_val": top_loop["min_value"],
    }


def main() -> None:
    rng = random.Random(20261116)
    max_n = 50000
    max_h = 10
    sample_count = 25
    max_k = 1  # low sea level: q_r <= 2*p*d

    rows: List[Dict[str, Any]] = []
    for p in [8, 10]:
        t0 = time.time()
        groups = [
            ("every_step_c0", sample_q_collide(p, 0, sample_count, max_k, rng)),
            ("every_step_c_half", sample_q_collide(p, p // 2, sample_count, max_k, rng)),
            ("alternating_c1", sample_q_collide(p, 1, sample_count, max_k, rng)),
            ("binary_distinct", sample_q_binary_distinct(p, sample_count, max_k, rng)),
        ]
        print(f"\n================ Phase 3: p={p} (d={p-1}, burst={p-1}-way, N={sample_count}/group, n<={max_n}) ================")
        print(f"{'Group':<20} | {'loops':>5} {'maxLen':>6} {'avgStp':>6} {'maxStp':>6} {'maxShr':>6} | {'nodes@H10':>9} {'W(10)':>7} {'bursts':>6}")
        print("-" * 92)

        for gname, q_list_batch in groups:
            g_recs = []
            for q_tup in q_list_batch:
                ev = evaluate_system(p, q_tup, max_n=max_n)
                root = ev["top_loop_min_val"]
                ct = measure_ctree_bfs(p, list(q_tup), root, max_h=max_h) if root > 0 else {
                    "total_nodes": 0, "width_at_h": 0, "burst_nodes": 0
                }
                rec = {
                    "p": p,
                    "group": gname,
                    "q": str(q_tup),
                    "gcd_q": math.gcd(*q_tup),
                    "mean_q": sum(q_tup) / len(q_tup),
                    **ev,
                    "ctree_nodes_h10": ct["total_nodes"],
                    "ctree_w10": ct["width_at_h"],
                    "ctree_bursts": ct["burst_nodes"],
                }
                g_recs.append(rec)
                rows.append(rec)

            avg = lambda k: statistics.mean(r[k] for r in g_recs)
            print(
                f"{gname:<20} | {avg('num_loops'):>5.2f} {avg('max_len'):>6.1f} "
                f"{avg('avg_steps'):>6.2f} {avg('max_steps'):>6.1f} {avg('max_share'):>6.3f} | "
                f"{avg('ctree_nodes_h10'):>9.1f} {avg('ctree_w10'):>7.1f} {avg('ctree_bursts'):>6.1f}"
            )
        print(f"Elapsed for p={p}: {time.time() - t0:.1f}s")

    out_path = Path("outputs/modp_collision/phase3_amplification.csv")
    write_csv(out_path, rows)
    print(f"\nSaved Phase 3 results to {out_path}")


if __name__ == "__main__":
    main()

