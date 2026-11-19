"""Orchestration CLI for generalized (p >= 4, Q) CTree pairing study."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .algebra import (
    SystemRecord,
    SystemSpec,
    find_shifted_congruences,
    load_p4_grid80,
    load_sqlite_summary,
    make_minimal_q_for_m,
    multiplicative_subgroup_cosets,
    p_free_core,
    primitive_family_key,
    shifted_coset_map,
)
from .metrics import (
    build_contingency,
    check_coset_leakage,
    compute_pair_metrics,
    summarize_exact_relations,
)
from .solver import SolverResult, compute_systems_parallel
from .visualize import generate_all_charts

OUT_DIR = Path("outputs/pairing_p4plus")


@dataclass(frozen=True)
class PairCandidate:
    """Pair of systems to evaluate at trajectory level."""

    category: str
    subcategory: str
    spec_a: SystemSpec
    spec_b: SystemSpec
    invariant_mode: str  # "multiplicative" | "shifted" | "none"
    modulus: int
    shift_c: int | None
    relation: str
    is_pure_jacobi: bool


def _classify_p_relation(spec_a: SystemSpec, spec_b: SystemSpec) -> str:
    if spec_a.p != spec_b.p:
        return "cross_p"
    p = spec_a.p
    if spec_a.scale(p) == spec_b or spec_b.scale(p) == spec_a:
        return "p_sibling"
    if p == 4 and (spec_a.scale(2) == spec_b or spec_b.scale(2) == spec_a):
        return "scale_flip_2x"
    _, base_a = primitive_family_key(p, spec_a.q_tuple)
    _, base_b = primitive_family_key(p, spec_b.q_tuple)
    if base_a == base_b:
        return "same_family_other_scale"
    return "cross_family_same_mod"


def _coset_loop_summary(
    rec: SystemRecord, m: int
) -> tuple[int, list[int], list[float], list[tuple[int, int] | None]]:
    """Classify loops of rec into non-primitive and cosets mod m."""
    cs = multiplicative_subgroup_cosets(rec.spec.p, m)
    non_prim = 0
    counts = [0] * cs.index
    shares = [0.0] * cs.index
    loops_per_coset: list[list[tuple[int, int]]] = [[] for _ in range(cs.index)]
    for lp in rec.loops:
        if math.gcd(lp.min_value, m) != 1:
            non_prim += 1
        else:
            cid = cs.residue_to_coset[lp.min_value % m]
            counts[cid] += 1
            shares[cid] += lp.basin_share
            loops_per_coset[cid].append((lp.min_value, lp.length))
    single_info = [lst[0] if len(lst) == 1 else None for lst in loops_per_coset]
    return non_prim, counts, shares, single_info


def _shifted_loop_summary(rec: SystemRecord, m: int, c: int, idx2: int) -> dict[str, Any]:
    """Classify loops of rec under shifted congruence u = n + c (mod m)."""
    _, rmap2 = shifted_coset_map(m)
    fixed_loops: list[tuple[int, int]] = []
    fixed_share = 0.0
    non_fixed_loops: list[tuple[int, int]] = []
    non_fixed_share = 0.0
    coset_counts = [0] * idx2
    for lp in rec.loops:
        u = (lp.min_value + c) % m
        if u == 0:
            fixed_loops.append((lp.min_value, lp.length))
            fixed_share += lp.basin_share
        else:
            non_fixed_loops.append((lp.min_value, lp.length))
            non_fixed_share += lp.basin_share
            if math.gcd(u, m) == 1:
                coset_counts[rmap2[u]] += 1
    return {
        "fixed_count": len(fixed_loops),
        "fixed_share": fixed_share,
        "fixed_single": fixed_loops[0] if len(fixed_loops) == 1 else None,
        "non_fixed_count": len(non_fixed_loops),
        "non_fixed_share": non_fixed_share,
        "non_fixed_single": non_fixed_loops[0] if len(non_fixed_loops) == 1 else None,
        "prim_coset_counts": coset_counts,
    }


def _load_all_existing_records(base_dir: Path = Path(".")) -> dict[int, list[SystemRecord]]:
    records_by_p: dict[int, list[SystemRecord]] = {}
    records_by_p[3] = load_sqlite_summary(3, base_dir=base_dir, q1_max=200)
    records_by_p[4] = load_p4_grid80(base_dir=base_dir)
    for p in (5, 6, 7, 8, 9):
        records_by_p[p] = load_sqlite_summary(p, base_dir=base_dir)
    return records_by_p


def run_phase1(base_dir: Path = Path("."), out_dir: Path = OUT_DIR) -> dict[str, Any]:
    """Phase 1: Exhaustive algebraic screening of existing datasets (p = 3..9)."""
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    records_by_p = _load_all_existing_records(base_dir)

    coset_rows: list[dict[str, Any]] = []
    coset_records_by_pm: dict[tuple[int, int], list[SystemRecord]] = defaultdict(list)
    exact_core_records_by_pm: dict[tuple[int, int], list[SystemRecord]] = defaultdict(list)

    shifted_rows: list[dict[str, Any]] = []
    shifted_records_by_pmc: dict[tuple[int, int, int], list[SystemRecord]] = defaultdict(list)

    for p, recs in sorted(records_by_p.items()):
        for rec in recs:
            g_core = rec.spec.g_core
            if g_core > 1:
                cs_core = multiplicative_subgroup_cosets(p, g_core)
                if cs_core.index >= 2:
                    fam_g, fam_base = primitive_family_key(p, rec.spec.q_tuple)
                    non_prim, c_counts, c_shares, c_single = _coset_loop_summary(rec, g_core)
                    coset_rows.append(
                        {
                            "p": p,
                            "q_tuple": json.dumps(list(rec.spec.q_tuple)),
                            "gcd_q": rec.spec.gcd_q,
                            "g_core": g_core,
                            "family_g": fam_g,
                            "family_base": json.dumps(list(fam_base)),
                            "index": cs_core.index,
                            "is_pure_composite_coupling": int(cs_core.is_pure_composite_coupling),
                            "num_loops": rec.num_loops,
                            "non_prim_loops": non_prim,
                            "per_coset_loop_counts": json.dumps(c_counts),
                            "per_coset_shares": json.dumps([round(x, 6) for x in c_shares]),
                            "per_coset_single_min_len": json.dumps(
                                [list(x) if x is not None else None for x in c_single]
                            ),
                            "has_single_coset_loop": int(any(x is not None for x in c_single)),
                            "source": rec.source,
                        }
                    )
                    exact_core_records_by_pm[(p, g_core)].append(rec)

                # Also register under divisors m > 1 of g_core with index >= 2 (for cross-p and divisor matching)
                for m in range(2, g_core + 1):
                    if g_core % m == 0 and multiplicative_subgroup_cosets(p, m).index >= 2:
                        coset_records_by_pm[(p, m)].append(rec)

            if p >= 4:
                for m, c, idx2 in find_shifted_congruences(p, rec.spec.q_tuple):
                    sh = _shifted_loop_summary(rec, m, c, idx2)
                    shifted_rows.append(
                        {
                            "p": p,
                            "q_tuple": json.dumps(list(rec.spec.q_tuple)),
                            "gcd_q": rec.spec.gcd_q,
                            "m": m,
                            "shift_c": c,
                            "idx2": idx2,
                            "num_loops": rec.num_loops,
                            "fixed_loops": sh["fixed_count"],
                            "fixed_share": round(sh["fixed_share"], 6),
                            "non_fixed_loops": sh["non_fixed_count"],
                            "non_fixed_share": round(sh["non_fixed_share"], 6),
                            "single_fixed_loop": json.dumps(
                                list(sh["fixed_single"]) if sh["fixed_single"] else None
                            ),
                            "single_non_fixed_loop": json.dumps(
                                list(sh["non_fixed_single"]) if sh["non_fixed_single"] else None
                            ),
                            "prim_coset_counts": json.dumps(sh["prim_coset_counts"]),
                            "source": rec.source,
                        }
                    )
                    shifted_records_by_pmc[(p, m, c)].append(rec)

    coset_csv = out_dir / "phase1_coset_systems.csv"
    with coset_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "p",
            "q_tuple",
            "gcd_q",
            "g_core",
            "family_g",
            "family_base",
            "index",
            "is_pure_composite_coupling",
            "num_loops",
            "non_prim_loops",
            "per_coset_loop_counts",
            "per_coset_shares",
            "per_coset_single_min_len",
            "has_single_coset_loop",
            "source",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(coset_rows)

    shifted_csv = out_dir / "phase1_shifted_systems.csv"
    with shifted_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "p",
            "q_tuple",
            "gcd_q",
            "m",
            "shift_c",
            "idx2",
            "num_loops",
            "fixed_loops",
            "fixed_share",
            "non_fixed_loops",
            "non_fixed_share",
            "single_fixed_loop",
            "single_non_fixed_loop",
            "prim_coset_counts",
            "source",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(shifted_rows)

    # Build predicted pairs catalog
    predicted_rows: list[dict[str, Any]] = []

    def _predict_coset_pair(
        rec_a: SystemRecord,
        rec_b: SystemRecord,
        m: int,
        cat: str,
        rel_override: str | None = None,
    ) -> dict[str, Any]:
        p_a, p_b = rec_a.spec.p, rec_b.spec.p
        cs_a = multiplicative_subgroup_cosets(p_a, m)
        cs_b = multiplicative_subgroup_cosets(p_b, m)
        assert cs_a.subgroup == cs_b.subgroup
        _, ca, _, sa = _coset_loop_summary(rec_a, m)
        _, cb, _, sb = _coset_loop_summary(rec_b, m)
        same_g_core = rec_a.spec.g_core == rec_b.spec.g_core == m
        pred_eq = 0
        pred_inc = 0
        diff_len_eq = 0
        for cid in range(cs_a.index):
            na, nb = ca[cid], cb[cid]
            if na == 1 and nb == 1:
                pred_eq += 1
                if sa[cid] is not None and sb[cid] is not None and sa[cid][1] != sb[cid][1]:
                    diff_len_eq += 1
            elif (na == 1 and nb >= 2) or (nb == 1 and na >= 2):
                pred_inc += 1
        rel = rel_override or _classify_p_relation(rec_a.spec, rec_b.spec)
        return {
            "category": cat,
            "invariant_mode": "multiplicative",
            "p_a": p_a,
            "q_a": json.dumps(list(rec_a.spec.q_tuple)),
            "g_core_a": rec_a.spec.g_core,
            "p_b": p_b,
            "q_b": json.dumps(list(rec_b.spec.q_tuple)),
            "g_core_b": rec_b.spec.g_core,
            "modulus": m,
            "shift_c": "",
            "index": cs_a.index,
            "is_pure_jacobi": int(cs_a.is_pure_composite_coupling),
            "relation": rel,
            "same_g_core": int(same_g_core),
            "pred_prim_exact_equalities": pred_eq,
            "pred_prim_strict_inclusions": pred_inc,
            "pred_diff_len_equalities": diff_len_eq,
            "coset_counts_a": json.dumps(ca),
            "coset_counts_b": json.dumps(cb),
        }

    # (1) Same-p multiplicative cosets (p >= 4), exact core matches + shared-divisor extra matches
    seen_same_p: set[tuple[SystemSpec, SystemSpec, int]] = set()
    for (p, m), recs in sorted(exact_core_records_by_pm.items()):
        if p < 4 or len(recs) < 2:
            continue
        recs_sorted = sorted(recs, key=lambda r: r.spec.q_tuple)
        for i in range(len(recs_sorted)):
            for j in range(i + 1, len(recs_sorted)):
                ra, rb = recs_sorted[i], recs_sorted[j]
                key = (ra.spec, rb.spec, m)
                seen_same_p.add(key)
                predicted_rows.append(_predict_coset_pair(ra, rb, m, "same_p_coset"))

    # Add shared-divisor pairs where g_core_A == m and g_core_B > m is a multiple of m
    for (p, m), recs in sorted(coset_records_by_pm.items()):
        if p < 4:
            continue
        exact_m = [r for r in recs if r.spec.g_core == m]
        larger_m = [r for r in recs if r.spec.g_core > m]
        if not exact_m or not larger_m:
            continue
        for ra in sorted(exact_m, key=lambda r: r.spec.q_tuple)[:15]:
            for rb in sorted(larger_m, key=lambda r: r.spec.q_tuple):
                s1, s2 = (ra, rb) if ra.spec.q_tuple <= rb.spec.q_tuple else (rb, ra)
                key = (s1.spec, s2.spec, m)
                if key not in seen_same_p:
                    seen_same_p.add(key)
                    predicted_rows.append(
                        _predict_coset_pair(s1, s2, m, "same_p_shared_coset_divisor")
                    )

    # (2) Cross-p multiplicative cosets: p=3 vs p=4, and p=4 vs p=5
    for p_a, p_b in ((3, 4), (4, 5)):
        shared_ms = sorted(
            {m for (p, m) in coset_records_by_pm if p == p_a}
            & {m for (p, m) in coset_records_by_pm if p == p_b}
        )
        for m in shared_ms:
            cs_a = multiplicative_subgroup_cosets(p_a, m)
            cs_b = multiplicative_subgroup_cosets(p_b, m)
            if cs_a.subgroup != cs_b.subgroup:
                continue
            recs_a = sorted(coset_records_by_pm[(p_a, m)], key=lambda r: r.spec.q_tuple)
            recs_b = sorted(coset_records_by_pm[(p_b, m)], key=lambda r: r.spec.q_tuple)
            for ra in recs_a:
                for rb in recs_b:
                    predicted_rows.append(
                        _predict_coset_pair(ra, rb, m, f"cross_p_{p_a}_vs_{p_b}")
                    )

    # (3) Same-p shifted congruence pairs (gcd(Q) == 1), sample top representatives per (p, m, c)
    shifted_group_summary: list[dict[str, Any]] = []
    for (p, m, c), recs in sorted(shifted_records_by_pmc.items()):
        gcd1_recs = [r for r in recs if r.spec.gcd_q == 1]
        if not gcd1_recs:
            continue
        idx2, _ = shifted_coset_map(m)
        single_fixed = []
        single_non_fixed = []
        both_single = []
        for r in gcd1_recs:
            sh = _shifted_loop_summary(r, m, c, idx2)
            sf = sh["fixed_count"] == 1
            sn = sh["non_fixed_count"] == 1
            if sf:
                single_fixed.append(r)
            if sn:
                single_non_fixed.append(r)
            if sf and sn:
                both_single.append(r)
        shifted_group_summary.append(
            {
                "p": p,
                "m": m,
                "shift_c": c,
                "idx2": idx2,
                "total_gcd1_systems": len(gcd1_recs),
                "single_fixed_systems": len(single_fixed),
                "single_non_fixed_systems": len(single_non_fixed),
                "both_single_systems": len(both_single),
            }
        )
        # Emit representative predicted pairs (up to 12 selected systems -> <= 66 pairs per group)
        rep_map = {
            r.spec: r
            for r in (
                sorted(both_single, key=lambda r: r.spec.q_tuple)[:6]
                + sorted(single_fixed, key=lambda r: r.spec.q_tuple)[:4]
                + sorted(gcd1_recs, key=lambda r: (r.num_loops, r.spec.q_tuple))[:4]
            )
        }
        rep_pool = list(rep_map.values())[:12]
        for i in range(len(rep_pool)):
            for j in range(i + 1, len(rep_pool)):
                ra, rb = rep_pool[i], rep_pool[j]
                sha = _shifted_loop_summary(ra, m, c, idx2)
                shb = _shifted_loop_summary(rb, m, c, idx2)
                pred_eq = int(sha["fixed_count"] == 1 and shb["fixed_count"] == 1) + int(
                    sha["non_fixed_count"] == 1 and shb["non_fixed_count"] == 1
                )
                pred_inc = int(
                    (sha["fixed_count"] == 1 and shb["fixed_count"] >= 2)
                    or (shb["fixed_count"] == 1 and sha["fixed_count"] >= 2)
                ) + int(
                    (sha["non_fixed_count"] == 1 and shb["non_fixed_count"] >= 2)
                    or (shb["non_fixed_count"] == 1 and sha["non_fixed_count"] >= 2)
                )
                diff_len = int(
                    sha["fixed_single"] is not None
                    and shb["fixed_single"] is not None
                    and sha["fixed_single"][1] != shb["fixed_single"][1]
                ) + int(
                    sha["non_fixed_single"] is not None
                    and shb["non_fixed_single"] is not None
                    and sha["non_fixed_single"][1] != shb["non_fixed_single"][1]
                )
                predicted_rows.append(
                    {
                        "category": "same_p_shifted_gcd1",
                        "invariant_mode": "shifted",
                        "p_a": p,
                        "q_a": json.dumps(list(ra.spec.q_tuple)),
                        "g_core_a": ra.spec.g_core,
                        "p_b": p,
                        "q_b": json.dumps(list(rb.spec.q_tuple)),
                        "g_core_b": rb.spec.g_core,
                        "modulus": m,
                        "shift_c": c,
                        "index": 1 + idx2,
                        "is_pure_jacobi": 0,
                        "relation": f"shifted_mod{m}_c{c}",
                        "same_g_core": 1,
                        "pred_prim_exact_equalities": pred_eq,
                        "pred_prim_strict_inclusions": pred_inc,
                        "pred_diff_len_equalities": diff_len,
                        "coset_counts_a": json.dumps([sha["fixed_count"], sha["non_fixed_count"]]),
                        "coset_counts_b": json.dumps([shb["fixed_count"], shb["non_fixed_count"]]),
                    }
                )

    pred_csv = out_dir / "phase1_predicted_pairs.csv"
    with pred_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "category",
            "invariant_mode",
            "p_a",
            "q_a",
            "g_core_a",
            "p_b",
            "q_b",
            "g_core_b",
            "modulus",
            "shift_c",
            "index",
            "is_pure_jacobi",
            "relation",
            "same_g_core",
            "pred_prim_exact_equalities",
            "pred_prim_strict_inclusions",
            "pred_diff_len_equalities",
            "coset_counts_a",
            "coset_counts_b",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(predicted_rows)

    # Aggregate summary JSON
    by_p_coset = defaultdict(int)
    by_p_cores = defaultdict(set)
    for row in coset_rows:
        by_p_coset[row["p"]] += 1
        by_p_cores[row["p"]].add(row["g_core"])

    by_cat_pred: dict[str, dict[str, int]] = defaultdict(
        lambda: {"pairs": 0, "with_eq": 0, "with_diff_len_eq": 0, "with_inc": 0}
    )
    for row in predicted_rows:
        d = by_cat_pred[row["category"]]
        d["pairs"] += 1
        if row["pred_prim_exact_equalities"] > 0:
            d["with_eq"] += 1
        if row["pred_diff_len_equalities"] > 0:
            d["with_diff_len_eq"] += 1
        if row["pred_prim_strict_inclusions"] > 0:
            d["with_inc"] += 1

    summary = {
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "dataset_counts": {p: len(recs) for p, recs in sorted(records_by_p.items())},
        "coset_systems_p4plus": {
            str(p): {
                "count": by_p_coset[p],
                "unique_g_cores": sorted(by_p_cores[p]),
            }
            for p in sorted(by_p_coset)
            if p >= 4
        },
        "coset_systems_p3_ref_count": by_p_coset[3],
        "shifted_gcd1_groups": shifted_group_summary,
        "predicted_pairs_by_category": dict(by_cat_pred),
        "total_predicted_pairs": len(predicted_rows),
    }
    summary_json = out_dir / "phase1_summary.json"
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def _build_phase2_candidates(base_dir: Path = Path(".")) -> list[PairCandidate]:
    """Assemble curated Phase 2 verification pairs across Cat A, B, C, D."""
    records_by_p = _load_all_existing_records(base_dir)
    p4_map: dict[tuple[int, ...], SystemRecord] = {
        r.spec.q_tuple: r for r in records_by_p[4]
    }
    p5_map: dict[tuple[int, ...], SystemRecord] = {
        r.spec.q_tuple: r for r in records_by_p[5]
    }
    p3_map: dict[tuple[int, ...], SystemRecord] = {
        r.spec.q_tuple: r for r in records_by_p[3]
    }

    candidates: list[PairCandidate] = []
    seen_pairs: set[tuple[str, SystemSpec, SystemSpec]] = set()

    def _add(
        cat: str,
        subcat: str,
        sa: SystemSpec,
        sb: SystemSpec,
        mode: str,
        modulus: int,
        shift_c: int | None = None,
        rel_override: str | None = None,
    ) -> None:
        if sa == sb:
            return
        if sa.p > sb.p or (sa.p == sb.p and sa.q_tuple > sb.q_tuple):
            sa, sb = sb, sa
        key = (cat, sa, sb)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        rel = rel_override or _classify_p_relation(sa, sb)
        is_jacobi = False
        if mode == "multiplicative" and modulus >= 2:
            is_jacobi = multiplicative_subgroup_cosets(sa.p, modulus).is_pure_composite_coupling
        candidates.append(
            PairCandidate(
                category=cat,
                subcategory=subcat,
                spec_a=sa,
                spec_b=sb,
                invariant_mode=mode,
                modulus=modulus,
                shift_c=shift_c,
                relation=rel,
                is_pure_jacobi=is_jacobi,
            )
        )

    # --- Cat A: Same-p scaling (coset p-siblings, 2x flips, and non-coset p-siblings) ---
    p4_coset_recs = [
        r
        for r in records_by_p[4]
        if r.spec.g_core > 1 and multiplicative_subgroup_cosets(4, r.spec.g_core).index >= 2
    ]
    # 1) p=4 coset 4*Q siblings inside 80x80
    p4_sibs = []
    for r in sorted(p4_coset_recs, key=lambda x: (x.spec.g_core, x.spec.q_tuple)):
        sib = r.spec.scale(4)
        if sib.q_tuple in p4_map:
            p4_sibs.append((r.spec, sib))
    for sa, sb in p4_sibs[:14]:
        _add("CatA_scaling", "p4_coset_p_sibling", sa, sb, "multiplicative", sa.g_core)

    # 2) p=4 coset 2*Q flip pairs inside 80x80
    p4_flips = []
    for r in sorted(p4_coset_recs, key=lambda x: (x.spec.g_core, x.spec.q_tuple)):
        flp = r.spec.scale(2)
        if flp.q_tuple in p4_map:
            p4_flips.append((r.spec, flp))
    for sa, sb in p4_flips[:12]:
        _add("CatA_scaling", "p4_coset_2x_flip", sa, sb, "multiplicative", sa.g_core)

    # 3) Non-coset (I_p(g') == 1) p-siblings in p=4 and p=5
    for q_tuple in [(2, 1), (5, 1), (7, 4), (11, 1), (14, 1), (5, 4)]:
        if q_tuple in p4_map:
            sa = p4_map[q_tuple].spec
            sb = sa.scale(4)
            if sb.q_tuple in p4_map:
                _add(
                    "CatA_scaling",
                    "p4_non_coset_p_sibling",
                    sa,
                    sb,
                    "none",
                    sa.g_core,
                )
    for q_tuple in [(3, 2, 1), (3, 2, 5), (3, 2, 13), (7, 2, 1)]:
        if q_tuple in p5_map:
            sa = p5_map[q_tuple].spec
            sb = sa.scale(5)
            if sb.q_tuple in p5_map:
                _add(
                    "CatA_scaling",
                    "p5_non_coset_p_sibling",
                    sa,
                    sb,
                    "none",
                    sa.g_core,
                )

    # --- Cat B: Same-p cross-family and pure Jacobi walls ---
    for target_m, limit_n, subcat in [
        (13, None, "p4_g13_all34"),
        (37, None, "p4_g37_all4"),
        (47, None, "p4_g47_all4"),
        (35, None, "p4_g35_jacobi_all4"),
        (23, None, "p4_g23_all11"),
        (11, 12, "p4_g11_rep12"),
    ]:
        pool = sorted(
            [r.spec for r in records_by_p[4] if r.spec.g_core == target_m],
            key=lambda s: s.q_tuple,
        )
        if limit_n is not None and len(pool) > limit_n:
            # Always keep (209, 88) for g'=11 (single QNR loop) + evenly spaced representatives
            must = [s for s in pool if s.q_tuple == (209, 88)]
            rest = [s for s in pool if s.q_tuple != (209, 88)]
            step = max(1, len(rest) // (limit_n - len(must)))
            pool = must + rest[::step]
            pool = pool[:limit_n]
        for i in range(len(pool)):
            for j in range(i + 1, len(pool)):
                _add("CatB_cross_family", subcat, pool[i], pool[j], "multiplicative", target_m)

    # Larger pure Jacobi walls in p=4 (g'=85, 95, 119) paired with their 4*Q siblings
    for target_m in (85, 95, 119):
        pool = sorted(
            [r.spec for r in records_by_p[4] if r.spec.g_core == target_m],
            key=lambda s: s.q_tuple,
        )
        if pool:
            sa = pool[0]
            sb = sa.scale(4)
            _add("CatB_cross_family", f"p4_g{target_m}_jacobi_sibling", sa, sb, "multiplicative", target_m)

    # p=5 gcd=11 (all 8 systems)
    p5_g11 = sorted([r.spec for r in records_by_p[5] if r.spec.g_core == 11], key=lambda s: s.q_tuple)
    for i in range(len(p5_g11)):
        for j in range(i + 1, len(p5_g11)):
            _add("CatB_cross_family", "p5_g11_all8", p5_g11[i], p5_g11[j], "multiplicative", 11)

    # p=5 gcd=19 and gcd=21 (1 system in DB -> pair with valid 5*Q sibling + valid same-gcd neighbor)
    p5_19_base = SystemSpec(5, (19, 38, 57))
    p5_19_sib = p5_19_base.scale(5)
    p5_19_alt = SystemSpec(5, (19, 38, 133))
    for sa, sb in [(p5_19_base, p5_19_sib), (p5_19_base, p5_19_alt), (p5_19_sib, p5_19_alt)]:
        assert sa.is_valid() and sb.is_valid()
        _add("CatB_cross_family", "p5_g19_extended", sa, sb, "multiplicative", 19)

    p5_21_base = SystemSpec(5, (63, 42, 21))
    p5_21_sib = p5_21_base.scale(5)
    p5_21_alt = SystemSpec(5, (63, 42, 105))
    for sa, sb in [(p5_21_base, p5_21_sib), (p5_21_base, p5_21_alt), (p5_21_sib, p5_21_alt)]:
        assert sa.is_valid() and sb.is_valid()
        _add("CatB_cross_family", "p5_g21_jacobi_extended", sa, sb, "multiplicative", 21)

    # --- Cat C: Cross-p shared subgroup ---
    # p=4 (g'=11 rep12) vs p=5 (gcd=11 all 8)
    p4_g11_rep = sorted(
        list({s for cand in candidates if cand.subcategory == "p4_g11_rep12" for s in (cand.spec_a, cand.spec_b)}),
        key=lambda s: s.q_tuple,
    )
    for sa in p4_g11_rep:
        for sb in p5_g11:
            _add("CatC_cross_p", "p4_vs_p5_mod11", sa, sb, "multiplicative", 11, rel_override="cross_p_4_5")

    # p=3 vs p=4 at m=23 and m=47
    for m, p3_qs in ((23, [(23,), (69,)]), (47, [(47,), (141,)])):
        p4_m_pool = sorted(
            [r.spec for r in records_by_p[4] if r.spec.g_core == m],
            key=lambda s: s.q_tuple,
        )
        for q3 in p3_qs:
            sa = p3_map[q3].spec if q3 in p3_map else SystemSpec(3, q3)
            for sb in p4_m_pool:
                _add(
                    "CatC_cross_p",
                    f"p3_vs_p4_mod{m}",
                    sa,
                    sb,
                    "multiplicative",
                    m,
                    rel_override="cross_p_3_4",
                )

    # --- Cat D1: Shifted congruence (gcd == 1) ---
    # p=5 (m=3, c=1): pick 10 systems favoring single-fixed-loop systems + multi-loop diversity
    p5_sh_pool = []
    for r in sorted(records_by_p[5], key=lambda x: (x.num_loops, x.spec.q_tuple)):
        if r.spec.gcd_q != 1:
            continue
        shifts = find_shifted_congruences(5, r.spec.q_tuple)
        if (3, 1, 1) in shifts and r.num_loops >= 2:
            sh = _shifted_loop_summary(r, 3, 1, 1)
            p5_sh_pool.append((0 if sh["fixed_count"] == 1 else 1, 0 if sh["non_fixed_count"] == 1 else 1, r.spec))
    p5_sh_pool.sort(key=lambda x: (x[0], x[1], x[2].q_tuple))
    p5_sh_selected = [x[2] for x in p5_sh_pool[:10]]
    for i in range(len(p5_sh_selected)):
        for j in range(i + 1, len(p5_sh_selected)):
            _add("CatD_shifted_and_ctrl", "p5_shifted_mod3_c1", p5_sh_selected[i], p5_sh_selected[j], "shifted", 3, shift_c=1)

    # p=7 (m=5) and p=8 (m=3): group by (p, m, c) with gcd==1 and >=2 loops
    for p_val, m_val in ((7, 5), (8, 3)):
        by_c: dict[int, list[SystemSpec]] = defaultdict(list)
        for r in sorted(records_by_p[p_val], key=lambda x: (x.num_loops, x.spec.q_tuple)):
            if r.spec.gcd_q != 1 or r.num_loops < 2:
                continue
            for mm, cc, _ in find_shifted_congruences(p_val, r.spec.q_tuple):
                if mm == m_val:
                    by_c[cc].append(r.spec)
        # Pick the c with most multi-loop systems
        if by_c:
            best_c = max(by_c.keys(), key=lambda cc: (len(by_c[cc]), -cc))
            sel = by_c[best_c][:6]
            for i in range(len(sel)):
                for j in range(i + 1, len(sel)):
                    _add(
                        "CatD_shifted_and_ctrl",
                        f"p{p_val}_shifted_mod{m_val}_c{best_c}",
                        sel[i],
                        sel[j],
                        "shifted",
                        m_val,
                        shift_c=best_c,
                    )

    # --- Cat D2: Unstructured coprime controls (gcd == 1, no shifted congruence, num_loops >= 2) ---
    p4_ctrl = [
        r.spec
        for r in sorted(records_by_p[4], key=lambda x: x.spec.q_tuple)
        if r.spec.gcd_q == 1
        and r.num_loops >= 2
        and r.spec.q_tuple[0] <= 89
        and r.spec.q_tuple[1] <= 88
        and min(lp.basin_share for lp in r.loops) >= 0.03
    ][:15]
    for i in range(len(p4_ctrl)):
        for j in range(i + 1, len(p4_ctrl)):
            _add("CatD_shifted_and_ctrl", "p4_coprime_ctrl", p4_ctrl[i], p4_ctrl[j], "none", 1)

    p5_ctrl = [
        r.spec
        for r in sorted(records_by_p[5], key=lambda x: x.spec.q_tuple)
        if r.spec.gcd_q == 1
        and not find_shifted_congruences(5, r.spec.q_tuple)
        and r.num_loops >= 2
        and min(lp.basin_share for lp in r.loops) >= 0.03
    ][:10]
    for i in range(len(p5_ctrl)):
        for j in range(i + 1, len(p5_ctrl)):
            _add("CatD_shifted_and_ctrl", "p5_coprime_ctrl", p5_ctrl[i], p5_ctrl[j], "none", 1)

    return candidates


def _make_prim_mask(cand: PairCandidate, n_max: int) -> np.ndarray:
    """Boolean mask of length n_max selecting d_A, d_B-free and core-coprime integers."""
    ns = np.arange(1, n_max + 1, dtype=np.int64)
    da = cand.spec_a.d
    db = cand.spec_b.d
    mask = (ns % da) != 0
    if db != da:
        mask &= (ns % db) != 0
    g_ab = cand.spec_a.g_core * cand.spec_b.g_core
    if g_ab > 1:
        # Factor g_ab into distinct primes for vectorized filtering
        rem = g_ab
        f = 2
        while f * f <= rem:
            if rem % f == 0:
                mask &= (ns % f) != 0
                while rem % f == 0:
                    rem //= f
            f += 1 if f == 2 else 2
        if rem > 1:
            mask &= (ns % rem) != 0
    return mask


def _eval_pair_horizon(
    cand: PairCandidate,
    res_a: SolverResult,
    res_b: SolverResult,
    n_max: int,
    prim_mask_cache: dict[tuple[int, int, int, int], np.ndarray],
) -> dict[str, Any]:
    """Evaluate a PairCandidate on both All-N and primitive d-free stratum at horizon n_max."""
    ct_all = build_contingency(res_a.labels, res_b.labels, n_max=n_max)
    pm_all = compute_pair_metrics(ct_all)
    rel_all = summarize_exact_relations(ct_all, min_count=max(50, int(0.002 * n_max)))

    da, db = cand.spec_a.d, cand.spec_b.d
    ga, gb = cand.spec_a.g_core, cand.spec_b.g_core
    mkey = (n_max, da, db, math.lcm(ga, gb))
    mask = prim_mask_cache.get(mkey)
    if mask is None:
        mask = _make_prim_mask(cand, n_max)
        prim_mask_cache[mkey] = mask

    ct_prim = build_contingency(res_a.labels, res_b.labels, n_max=n_max, mask=mask)
    pm_prim = compute_pair_metrics(ct_prim)
    prim_total = int(mask.sum())
    rel_prim = summarize_exact_relations(ct_prim, min_count=max(50, int(0.002 * prim_total)))

    leak: dict[str, Any] = {"leakage_count": 0, "subgroup_relation": ""}
    if cand.invariant_mode == "multiplicative":
        leak = check_coset_leakage(ct_all, cand.spec_a.p, cand.spec_b.p, cand.modulus)
    elif cand.invariant_mode == "shifted":
        leak = check_coset_leakage(
            ct_all, cand.spec_a.p, cand.spec_b.p, cand.modulus, shift_c=cand.shift_c
        )

    best_gain_prim = pm_prim.best_gain if pm_prim else None
    best_raw_prim = pm_prim.best_raw_purity if pm_prim else None
    best_gain_all = pm_all.best_gain if pm_all else None

    return {
        "n_max": n_max,
        "category": cand.category,
        "subcategory": cand.subcategory,
        "p_a": cand.spec_a.p,
        "q_a": json.dumps(list(cand.spec_a.q_tuple)),
        "g_core_a": cand.spec_a.g_core,
        "p_b": cand.spec_b.p,
        "q_b": json.dumps(list(cand.spec_b.q_tuple)),
        "g_core_b": cand.spec_b.g_core,
        "invariant_mode": cand.invariant_mode,
        "modulus": cand.modulus,
        "shift_c": "" if cand.shift_c is None else cand.shift_c,
        "relation": cand.relation,
        "is_pure_jacobi": int(cand.is_pure_jacobi),
        "subgroup_relation": leak.get("subgroup_relation", ""),
        "leakage_count": leak["leakage_count"],
        "all_total": rel_all["total"],
        "all_loops_a": pm_all.n_loops_a if pm_all else len({k[0] for k in ct_all}),
        "all_loops_b": pm_all.n_loops_b if pm_all else len({k[1] for k in ct_all}),
        "all_cramers_v": round(pm_all.cramers_v, 6) if pm_all else "",
        "all_nmi": round(pm_all.nmi, 6) if pm_all else "",
        "all_exact_equalities": rel_all["exact_equalities"],
        "all_exact_strict_inclusions": rel_all["exact_strict_inclusions"],
        "all_exact_containments": rel_all["exact_containments"],
        "all_best_gain": round(best_gain_all.containment_gain, 6) if best_gain_all else "",
        "all_equal_pairs": json.dumps([list(x) for x in rel_all["exact_equal_pairs"]]),
        "all_inclusion_pairs": json.dumps([list(x) for x in rel_all["exact_inclusion_pairs"]]),
        "prim_total": rel_prim["total"],
        "prim_loops_a": pm_prim.n_loops_a if pm_prim else len({k[0] for k in ct_prim}),
        "prim_loops_b": pm_prim.n_loops_b if pm_prim else len({k[1] for k in ct_prim}),
        "prim_df": pm_prim.df if pm_prim else 0,
        "prim_chi2": round(pm_prim.chi2, 4) if pm_prim else "",
        "prim_p_value": f"{pm_prim.p_value:.3e}" if pm_prim else "",
        "prim_cramers_v": round(pm_prim.cramers_v, 6) if pm_prim else "",
        "prim_nmi": round(pm_prim.nmi, 6) if pm_prim else "",
        "prim_exact_equalities": rel_prim["exact_equalities"],
        "prim_exact_strict_inclusions": rel_prim["exact_strict_inclusions"],
        "prim_exact_containments": rel_prim["exact_containments"],
        "prim_best_purity": round(best_raw_prim.cond_prob, 6) if best_raw_prim else "",
        "prim_best_gain": round(best_gain_prim.containment_gain, 6) if best_gain_prim else "",
        "prim_best_pair": (
            f"{best_gain_prim.direction}: {best_gain_prim.source_loop}->{best_gain_prim.target_loop}"
            if best_gain_prim
            else ""
        ),
        "prim_equal_pairs": json.dumps([list(x) for x in rel_prim["exact_equal_pairs"]]),
        "prim_inclusion_pairs": json.dumps([list(x) for x in rel_prim["exact_inclusion_pairs"]]),
    }


def _select_highlight_candidates(
    candidates: list[PairCandidate],
    rows_100k: list[dict[str, Any]],
) -> list[PairCandidate]:
    """Select ~18-22 representative highlight pairs across all categories for N=1M scaling."""
    row_by_key = {
        (r["category"], r["p_a"], r["q_a"], r["p_b"], r["q_b"]): r for r in rows_100k
    }

    def _get_row(c: PairCandidate) -> dict[str, Any]:
        return row_by_key[
            (
                c.category,
                c.spec_a.p,
                json.dumps(list(c.spec_a.q_tuple)),
                c.spec_b.p,
                json.dumps(list(c.spec_b.q_tuple)),
            )
        ]

    selected: list[PairCandidate] = []
    used: set[tuple[SystemSpec, SystemSpec]] = set()

    def _pick(c: PairCandidate | None) -> None:
        if c is None:
            return
        k = (c.spec_a, c.spec_b)
        if k not in used:
            used.add(k)
            selected.append(c)

    # Cat A picks: p4 coset p-sibling, p4 2x flip, p4 non-coset p-sibling, p5 non-coset p-sibling
    for sub in ("p4_coset_p_sibling", "p4_coset_2x_flip", "p4_non_coset_p_sibling", "p5_non_coset_p_sibling"):
        pool = [c for c in candidates if c.subcategory == sub]
        pool.sort(
            key=lambda c: (
                -_get_row(c)["all_exact_equalities"],
                -(float(_get_row(c)["prim_cramers_v"]) if _get_row(c)["prim_cramers_v"] != "" else -1.0),
            )
        )
        for c in pool[: (2 if "non_coset" in sub else 2)]:
            _pick(c)

    # Cat B picks: p4 g'=13 cross-family with different loop lengths & 100% equality, g'=47, g'=35 Jacobi, p5 g'=11, p5 g'=21 Jacobi
    for sub in ("p4_g13_all34", "p4_g47_all4", "p4_g35_jacobi_all4", "p5_g11_all8", "p5_g21_jacobi_extended"):
        pool = [c for c in candidates if c.subcategory == sub]
        pool.sort(
            key=lambda c: (
                -_get_row(c)["prim_exact_equalities"],
                -_get_row(c)["all_exact_equalities"],
                -(1 if c.relation == "cross_family_same_mod" else 0),
                -(float(_get_row(c)["prim_cramers_v"]) if _get_row(c)["prim_cramers_v"] != "" else -1.0),
            )
        )
        _pick(pool[0] if pool else None)
        if sub == "p4_g13_all34" and len(pool) > 1:
            # Also pick one cross-family pair with >= 2 equalities if available
            cross = [c for c in pool if c.relation == "cross_family_same_mod"]
            if cross:
                _pick(cross[0])

    # Cat C picks: p4 vs p5 mod 11 (prefer (209,88) strict inclusion), p3 vs p4 mod 47 & mod 23
    for sub in ("p4_vs_p5_mod11", "p3_vs_p4_mod47", "p3_vs_p4_mod23"):
        pool = [c for c in candidates if c.subcategory == sub]
        pool.sort(
            key=lambda c: (
                -_get_row(c)["all_exact_equalities"],
                -_get_row(c)["all_exact_strict_inclusions"],
                -(float(_get_row(c)["prim_cramers_v"]) if _get_row(c)["prim_cramers_v"] != "" else -1.0),
            )
        )
        _pick(pool[0] if pool else None)

    # Cat D picks: p5 shifted mod 3, p7 shifted mod 5, p4 ctrl top+median, p5 ctrl top+median
    for prefix in ("p5_shifted_mod3_", "p7_shifted_mod5_"):
        pool = [c for c in candidates if c.subcategory.startswith(prefix)]
        if pool:
            pool.sort(
                key=lambda c: (
                    -_get_row(c)["all_exact_equalities"],
                    -_get_row(c)["all_exact_strict_inclusions"],
                    -(float(_get_row(c)["prim_cramers_v"]) if _get_row(c)["prim_cramers_v"] != "" else -1.0),
                )
            )
            _pick(pool[0])

    for sub in ("p4_coprime_ctrl", "p5_coprime_ctrl"):
        pool = [c for c in candidates if c.subcategory == sub and _get_row(c)["prim_cramers_v"] != ""]
        pool.sort(key=lambda c: float(_get_row(c)["prim_cramers_v"]), reverse=True)
        if pool:
            _pick(pool[0])
            _pick(pool[len(pool) // 2])

    return selected


def run_phase2(
    base_dir: Path = Path("."),
    out_dir: Path = OUT_DIR,
    n_screen: int = 100000,
    n_scale_max: int = 1000000,
) -> dict[str, Any]:
    """Phase 2: Trajectory-level exact contingency evaluation (N=100k & N=1M scaling)."""
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = _build_phase2_candidates(base_dir)
    unique_specs = list(
        dict.fromkeys([s for c in candidates for s in (c.spec_a, c.spec_b)])
    )
    print(f"[Phase 2] Solving {len(unique_specs)} unique systems up to N={n_screen}...")
    sys_results = compute_systems_parallel(unique_specs, n_max=n_screen)

    sys_csv = out_dir / "phase2_systems_100k.csv"
    with sys_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "p",
            "q_tuple",
            "gcd_q",
            "g_core",
            "n_max",
            "num_loops",
            "unconverged_count",
            "elapsed_ms",
            "loops_json",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for spec in unique_specs:
            res = sys_results[spec]
            writer.writerow(
                {
                    "p": spec.p,
                    "q_tuple": json.dumps(list(spec.q_tuple)),
                    "gcd_q": spec.gcd_q,
                    "g_core": spec.g_core,
                    "n_max": res.n_max,
                    "num_loops": len(res.loop_infos),
                    "unconverged_count": res.unconverged_count,
                    "elapsed_ms": round(res.elapsed_ms, 2),
                    "loops_json": json.dumps(
                        [
                            {
                                "min": li.loop_min,
                                "len": li.full_length,
                                "count_all": li.count_all,
                                "count_dfree": li.count_dfree,
                            }
                            for li in sorted(res.loop_infos.values(), key=lambda x: x.loop_min)
                        ]
                    ),
                }
            )

    prim_mask_cache: dict[tuple[int, int, int, int], np.ndarray] = {}
    rows_100k = [
        _eval_pair_horizon(c, sys_results[c.spec_a], sys_results[c.spec_b], n_screen, prim_mask_cache)
        for c in candidates
    ]

    pairs_csv = out_dir / "phase2_pairs_100k.csv"
    if rows_100k:
        with pairs_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_100k[0].keys()))
            writer.writeheader()
            writer.writerows(rows_100k)

    # High-resolution N=1M scaling verification on selected highlights
    highlights = _select_highlight_candidates(candidates, rows_100k)
    hl_specs = list(dict.fromkeys([s for c in highlights for s in (c.spec_a, c.spec_b)]))
    print(f"[Phase 2] Solving {len(hl_specs)} highlight systems up to N={n_scale_max} ({len(highlights)} pairs)...")
    hl_results = compute_systems_parallel(hl_specs, n_max=n_scale_max)

    checkpoints = [10000, 30000, 100000, 300000, n_scale_max]
    checkpoints = sorted({cp for cp in checkpoints if cp <= n_scale_max})
    scaling_rows: list[dict[str, Any]] = []
    hl_mask_cache: dict[tuple[int, int, int, int], np.ndarray] = {}
    highlight_tables: list[dict[str, Any]] = []

    for c in highlights:
        ra = hl_results[c.spec_a]
        rb = hl_results[c.spec_b]
        for cp in checkpoints:
            scaling_rows.append(_eval_pair_horizon(c, ra, rb, cp, hl_mask_cache))

        # Store exact full contingency tables at n_scale_max for Step 2 charts & inspection
        ct_all_1m = build_contingency(ra.labels, rb.labels, n_max=n_scale_max)
        mkey = (n_scale_max, c.spec_a.d, c.spec_b.d, math.lcm(c.spec_a.g_core, c.spec_b.g_core))
        mask_1m = hl_mask_cache[mkey]
        ct_prim_1m = build_contingency(ra.labels, rb.labels, n_max=n_scale_max, mask=mask_1m)
        highlight_tables.append(
            {
                "category": c.category,
                "subcategory": c.subcategory,
                "relation": c.relation,
                "invariant_mode": c.invariant_mode,
                "modulus": c.modulus,
                "shift_c": c.shift_c,
                "spec_a": {"p": c.spec_a.p, "q": list(c.spec_a.q_tuple)},
                "spec_b": {"p": c.spec_b.p, "q": list(c.spec_b.q_tuple)},
                "n_max": n_scale_max,
                "loops_a": {
                    str(k): {"len": v.full_length, "count_all": v.count_all, "count_dfree": v.count_dfree}
                    for k, v in sorted(ra.loop_infos.items())
                },
                "loops_b": {
                    str(k): {"len": v.full_length, "count_all": v.count_all, "count_dfree": v.count_dfree}
                    for k, v in sorted(rb.loop_infos.items())
                },
                "ct_all": [[a, b, cnt] for (a, b), cnt in sorted(ct_all_1m.items())],
                "ct_prim": [[a, b, cnt] for (a, b), cnt in sorted(ct_prim_1m.items())],
            }
        )

    scaling_csv = out_dir / "phase2_scaling_1m.csv"
    if scaling_rows:
        with scaling_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(scaling_rows[0].keys()))
            writer.writeheader()
            writer.writerows(scaling_rows)

    tables_json = out_dir / "phase2_highlight_tables.json"
    tables_json.write_text(
        json.dumps(highlight_tables, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    unconv_100k = sum(r.unconverged_count for r in sys_results.values())
    unconv_1m = sum(r.unconverged_count for r in hl_results.values())
    leak_nonzero = [r for r in rows_100k + scaling_rows if r["leakage_count"] > 0]
    summary = {
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "unique_systems_100k": len(unique_specs),
        "pairs_100k": len(rows_100k),
        "unconverged_100k": unconv_100k,
        "unique_systems_1m": len(hl_specs),
        "highlight_pairs_1m": len(highlights),
        "unconverged_1m": unconv_1m,
        "leakage_nonzero_count": len(leak_nonzero),
    }
    (out_dir / "phase2_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def _build_phase3_candidates() -> tuple[list[PairCandidate], list[PairCandidate]]:
    """Build Phase 3 targeted p=6..9 quadratic, shifted quadratic, higher-order, and cross-p pairs."""
    all_cands: list[PairCandidate] = []
    hl_cands: list[PairCandidate] = []
    seen: set[tuple[str, SystemSpec, SystemSpec]] = set()

    def _add(
        cat: str,
        subcat: str,
        sa: SystemSpec,
        sb: SystemSpec,
        mode: str,
        modulus: int,
        shift_c: int | None = None,
        rel_override: str | None = None,
        highlight: bool = False,
    ) -> None:
        if sa == sb:
            return
        if sa.p > sb.p or (sa.p == sb.p and sa.q_tuple > sb.q_tuple):
            sa, sb = sb, sa
        key = (cat, sa, sb)
        if key in seen:
            return
        seen.add(key)
        rel = rel_override or _classify_p_relation(sa, sb)
        is_jacobi = False
        if mode == "multiplicative" and modulus >= 2:
            is_jacobi = multiplicative_subgroup_cosets(sa.p, modulus).is_pure_composite_coupling
        cand = PairCandidate(
            category=cat,
            subcategory=subcat,
            spec_a=sa,
            spec_b=sb,
            invariant_mode=mode,
            modulus=modulus,
            shift_c=shift_c,
            relation=rel,
            is_pure_jacobi=is_jacobi,
        )
        all_cands.append(cand)
        if highlight:
            hl_cands.append(cand)

    # Group 3A: p=6..9 quadratic (index 2)
    for p_val, m_val in ((6, 19), (7, 19), (8, 31), (9, 7)):
        s1 = make_minimal_q_for_m(p_val, m_val, shift_idx=0, c_mod_m=0)
        s2 = make_minimal_q_for_m(p_val, m_val, shift_idx=1, c_mod_m=0)
        s3 = s1.scale(p_val)
        sub = f"p{p_val}_m{m_val}_idx2"
        _add("Phase3A_quadratic_idx2", sub, s1, s2, "multiplicative", m_val, highlight=True)
        _add("Phase3A_quadratic_idx2", sub, s1, s3, "multiplicative", m_val)
        _add("Phase3A_quadratic_idx2", sub, s2, s3, "multiplicative", m_val)

    # Group 3B: p=9 shifted quadratic (gcd=1, m=7, c=1, idx2=2 -> 3 sealed worlds)
    s9_sh1 = make_minimal_q_for_m(9, 7, shift_idx=0, c_mod_m=1)
    s9_sh2 = make_minimal_q_for_m(9, 7, shift_idx=1, c_mod_m=1)
    s9_sh3 = make_minimal_q_for_m(9, 7, shift_idx=2, c_mod_m=1)
    assert s9_sh1.gcd_q == 1 and s9_sh2.gcd_q == 1 and s9_sh3.gcd_q == 1
    _add("Phase3B_shifted_quadratic", "p9_shifted_m7_c1", s9_sh1, s9_sh2, "shifted", 7, shift_c=1, highlight=True)
    _add("Phase3B_shifted_quadratic", "p9_shifted_m7_c1", s9_sh1, s9_sh3, "shifted", 7, shift_c=1)
    _add("Phase3B_shifted_quadratic", "p9_shifted_m7_c1", s9_sh2, s9_sh3, "shifted", 7, shift_c=1)

    # Group 3C: Higher-order power residues (idx = 3, 5, 7, 12)
    for p_val, m_val, idx_val in ((8, 19, 3), (6, 31, 5), (7, 43, 7), (9, 73, 12)):
        s1 = make_minimal_q_for_m(p_val, m_val, shift_idx=0, c_mod_m=0)
        s2 = make_minimal_q_for_m(p_val, m_val, shift_idx=1, c_mod_m=0)
        s3 = s1.scale(p_val)
        sub = f"p{p_val}_m{m_val}_idx{idx_val}"
        _add("Phase3C_higher_order", sub, s1, s2, "multiplicative", m_val, highlight=True)
        _add("Phase3C_higher_order", sub, s1, s3, "multiplicative", m_val)
        _add("Phase3C_higher_order", sub, s2, s3, "multiplicative", m_val)

    # Group 3D: Cross-p equal, orthogonal, and nested hierarchies
    s5_19 = make_minimal_q_for_m(5, 19, shift_idx=0, c_mod_m=0)
    s6_19 = make_minimal_q_for_m(6, 19, shift_idx=0, c_mod_m=0)
    s7_19 = make_minimal_q_for_m(7, 19, shift_idx=0, c_mod_m=0)
    s8_19 = make_minimal_q_for_m(8, 19, shift_idx=0, c_mod_m=0)
    _add("Phase3D_cross_p", "m19_qr_p5_vs_p6", s5_19, s6_19, "multiplicative", 19, rel_override="cross_p_equal", highlight=True)
    _add("Phase3D_cross_p", "m19_qr_p5_vs_p7", s5_19, s7_19, "multiplicative", 19, rel_override="cross_p_equal")
    _add("Phase3D_cross_p", "m19_qr_p6_vs_p7", s6_19, s7_19, "multiplicative", 19, rel_override="cross_p_equal", highlight=True)
    _add("Phase3D_cross_p", "m19_orth_p6_vs_p8", s6_19, s8_19, "multiplicative", 19, rel_override="cross_p_orthogonal", highlight=True)

    s3_73 = SystemSpec(3, (73,))
    s4_73 = make_minimal_q_for_m(4, 73, shift_idx=0, c_mod_m=0)
    s9_73 = make_minimal_q_for_m(9, 73, shift_idx=0, c_mod_m=0)
    _add("Phase3D_cross_p", "m73_nested_p4_vs_p9", s4_73, s9_73, "multiplicative", 73, rel_override="cross_p_nested", highlight=True)
    _add("Phase3D_cross_p", "m73_nested_p3_vs_p9", s3_73, s9_73, "multiplicative", 73, rel_override="cross_p_nested", highlight=True)
    _add("Phase3D_cross_p", "m73_equal_p3_vs_p4", s3_73, s4_73, "multiplicative", 73, rel_override="cross_p_equal", highlight=True)

    return all_cands, hl_cands


def run_phase3(
    out_dir: Path = OUT_DIR,
    n_screen: int = 100000,
    n_scale_max: int = 1000000,
) -> dict[str, Any]:
    """Phase 3: Targeted p=6..9 quadratic, shifted quadratic, higher-order, and cross-p hierarchies."""
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates, highlights = _build_phase3_candidates()
    unique_specs = list(dict.fromkeys([s for c in candidates for s in (c.spec_a, c.spec_b)]))
    print(f"[Phase 3] Solving {len(unique_specs)} unique systems up to N={n_screen}...")
    sys_results = compute_systems_parallel(unique_specs, n_max=n_screen)

    sys_csv = out_dir / "phase3_systems_100k.csv"
    with sys_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "p",
            "q_tuple",
            "gcd_q",
            "g_core",
            "n_max",
            "num_loops",
            "unconverged_count",
            "elapsed_ms",
            "loops_json",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for spec in unique_specs:
            res = sys_results[spec]
            writer.writerow(
                {
                    "p": spec.p,
                    "q_tuple": json.dumps(list(spec.q_tuple)),
                    "gcd_q": spec.gcd_q,
                    "g_core": spec.g_core,
                    "n_max": res.n_max,
                    "num_loops": len(res.loop_infos),
                    "unconverged_count": res.unconverged_count,
                    "elapsed_ms": round(res.elapsed_ms, 2),
                    "loops_json": json.dumps(
                        [
                            {
                                "min": li.loop_min,
                                "len": li.full_length,
                                "count_all": li.count_all,
                                "count_dfree": li.count_dfree,
                            }
                            for li in sorted(res.loop_infos.values(), key=lambda x: x.loop_min)
                        ]
                    ),
                }
            )

    mask_cache_100k: dict[tuple[int, int, int, int], np.ndarray] = {}
    rows_100k = [
        _eval_pair_horizon(c, sys_results[c.spec_a], sys_results[c.spec_b], n_screen, mask_cache_100k)
        for c in candidates
    ]
    with (out_dir / "phase3_pairs_100k.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_100k[0].keys()))
        writer.writeheader()
        writer.writerows(rows_100k)

    # Solve highlight systems up to N=1,000,000
    hl_specs = list(dict.fromkeys([s for c in highlights for s in (c.spec_a, c.spec_b)]))
    print(f"[Phase 3] Solving {len(hl_specs)} highlight systems up to N={n_scale_max} ({len(highlights)} pairs)...")
    hl_results = compute_systems_parallel(hl_specs, n_max=n_scale_max)

    mask_cache_1m: dict[tuple[int, int, int, int], np.ndarray] = {}
    rows_1m: list[dict[str, Any]] = []
    highlight_tables: list[dict[str, Any]] = []

    for c in highlights:
        ra = hl_results[c.spec_a]
        rb = hl_results[c.spec_b]
        rows_1m.append(_eval_pair_horizon(c, ra, rb, n_scale_max, mask_cache_1m))
        ct_all_1m = build_contingency(ra.labels, rb.labels, n_max=n_scale_max)
        mkey = (n_scale_max, c.spec_a.d, c.spec_b.d, math.lcm(c.spec_a.g_core, c.spec_b.g_core))
        ct_prim_1m = build_contingency(ra.labels, rb.labels, n_max=n_scale_max, mask=mask_cache_1m[mkey])

        # Annotate per-loop world IDs
        def _annotate_loops(res: SolverResult) -> dict[str, Any]:
            out_d: dict[str, Any] = {}
            for k, v in sorted(res.loop_infos.items()):
                if c.invariant_mode == "multiplicative":
                    g = math.gcd(k, c.modulus)
                    world = -g if g > 1 else multiplicative_subgroup_cosets(res.spec.p, c.modulus).residue_to_coset[k % c.modulus]
                else:
                    assert c.shift_c is not None
                    u = (k + c.shift_c) % c.modulus
                    if u == 0:
                        world = -1
                    else:
                        idx2, rmap2 = shifted_coset_map(c.modulus)
                        world = 0 if idx2 == 1 else rmap2[u]
                out_d[str(k)] = {
                    "len": v.full_length,
                    "count_all": v.count_all,
                    "count_dfree": v.count_dfree,
                    "world": world,
                }
            return out_d

        highlight_tables.append(
            {
                "category": c.category,
                "subcategory": c.subcategory,
                "relation": c.relation,
                "invariant_mode": c.invariant_mode,
                "modulus": c.modulus,
                "shift_c": c.shift_c,
                "spec_a": {"p": c.spec_a.p, "q": list(c.spec_a.q_tuple)},
                "spec_b": {"p": c.spec_b.p, "q": list(c.spec_b.q_tuple)},
                "n_max": n_scale_max,
                "loops_a": _annotate_loops(ra),
                "loops_b": _annotate_loops(rb),
                "ct_all": [[a, b, cnt] for (a, b), cnt in sorted(ct_all_1m.items())],
                "ct_prim": [[a, b, cnt] for (a, b), cnt in sorted(ct_prim_1m.items())],
            }
        )

    with (out_dir / "phase3_pairs_1m.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_1m[0].keys()))
        writer.writeheader()
        writer.writerows(rows_1m)

    (out_dir / "phase3_highlight_tables.json").write_text(
        json.dumps(highlight_tables, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Also record coset-level 2x3 mixing matrix for orthogonal p=6 vs p=8 mod 19 at N=1M
    orth_mix: dict[str, int] = {}
    s6_19 = make_minimal_q_for_m(6, 19, 0, 0)
    s8_19 = make_minimal_q_for_m(8, 19, 0, 0)
    if s6_19 in hl_results and s8_19 in hl_results:
        cs6 = multiplicative_subgroup_cosets(6, 19)
        cs8 = multiplicative_subgroup_cosets(8, 19)
        ct_orth = build_contingency(hl_results[s6_19].labels, hl_results[s8_19].labels, n_max=n_scale_max)
        for (a, b), cnt in ct_orth.items():
            wa = "19N" if math.gcd(a, 19) > 1 else f"Q6_{cs6.residue_to_coset[a % 19]}"
            wb = "19N" if math.gcd(b, 19) > 1 else f"C8_{cs8.residue_to_coset[b % 19]}"
            k = f"{wa} x {wb}"
            orth_mix[k] = orth_mix.get(k, 0) + cnt

    unconv_100k = sum(r.unconverged_count for r in sys_results.values())
    unconv_1m = sum(r.unconverged_count for r in hl_results.values())
    leak_nonzero = [r for r in rows_100k + rows_1m if r["leakage_count"] > 0]
    summary = {
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "unique_systems_100k": len(unique_specs),
        "pairs_100k": len(rows_100k),
        "unconverged_100k": unconv_100k,
        "unique_systems_1m": len(hl_specs),
        "highlight_pairs_1m": len(highlights),
        "unconverged_1m": unconv_1m,
        "leakage_nonzero_count": len(leak_nonzero),
        "orthogonal_p6_vs_p8_mod19_coset_matrix_1m": dict(sorted(orth_mix.items())),
    }
    (out_dir / "phase3_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def run_phase4(out_dir: Path = OUT_DIR) -> dict[str, Any]:
    """Phase 4: Generate all visualization charts."""
    t0 = time.perf_counter()
    charts = generate_all_charts(out_dir=out_dir)
    summary = {
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "charts": [str(p) for p in charts],
    }
    (out_dir / "phase4_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run p >= 4 CTree pairing study phases.")
    parser.add_argument(
        "--phase",
        choices=["1", "2", "12", "3", "4", "34", "all"],
        default="12",
        help="Which phase(s) to execute.",
    )
    args = parser.parse_args()

    if args.phase in ("1", "12", "all"):
        s1 = run_phase1()
        print("Phase 1 summary:", json.dumps(s1, ensure_ascii=False))
    if args.phase in ("2", "12", "all"):
        s2 = run_phase2()
        print("Phase 2 summary:", json.dumps(s2, ensure_ascii=False))
    if args.phase in ("3", "34", "all"):
        s3 = run_phase3()
        print("Phase 3 summary:", json.dumps(s3, ensure_ascii=False))
    if args.phase in ("4", "34", "all"):
        s4 = run_phase4()
        print("Phase 4 summary:", json.dumps(s4, ensure_ascii=False))


if __name__ == "__main__":
    main()
