"""Fast compressed-step generalized (p, Q) Collatz trajectory labeler."""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np

from .algebra import SystemSpec


@dataclass
class LoopInfo:
    """Metadata for a single cycle in a generalized (p, Q) system."""

    loop_min: int
    compressed_length: int
    full_length: int
    count_all: int = 0
    count_dfree: int = 0


@dataclass
class SolverResult:
    """1-indexed loop labels for n in [1, n_max] and per-loop summaries."""

    spec: SystemSpec
    n_max: int
    labels: np.ndarray
    loop_infos: dict[int, LoopInfo]
    unconverged_count: int
    elapsed_ms: float


def compute_labels(
    spec: SystemSpec,
    n_max: int,
    max_steps: int = 50000,
    max_bits: int = 2000,
) -> SolverResult:
    """Compute canonical loop min_value labels for all integers n in [1, n_max].

    Index `n` in `result.labels` (dtype int64, length n_max + 1) holds the minimum
    value of the cycle reached from `n`, or `-1` if `max_steps` / `max_bits` is
    exceeded. Index 0 is unused (0).
    """
    if not spec.is_valid():
        raise ValueError(f"Invalid system spec: {spec}")
    if n_max < 1:
        raise ValueError(f"n_max must be >= 1, got {n_max}")

    t0 = time.perf_counter()
    p = spec.p
    d = spec.d
    q_arr = [0, *spec.q_tuple]

    labels = [0] * (n_max + 1)
    high_limit = 4 * n_max
    high_cache: dict[int, int] = {}
    loop_infos: dict[int, LoopInfo] = {}

    for start in range(1, n_max + 1):
        if start % d == 0:
            labels[start] = labels[start // d]
            continue
        if labels[start] != 0:
            continue

        x = start
        path: list[int] = []
        seen: dict[int, int] = {}

        while True:
            if x <= n_max:
                cached = labels[x]
                if cached != 0:
                    lid = cached
                    break
            else:
                cached = high_cache.get(x)
                if cached is not None:
                    lid = cached
                    break

            cycle_start = seen.get(x)
            if cycle_start is not None:
                cycle = path[cycle_start:]
                lid = min(cycle)
                if lid not in loop_infos:
                    full_len = 0
                    for node in cycle:
                        val = p * node + q_arr[node % d]
                        steps = 1
                        while val % d == 0:
                            val //= d
                            steps += 1
                        full_len += steps
                    loop_infos[lid] = LoopInfo(
                        loop_min=lid,
                        compressed_length=len(cycle),
                        full_length=full_len,
                    )
                for node in cycle:
                    if node > n_max:
                        high_cache[node] = lid
                break

            if len(path) >= max_steps or x.bit_length() > max_bits:
                lid = -1
                break

            seen[x] = len(path)
            path.append(x)
            nx = p * x + q_arr[x % d]
            while nx % d == 0:
                nx //= d
            x = nx

        for node in path:
            if node <= n_max:
                labels[node] = lid
            elif node <= high_limit:
                high_cache[node] = lid

    arr = np.asarray(labels, dtype=np.int64)
    uniq, counts = np.unique(arr[1:], return_counts=True)
    unconverged_count = 0
    for u, c in zip(uniq.tolist(), counts.tolist()):
        if u <= 0:
            unconverged_count += c
        else:
            loop_infos[u].count_all = c

    dfree_mask = np.arange(1, n_max + 1, dtype=np.int64) % d != 0
    u_df, c_df = np.unique(arr[1:][dfree_mask], return_counts=True)
    for u, c in zip(u_df.tolist(), c_df.tolist()):
        if u > 0:
            loop_infos[u].count_dfree = c

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return SolverResult(
        spec=spec,
        n_max=n_max,
        labels=arr,
        loop_infos=loop_infos,
        unconverged_count=unconverged_count,
        elapsed_ms=elapsed_ms,
    )


def _solve_worker(args: tuple[SystemSpec, int, int, int]) -> SolverResult:
    spec, n_max, max_steps, max_bits = args
    return compute_labels(spec, n_max=n_max, max_steps=max_steps, max_bits=max_bits)


def compute_systems_parallel(
    specs: list[SystemSpec],
    n_max: int,
    workers: int | None = None,
    max_steps: int = 50000,
    max_bits: int = 2000,
) -> dict[SystemSpec, SolverResult]:
    """Compute SolverResult for a deduplicated list of SystemSpecs in parallel."""
    unique_specs: list[SystemSpec] = list(dict.fromkeys(specs))
    if not unique_specs:
        return {}

    if workers is None:
        workers = min(os.cpu_count() or 4, 8)

    if workers <= 1 or len(unique_specs) <= 2:
        return {
            spec: compute_labels(spec, n_max=n_max, max_steps=max_steps, max_bits=max_bits)
            for spec in unique_specs
        }

    tasks = [(spec, n_max, max_steps, max_bits) for spec in unique_specs]
    results: dict[SystemSpec, SolverResult] = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_solve_worker, tasks):
            results[res.spec] = res
    return results

