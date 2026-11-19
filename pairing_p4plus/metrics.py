"""Contingency tables, association metrics, set-equality/inclusion, and coset-leakage diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .algebra import multiplicative_subgroup_cosets, shifted_coset_map


@dataclass
class ContainmentBest:
    """Best directional near-containment or enrichment between two basins."""

    direction: str  # "X->A" or "A->X"
    source_loop: int
    target_loop: int
    cell_count: int
    source_total: int
    cond_prob: float
    baseline_prob: float
    containment_gain: float


@dataclass
class PairMetrics:
    """Association, exact equality, strict inclusion, and near-containment metrics."""

    total: int
    n_loops_a: int
    n_loops_b: int
    df: int
    chi2: float
    p_value: float
    cramers_v: float
    mi_bits: float
    nmi: float
    max_abs_std_resid: float
    exact_equalities: int
    exact_strict_inclusions: int
    exact_containments: int
    significant_zero_cells: int
    best_raw_purity: ContainmentBest | None
    best_gain: ContainmentBest | None
    exact_equal_pairs: tuple[tuple[int, int, int], ...]
    exact_inclusion_pairs: tuple[tuple[str, int, int, int, int], ...]


def chi2_sf(chi2: float, df: int) -> float:
    """Compute the upper-tail survival function P(Chi2_df >= chi2) = Q(df/2, chi2/2)."""
    if df <= 0 or chi2 <= 0.0:
        return 1.0
    a = 0.5 * df
    z = 0.5 * chi2
    log_pref = -z + a * math.log(z) - math.lgamma(a)

    if z < a + 1.0:
        if log_pref < -745.0:
            return 1.0
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(10000):
            ap += 1.0
            term *= z / ap
            total += term
            if abs(term) <= abs(total) * 1e-14:
                break
        p_val = total * math.exp(log_pref)
        return max(0.0, min(1.0, 1.0 - p_val))

    if log_pref < -745.0:
        return 0.0
    tiny = 1e-300
    eps = 1e-14
    b = z + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b if abs(b) > tiny else 1.0 / tiny
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) <= eps:
            break
    return max(0.0, min(1.0, math.exp(log_pref) * h))


def build_contingency(
    labels_a: np.ndarray,
    labels_b: np.ndarray,
    n_max: int | None = None,
    mask: np.ndarray | None = None,
) -> dict[tuple[int, int], int]:
    """Build a (label_a, label_b) -> count contingency dictionary from 1-indexed arrays."""
    limit = min(len(labels_a), len(labels_b)) - 1
    if n_max is not None:
        if n_max < 0 or n_max > limit:
            raise ValueError(f"n_max={n_max} out of bounds [0, {limit}]")
        limit = n_max

    a = labels_a[1 : limit + 1]
    b = labels_b[1 : limit + 1]
    if mask is not None:
        m = mask[:limit] if len(mask) >= limit else mask
        if len(m) != limit:
            raise ValueError(f"mask length {len(m)} != limit {limit}")
        a = a[m]
        b = b[m]

    if a.size == 0:
        return {}

    ua, inv_a = np.unique(a, return_inverse=True)
    ub, inv_b = np.unique(b, return_inverse=True)
    nb = int(ub.size)
    flat = inv_a * nb + inv_b
    counts = np.bincount(flat, minlength=int(ua.size) * nb)
    nz = np.nonzero(counts)[0]
    ua_list = ua.tolist()
    ub_list = ub.tolist()
    cnt_list = counts.tolist()
    return {(int(ua_list[idx // nb]), int(ub_list[idx % nb])): int(cnt_list[idx]) for idx in nz.tolist()}


def _marginals(ct: dict[tuple[int, int], int]) -> tuple[dict[int, int], dict[int, int], int]:
    ra: dict[int, int] = {}
    rb: dict[int, int] = {}
    total = 0
    for (a, b), cnt in ct.items():
        if cnt <= 0:
            continue
        ra[a] = ra.get(a, 0) + cnt
        rb[b] = rb.get(b, 0) + cnt
        total += cnt
    return ra, rb, total


def summarize_exact_relations(
    ct: dict[tuple[int, int], int],
    min_count: int = 1,
) -> dict[str, Any]:
    """Summarize exact set equalities and strict inclusions even on 1-loop tables."""
    ra, rb, total = _marginals(ct)
    eq_pairs: list[tuple[int, int, int]] = []
    inc_pairs: list[tuple[str, int, int, int, int]] = []

    for a, ca in sorted(ra.items()):
        for b, cb in sorted(rb.items()):
            cab = ct.get((a, b), 0)
            if cab == 0:
                continue
            if cab == ca and cab == cb and ca >= min_count:
                eq_pairs.append((a, b, cab))
            else:
                if cab == cb and cb < ca and cb >= min_count:
                    inc_pairs.append(("X->A", b, a, cb, ca))
                if cab == ca and ca < cb and ca >= min_count:
                    inc_pairs.append(("A->X", a, b, ca, cb))

    return {
        "total": total,
        "exact_equalities": len(eq_pairs),
        "exact_strict_inclusions": len(inc_pairs),
        "exact_containments": 2 * len(eq_pairs) + len(inc_pairs),
        "exact_equal_pairs": tuple(eq_pairs),
        "exact_inclusion_pairs": tuple(inc_pairs),
    }


def _evaluate_containment(
    ct: dict[tuple[int, int], int],
    ra: dict[int, int],
    rb: dict[int, int],
    total: int,
    min_count: int,
) -> tuple[
    int,
    int,
    int,
    ContainmentBest | None,
    ContainmentBest | None,
    tuple[tuple[int, int, int], ...],
    tuple[tuple[str, int, int, int, int], ...],
]:
    """Evaluate exact equalities, strict inclusions, and best near-containment."""
    rel = summarize_exact_relations(ct, min_count=min_count)
    best_raw: ContainmentBest | None = None
    best_gain: ContainmentBest | None = None

    def _update(cand_raw: ContainmentBest, cand_gain: ContainmentBest) -> None:
        nonlocal best_raw, best_gain
        if best_raw is None or (
            cand_raw.cond_prob,
            cand_raw.containment_gain,
            cand_raw.source_total,
        ) > (
            best_raw.cond_prob,
            best_raw.containment_gain,
            best_raw.source_total,
        ):
            best_raw = cand_raw
        if best_gain is None or (
            cand_gain.containment_gain,
            cand_gain.cond_prob,
            cand_gain.source_total,
        ) > (
            best_gain.containment_gain,
            best_gain.cond_prob,
            best_gain.source_total,
        ):
            best_gain = cand_gain

    # Direction X -> A: P(A=a | X=b)
    for b, cb in rb.items():
        if cb < min_count:
            continue
        best_a = max(ra.keys(), key=lambda a: ct.get((a, b), 0))
        c_ab = ct.get((best_a, b), 0)
        cond_p = c_ab / cb
        base_p = ra[best_a] / total
        if base_p < 1.0 - 1e-12:
            gain_best_raw = (cond_p - base_p) / (1.0 - base_p)
            cand_raw = ContainmentBest(
                direction="X->A",
                source_loop=b,
                target_loop=best_a,
                cell_count=c_ab,
                source_total=cb,
                cond_prob=cond_p,
                baseline_prob=base_p,
                containment_gain=gain_best_raw,
            )
            best_ga = None
            for a, ca in ra.items():
                bp = ca / total
                if bp >= 1.0 - 1e-12:
                    continue
                cab = ct.get((a, b), 0)
                cp = cab / cb
                g = (cp - bp) / (1.0 - bp)
                cand_g = ContainmentBest(
                    direction="X->A",
                    source_loop=b,
                    target_loop=a,
                    cell_count=cab,
                    source_total=cb,
                    cond_prob=cp,
                    baseline_prob=bp,
                    containment_gain=g,
                )
                if best_ga is None or (g, cp) > (best_ga.containment_gain, best_ga.cond_prob):
                    best_ga = cand_g
            if best_ga is not None:
                _update(cand_raw, best_ga)

    # Direction A -> X: P(X=b | A=a)
    for a, ca in ra.items():
        if ca < min_count:
            continue
        best_b = max(rb.keys(), key=lambda b: ct.get((a, b), 0))
        c_ab = ct.get((a, best_b), 0)
        cond_p = c_ab / ca
        base_p = rb[best_b] / total
        if base_p < 1.0 - 1e-12:
            gain_best_raw = (cond_p - base_p) / (1.0 - base_p)
            cand_raw = ContainmentBest(
                direction="A->X",
                source_loop=a,
                target_loop=best_b,
                cell_count=c_ab,
                source_total=ca,
                cond_prob=cond_p,
                baseline_prob=base_p,
                containment_gain=gain_best_raw,
            )
            best_gb = None
            for b, cb in rb.items():
                bp = cb / total
                if bp >= 1.0 - 1e-12:
                    continue
                cab = ct.get((a, b), 0)
                cp = cab / ca
                g = (cp - bp) / (1.0 - bp)
                cand_g = ContainmentBest(
                    direction="A->X",
                    source_loop=a,
                    target_loop=b,
                    cell_count=cab,
                    source_total=ca,
                    cond_prob=cp,
                    baseline_prob=bp,
                    containment_gain=g,
                )
                if best_gb is None or (g, cp) > (best_gb.containment_gain, best_gb.cond_prob):
                    best_gb = cand_g
            if best_gb is not None:
                _update(cand_raw, best_gb)

    return (
        rel["exact_equalities"],
        rel["exact_strict_inclusions"],
        rel["exact_containments"],
        best_raw,
        best_gain,
        rel["exact_equal_pairs"],
        rel["exact_inclusion_pairs"],
    )


def compute_pair_metrics(
    ct: dict[tuple[int, int], int],
    min_basin_abs: int = 50,
    min_basin_frac: float = 0.002,
) -> PairMetrics | None:
    """Compute chi-square, Cramer's V, NMI, exact equality/inclusion, and near-containment metrics."""
    ra, rb, total = _marginals(ct)
    if len(ra) < 2 or len(rb) < 2 or total == 0:
        return None

    chi2 = 0.0
    mi_bits = 0.0
    max_abs_std_resid = 0.0
    sig_zeros = 0

    for a, ca in ra.items():
        pa = ca / total
        for b, cb in rb.items():
            obs = ct.get((a, b), 0)
            exp = ca * cb / total
            diff = obs - exp
            chi2 += (diff * diff) / exp
            resid = abs(diff) / math.sqrt(exp)
            if resid > max_abs_std_resid:
                max_abs_std_resid = resid
            if obs == 0:
                if exp >= 10.0:
                    sig_zeros += 1
            else:
                pab = obs / total
                pb = cb / total
                mi_bits += pab * math.log2(pab / (pa * pb))

    ha = -sum((ca / total) * math.log2(ca / total) for ca in ra.values())
    hb = -sum((cb / total) * math.log2(cb / total) for cb in rb.values())
    nmi = mi_bits / math.sqrt(ha * hb) if ha > 0.0 and hb > 0.0 else 0.0

    k_min = min(len(ra), len(rb))
    cramers_v = math.sqrt(chi2 / (total * (k_min - 1)))
    df = (len(ra) - 1) * (len(rb) - 1)
    p_value = chi2_sf(chi2, df)

    min_count = max(min_basin_abs, int(min_basin_frac * total))
    (
        exact_eq,
        exact_inc,
        exact_cont,
        best_raw,
        best_gain,
        eq_pairs,
        inc_pairs,
    ) = _evaluate_containment(ct, ra, rb, total, min_count)

    return PairMetrics(
        total=total,
        n_loops_a=len(ra),
        n_loops_b=len(rb),
        df=df,
        chi2=chi2,
        p_value=p_value,
        cramers_v=cramers_v,
        mi_bits=mi_bits,
        nmi=nmi,
        max_abs_std_resid=max_abs_std_resid,
        exact_equalities=exact_eq,
        exact_strict_inclusions=exact_inc,
        exact_containments=exact_cont,
        significant_zero_cells=sig_zeros,
        best_raw_purity=best_raw,
        best_gain=best_gain,
        exact_equal_pairs=eq_pairs,
        exact_inclusion_pairs=inc_pairs,
    )


def _join_subgroup_coset_map(p_a: int, p_b: int, m: int) -> tuple[str, int, dict[int, int]]:
    """Compute the join subgroup <H_{p_a}(m), H_{p_b}(m)> in (Z/mZ)* and its coset map."""
    cs_a = multiplicative_subgroup_cosets(p_a, m)
    if p_a == p_b:
        return "equal", cs_a.index, cs_a.residue_to_coset

    cs_b = multiplicative_subgroup_cosets(p_b, m)
    ha = cs_a.subgroup
    hb = cs_b.subgroup
    if ha == hb:
        return "equal", cs_a.index, cs_a.residue_to_coset
    if ha.issubset(hb):
        return "A_sub_B", cs_b.index, cs_b.residue_to_coset
    if hb.issubset(ha):
        return "B_sub_A", cs_a.index, cs_a.residue_to_coset

    gens = tuple(ha | hb)
    sub = {1}
    frontier = [1]
    while frontier:
        cur = frontier.pop()
        for g in gens:
            nxt = (cur * g) % m
            if nxt not in sub:
                sub.add(nxt)
                frontier.append(nxt)

    units = [x for x in range(1, m) if math.gcd(x, m) == 1]
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
    return "different", len(cosets), rmap


def check_coset_leakage(
    ct: dict[tuple[int, int], int],
    p_a: int,
    p_b: int,
    m: int,
    shift_c: int | None = None,
) -> dict[str, Any]:
    """Verify zero cross-world / cross-coset leakage on a contingency table.

    - If shift_c is None: checks multiplicative invariant mod m under the join
      subgroup <H_{p_a}(m), H_{p_b}(m)>.
    - If shift_c is not None: checks shifted-congruence invariant on u = n + shift_c (mod m).
    """
    if shift_c is None:
        rel, join_idx, rmap = _join_subgroup_coset_map(p_a, p_b, m)
        total = 0
        primitive_total = 0
        stratum_leakage = 0
        coset_leakage = 0
        for (a, b), cnt in ct.items():
            if cnt <= 0 or a <= 0 or b <= 0:
                continue
            total += cnt
            pa_prim = math.gcd(a, m) == 1
            pb_prim = math.gcd(b, m) == 1
            if pa_prim != pb_prim:
                stratum_leakage += cnt
            elif pa_prim and pb_prim:
                primitive_total += cnt
                if rmap[a % m] != rmap[b % m]:
                    coset_leakage += cnt
        return {
            "mode": "multiplicative",
            "m": m,
            "subgroup_relation": rel,
            "join_index": join_idx,
            "total_evaluated": total,
            "primitive_total": primitive_total,
            "stratum_leakage_count": stratum_leakage,
            "coset_leakage_count": coset_leakage,
            "leakage_count": stratum_leakage + coset_leakage,
        }

    idx2, rmap2 = shifted_coset_map(m)
    total = 0
    fixed_total = 0
    fixed_leakage = 0
    stratum_leakage = 0
    coset_leakage = 0
    for (a, b), cnt in ct.items():
        if cnt <= 0 or a <= 0 or b <= 0:
            continue
        total += cnt
        ua = (a + shift_c) % m
        ub = (b + shift_c) % m
        ga = math.gcd(ua, m)
        gb = math.gcd(ub, m)
        if ua == 0 and ub == 0:
            fixed_total += cnt
        elif (ua == 0) != (ub == 0):
            fixed_leakage += cnt
            stratum_leakage += cnt
        elif ga != gb:
            stratum_leakage += cnt
        elif ga == 1 and idx2 >= 2:
            if rmap2[ua] != rmap2[ub]:
                coset_leakage += cnt
    return {
        "mode": "shifted",
        "m": m,
        "shift_c": shift_c,
        "idx2": idx2,
        "total_evaluated": total,
        "fixed_total": fixed_total,
        "fixed_leakage_count": fixed_leakage,
        "stratum_leakage_count": stratum_leakage,
        "coset_leakage_count": coset_leakage,
        "leakage_count": stratum_leakage + coset_leakage,
    }

