"""Algebraic invariants and existing-dataset loaders for generalized (p, Q) Collatz systems."""

from __future__ import annotations

import csv
import functools
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def p_free_core(g: int, p: int) -> int:
    """Return the largest divisor of g coprime to p."""
    if g <= 0:
        raise ValueError(f"g must be positive, got {g}")
    if p < 2:
        raise ValueError(f"p must be >= 2, got {p}")
    c = g
    while True:
        d = math.gcd(c, p)
        if d == 1:
            return c
        c //= d


def is_prime(n: int) -> bool:
    """Return True if integer n >= 2 is prime."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    k = 5
    while k * k <= n:
        if n % k == 0 or n % (k + 2) == 0:
            return False
        k += 6
    return True


_is_prime = is_prime


def euler_phi(n: int) -> int:
    """Compute Euler's totient phi(n) for n >= 1."""
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    result = n
    x = n
    f = 2
    while f * f <= x:
        if x % f == 0:
            while x % f == 0:
                x //= f
            result -= result // f
        f += 1 if f == 2 else 2
    if x > 1:
        result -= result // x
    return result


@dataclass(frozen=True)
class SystemSpec:
    """Immutable specification of a generalized (p, Q) Collatz system."""

    p: int
    q_tuple: tuple[int, ...]

    @property
    def d(self) -> int:
        return self.p - 1

    @property
    def q_norm(self) -> list[int | None]:
        return [None, *self.q_tuple]

    @property
    def gcd_q(self) -> int:
        return math.gcd(*self.q_tuple)

    @property
    def g_core(self) -> int:
        return p_free_core(self.gcd_q, self.p)

    @property
    def label(self) -> str:
        return f"p{self.p}_Q({','.join(map(str, self.q_tuple))})"

    def is_valid(self) -> bool:
        if self.p < 3 or len(self.q_tuple) != self.p - 2:
            return False
        d = self.d
        for r, qr in enumerate(self.q_tuple, start=1):
            if qr <= 0 or (self.p * r + qr) % d != 0:
                return False
        return True

    def scale(self, k: int) -> SystemSpec:
        """Return conjugate system satisfying T_{p, Q'}(k*n) = k * T_{p, Q}(n) for gcd(k, d) == 1."""
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")
        d = self.d
        if math.gcd(k, d) != 1:
            raise ValueError(f"k={k} must be coprime to d={d}")
        scaled = [0] * (d - 1)
        for r, qr in enumerate(self.q_tuple, start=1):
            r_prime = (k * r) % d
            scaled[r_prime - 1] = k * qr
        spec = SystemSpec(self.p, tuple(scaled))
        if not spec.is_valid():
            raise ValueError(f"Scaled spec is invalid: {spec}")
        return spec


def primitive_family_key(p: int, q_tuple: tuple[int, ...]) -> tuple[int, tuple[int, ...]]:
    """Return (g, base_q_tuple) such that SystemSpec(p, base_q_tuple).scale(g) == SystemSpec(p, q_tuple)."""
    spec = SystemSpec(p, q_tuple)
    if not spec.is_valid():
        raise ValueError(f"Invalid system spec: {spec}")
    g = spec.gcd_q
    if g == 1:
        return 1, q_tuple
    d = p - 1
    if math.gcd(g, d) != 1:
        raise ValueError(f"gcd(q)={g} is not coprime to d={d}")
    base = tuple(q_tuple[((g * r) % d) - 1] // g for r in range(1, d))
    base_spec = SystemSpec(p, base)
    if not base_spec.is_valid() or base_spec.gcd_q != 1:
        raise ValueError(f"Failed primitive extraction for {spec}: got {base_spec}")
    return g, base


@dataclass(frozen=True)
class CosetStructure:
    """Multiplicative subgroup H_p(m) = <p, p-1> <= (Z/mZ)^* and its cosets."""

    p: int
    m: int
    phi: int
    subgroup_order: int
    index: int
    subgroup: frozenset[int]
    cosets: tuple[frozenset[int], ...]
    residue_to_coset: dict[int, int]
    is_pure_composite_coupling: bool


@functools.lru_cache(maxsize=None)
def multiplicative_subgroup_cosets(p: int, m: int) -> CosetStructure:
    """Compute subgroup H_p(m) = <p, p-1> in (Z/mZ)^* and coset lookup table."""
    if p < 3:
        raise ValueError(f"p must be >= 3, got {p}")
    if m < 2:
        raise ValueError(f"m must be >= 2, got {m}")
    d = p - 1
    if math.gcd(m, p) != 1 or math.gcd(m, d) != 1:
        raise ValueError(f"m={m} must be coprime to p={p} and d={d}")

    units = [x for x in range(1, m) if math.gcd(x, m) == 1]
    sub_set = {1}
    frontier = [1]
    gens = (p % m, d % m)
    while frontier:
        cur = frontier.pop()
        for gen in gens:
            nxt = (cur * gen) % m
            if nxt not in sub_set:
                sub_set.add(nxt)
                frontier.append(nxt)

    cosets_list: list[frozenset[int]] = []
    seen: set[int] = set()
    for u in units:
        if u not in seen:
            c = frozenset((u * h) % m for h in sub_set)
            cosets_list.append(c)
            seen |= c
    cosets_list.sort(key=lambda c: min(c))

    res_map: dict[int, int] = {}
    for cid, cset in enumerate(cosets_list):
        for r in cset:
            res_map[r] = cid

    phi = len(units)
    sub_order = len(sub_set)
    index = phi // sub_order

    is_pure_comp = False
    if index >= 2 and not _is_prime(m):
        proper_divs = [k for k in range(2, m) if m % k == 0]
        is_pure_comp = all(multiplicative_subgroup_cosets(p, k).index == 1 for k in proper_divs)

    return CosetStructure(
        p=p,
        m=m,
        phi=phi,
        subgroup_order=sub_order,
        index=index,
        subgroup=frozenset(sub_set),
        cosets=tuple(cosets_list),
        residue_to_coset=res_map,
        is_pure_composite_coupling=is_pure_comp,
    )


@functools.lru_cache(maxsize=None)
def _subgroup_index_gen2(m: int) -> tuple[int, dict[int, int]]:
    """Compute index and coset map for <2> <= (Z/mZ)^* (odd m >= 3)."""
    units = [x for x in range(1, m) if math.gcd(x, m) == 1]
    sub = {1}
    cur = 2 % m
    while cur not in sub:
        sub.add(cur)
        cur = (cur * 2) % m
    cosets: list[frozenset[int]] = []
    seen: set[int] = set()
    for u in units:
        if u not in seen:
            c = frozenset((u * h) % m for h in sub)
            cosets.append(c)
            seen |= c
    cosets.sort(key=lambda c: min(c))
    rmap: dict[int, int] = {}
    for cid, cset in enumerate(cosets):
        for r in cset:
            rmap[r] = cid
    return len(cosets), rmap


def shifted_coset_map(m: int) -> tuple[int, dict[int, int]]:
    """Return (index_of_<2>_mod_m, residue_to_coset) for odd m >= 3."""
    if m < 3 or m % 2 == 0:
        raise ValueError(f"m must be odd >= 3, got {m}")
    return _subgroup_index_gen2(m)


def find_shifted_congruences(p: int, q_tuple: tuple[int, ...]) -> list[tuple[int, int, int]]:
    """Find odd divisors m > 1 of (p - 2) where q_1 == ... == q_{d-1} == c (mod m), c != 0.

    Returns a list of (m, c, idx2), where idx2 is the index of <2> in (Z/mZ)^*.
    """
    pm2 = p - 2
    if pm2 < 3:
        return []
    odd_divs = [m for m in range(3, pm2 + 1, 2) if pm2 % m == 0]
    found: list[tuple[int, int, int]] = []
    for m in odd_divs:
        mods = {qr % m for qr in q_tuple}
        if len(mods) == 1:
            c = next(iter(mods))
            if c != 0:
                idx2, _ = _subgroup_index_gen2(m)
                found.append((m, c, idx2))
    return found


def make_minimal_q_for_m(
    p: int,
    m: int,
    shift_idx: int = 0,
    c_mod_m: int = 0,
) -> SystemSpec:
    """Construct a minimal valid SystemSpec(p, Q) with q_r == c_mod_m (mod m) for all r."""
    if p < 3:
        raise ValueError(f"p must be >= 3, got {p}")
    d = p - 1
    if m < 2 or math.gcd(m, d) != 1:
        raise ValueError(f"m={m} must be >= 2 and coprime to d={d}")
    qs: list[int] = []
    step_lcm = math.lcm(d, m)
    target_c = c_mod_m % m
    for r in range(1, d):
        req_d = (d - r) % d
        val = None
        for k in range(m):
            cand = req_d + k * d
            if cand > 0 and cand % m == target_c:
                val = cand
                break
        if val is None:
            raise ValueError(f"No CRT solution for r={r}, d={d}, m={m}, c={c_mod_m}")
        if r == d - 1 and shift_idx > 0:
            val += shift_idx * step_lcm
        qs.append(val)
    spec = SystemSpec(p, tuple(qs))
    if not spec.is_valid():
        raise ValueError(f"Constructed invalid spec: {spec}")
    return spec


@dataclass
class LoopRecord:
    """Loop metadata loaded from existing summary DB/CSV."""

    min_value: int
    length: int
    basin_count: int | None
    basin_share: float


@dataclass
class SystemRecord:
    """System + loops record loaded from existing dataset."""

    spec: SystemSpec
    n_max: int
    num_loops: int
    loops: list[LoopRecord]
    source: str


def load_p4_grid80(base_dir: Path | str = Path(".")) -> list[SystemRecord]:
    """Load existing p=4 80x80 grid summary and loop catalog (read-only)."""
    base = Path(base_dir)
    summary_path = base / "outputs" / "p4_grid_80x80" / "summary.csv"
    loops_path = base / "outputs" / "p4_grid_80x80" / "loops_catalog.csv"

    loops_by_q: dict[tuple[int, int], list[LoopRecord]] = defaultdict(list)
    with loops_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (int(row["q1"]), int(row["q2"]))
            share = float(row["basin_share_pct"]) / 100.0
            loops_by_q[key].append(
                LoopRecord(
                    min_value=int(row["min_value"]),
                    length=int(row["length"]),
                    basin_count=None,
                    basin_share=share,
                )
            )

    records: list[SystemRecord] = []
    with summary_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            q1 = int(row["q1"])
            q2 = int(row["q2"])
            spec = SystemSpec(4, (q1, q2))
            records.append(
                SystemRecord(
                    spec=spec,
                    n_max=100000,
                    num_loops=int(row["num_loops"]),
                    loops=sorted(loops_by_q[(q1, q2)], key=lambda l: l.min_value),
                    source="outputs/p4_grid_80x80",
                )
            )
    return records


def load_sqlite_summary(
    p: int,
    base_dir: Path | str = Path("."),
    q1_max: int | None = None,
) -> list[SystemRecord]:
    """Load existing data/p{p}/summary_p{p}.db (read-only)."""
    base = Path(base_dir)
    db_path = base / "data" / f"p{p}" / f"summary_p{p}.db"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        if q1_max is not None and p == 3:
            sys_rows = cur.execute(
                "SELECT system_id, q_json, n_max, num_loops FROM systems WHERE q1 <= ?",
                (q1_max,),
            ).fetchall()
        else:
            sys_rows = cur.execute(
                "SELECT system_id, q_json, n_max, num_loops FROM systems"
            ).fetchall()

        sys_ids = {int(r[0]) for r in sys_rows}
        loops_by_sid: dict[int, list[LoopRecord]] = defaultdict(list)
        if q1_max is not None and p == 3:
            loop_rows = cur.execute(
                """
                SELECT l.system_id, l.min_value, l.length, l.basin_count, l.basin_share
                FROM loops l
                JOIN systems s ON s.system_id = l.system_id
                WHERE s.q1 <= ?
                """,
                (q1_max,),
            ).fetchall()
        else:
            loop_rows = cur.execute(
                "SELECT system_id, min_value, length, basin_count, basin_share FROM loops"
            ).fetchall()

        for sid, mv, length, bc, bs in loop_rows:
            sid_int = int(sid)
            if sid_int in sys_ids:
                loops_by_sid[sid_int].append(
                    LoopRecord(
                        min_value=int(mv),
                        length=int(length),
                        basin_count=int(bc),
                        basin_share=float(bs),
                    )
                )

        records: list[SystemRecord] = []
        for sid, qj, n_max, num_loops in sys_rows:
            sid_int = int(sid)
            q_list = json.loads(qj)[1:]
            spec = SystemSpec(p, tuple(int(v) for v in q_list))
            records.append(
                SystemRecord(
                    spec=spec,
                    n_max=int(n_max),
                    num_loops=int(num_loops),
                    loops=sorted(loops_by_sid[sid_int], key=lambda l: l.min_value),
                    source=f"data/p{p}/summary_p{p}.db",
                )
            )
        return records
    finally:
        con.close()

