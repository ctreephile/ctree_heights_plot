"""Unit tests for pairing_p4plus algebra, solver, metrics, and invariance laws."""

from __future__ import annotations

import math
from pathlib import Path

from backend.engine import CollatzPQEngine
from pairing_p4plus.algebra import (
    SystemSpec,
    find_shifted_congruences,
    multiplicative_subgroup_cosets,
    p_free_core,
    primitive_family_key,
)
from pairing_p4plus.metrics import (
    build_contingency,
    check_coset_leakage,
    chi2_sf,
    compute_pair_metrics,
)
from pairing_p4plus.solver import compute_labels


def test_solver_matches_backend_engine_across_p3_to_p9(tmp_path: Path) -> None:
    """Verify solver.compute_labels matches CollatzPQEngine loop min_value and length."""
    engine = CollatzPQEngine(db_path=tmp_path / "verify.db")
    specs = [
        SystemSpec(3, (23,)),
        SystemSpec(4, (26, 13)),
        SystemSpec(4, (26, 91)),
        SystemSpec(5, (11, 22, 33)),
        SystemSpec(6, (4, 3, 2, 1)),
        SystemSpec(7, (11, 16, 21, 26, 1)),
        SystemSpec(8, (13, 19, 4, 10, 16, 1)),
        SystemSpec(9, (7, 6, 13, 20, 3, 2, 1)),
    ]
    n_max = 2000
    for spec in specs:
        assert spec.is_valid()
        res = compute_labels(spec, n_max=n_max)
        assert res.unconverged_count == 0

        eng_out = engine.compute_range(
            p=spec.p,
            q_input=spec.q_norm,
            n_start=1,
            n_end=n_max,
            max_steps=50000,
        )
        loop_by_id = {lp["loop_id"]: lp for lp in eng_out["loops"]}
        pts = eng_out["points"]
        for n, lid in zip(pts["n"], pts["loop_id"]):
            assert lid != 0
            eng_lp = loop_by_id[lid]
            got_min = int(res.labels[n])
            assert got_min == eng_lp["min_value"]
            assert res.loop_infos[got_min].full_length == eng_lp["length"]


def test_multiplicative_subgroup_cosets_and_pure_composite_flags() -> None:
    """Verify subgroup indices and pure composite Jacobi flags across p=3..9."""
    expected = [
        (3, 23, 2, False),
        (4, 11, 2, False),
        (4, 13, 2, False),
        (4, 35, 2, True),
        (5, 11, 2, False),
        (5, 21, 2, True),
        (6, 31, 5, False),
        (7, 43, 7, False),
        (8, 19, 3, False),
        (9, 7, 2, False),
        (9, 73, 12, False),
    ]
    for p, m, exp_idx, exp_jacobi in expected:
        cs = multiplicative_subgroup_cosets(p, m)
        assert cs.index == exp_idx
        assert cs.is_pure_composite_coupling is exp_jacobi
        assert len(cs.residue_to_coset) == cs.phi

    assert p_free_core(94, 4) == 47
    assert p_free_core(55, 5) == 11
    assert p_free_core(12, 4) == 3


def test_primitive_family_key_and_scale_conjugacy() -> None:
    """Verify scale() and primitive_family_key() agree on p=4 flip/sibling relations."""
    s = SystemSpec(4, (26, 13))
    assert s.scale(2) == SystemSpec(4, (26, 52))
    assert s.scale(4) == SystemSpec(4, (104, 52))
    assert primitive_family_key(4, (26, 13)) == (13, (2, 1))
    assert primitive_family_key(4, (26, 52)) == (26, (2, 1))
    assert primitive_family_key(4, (2, 22)) == (2, (11, 1))

    s5 = SystemSpec(5, (3, 2, 1))
    assert s5.scale(5) == SystemSpec(5, (15, 10, 5))
    assert primitive_family_key(5, (15, 10, 5)) == (5, (3, 2, 1))


def test_empirical_coset_and_shifted_conservation_laws() -> None:
    """Verify zero cross-coset and zero shifted-world leakage on N=5000 trajectories."""
    n_max = 5000

    # 1. p=4 same-mod cross-family: (26, 13) vs (26, 91) mod 13
    r_a = compute_labels(SystemSpec(4, (26, 13)), n_max)
    r_b = compute_labels(SystemSpec(4, (26, 91)), n_max)
    ct_13 = build_contingency(r_a.labels, r_b.labels, n_max=n_max)
    leak_13 = check_coset_leakage(ct_13, 4, 4, 13)
    assert leak_13["leakage_count"] == 0
    pm_13 = compute_pair_metrics(ct_13)
    assert pm_13 is not None
    assert pm_13.exact_equalities >= 2

    # 2. p=4 pure composite Jacobi wall mod 35: (35, 70) vs (35, 175)
    r_35a = compute_labels(SystemSpec(4, (35, 70)), n_max)
    r_35b = compute_labels(SystemSpec(4, (35, 175)), n_max)
    ct_35 = build_contingency(r_35a.labels, r_35b.labels, n_max=n_max)
    leak_35 = check_coset_leakage(ct_35, 4, 4, 35)
    assert leak_35["leakage_count"] == 0

    # 3. p=5 mod 11: (11, 22, 33) vs (11, 22, 77)
    r_5a = compute_labels(SystemSpec(5, (11, 22, 33)), n_max)
    r_5b = compute_labels(SystemSpec(5, (11, 22, 77)), n_max)
    ct_5 = build_contingency(r_5a.labels, r_5b.labels, n_max=n_max)
    leak_5 = check_coset_leakage(ct_5, 5, 5, 11)
    assert leak_5["leakage_count"] == 0

    # 4. Cross-p mod 11: p=4 (209, 88) vs p=5 (11, 22, 33)
    r_4_209 = compute_labels(SystemSpec(4, (209, 88)), n_max)
    ct_cross = build_contingency(r_4_209.labels, r_5a.labels, n_max=n_max)
    leak_cross = check_coset_leakage(ct_cross, 4, 5, 11)
    assert leak_cross["subgroup_relation"] == "equal"
    assert leak_cross["leakage_count"] == 0

    # 5. Shifted congruence (gcd=1): p=5 (7, 10, 1) vs (7, 10, 13) mod 3, c=1
    s_sh1 = SystemSpec(5, (7, 10, 1))
    s_sh2 = SystemSpec(5, (7, 10, 13))
    assert s_sh1.gcd_q == 1 and s_sh2.gcd_q == 1
    assert find_shifted_congruences(5, s_sh1.q_tuple) == [(3, 1, 1)]
    r_sh1 = compute_labels(s_sh1, n_max)
    r_sh2 = compute_labels(s_sh2, n_max)
    ct_sh = build_contingency(r_sh1.labels, r_sh2.labels, n_max=n_max)
    leak_sh = check_coset_leakage(ct_sh, 5, 5, 3, shift_c=1)
    assert leak_sh["fixed_total"] > 0
    assert leak_sh["leakage_count"] == 0


def test_metrics_synthetic_tables_and_chi2_sf() -> None:
    """Verify compute_pair_metrics on diagonal, nested, and uniform contingency tables."""
    # Exact 100% diagonal equality
    diag = {(1, 10): 500, (2, 20): 500}
    pm_d = compute_pair_metrics(diag)
    assert pm_d is not None
    assert math.isclose(pm_d.cramers_v, 1.0, rel_tol=1e-9)
    assert pm_d.exact_equalities == 2
    assert pm_d.exact_strict_inclusions == 0
    assert pm_d.exact_containments == 4

    # Block-nested strict inclusion: X=10 & X=20 both inside A=1; X=30 == A=2
    nested = {(1, 10): 300, (1, 20): 200, (2, 30): 500}
    pm_n = compute_pair_metrics(nested)
    assert pm_n is not None
    assert math.isclose(pm_n.cramers_v, 1.0, rel_tol=1e-9)
    assert pm_n.exact_equalities == 1
    assert pm_n.exact_strict_inclusions == 2
    assert pm_n.exact_containments == 4

    # Uniform independent table
    unif = {(1, 10): 250, (1, 20): 250, (2, 10): 250, (2, 20): 250}
    pm_u = compute_pair_metrics(unif)
    assert pm_u is not None
    assert math.isclose(pm_u.chi2, 0.0, abs_tol=1e-12)
    assert math.isclose(pm_u.cramers_v, 0.0, abs_tol=1e-12)
    assert math.isclose(pm_u.p_value, 1.0, abs_tol=1e-12)
    assert pm_u.exact_equalities == 0

    # Chi2 survival function sanity check (df=2: exp(-chi2/2))
    assert math.isclose(chi2_sf(4.0, 2), math.exp(-2.0), rel_tol=1e-10)


def test_phase3_higher_order_shifted_quadratic_and_nested_cross_p() -> None:
    """Verify Phase 3 higher-order cosets, p=9 shifted quadratic wall, and nested/orthogonal cross-p."""
    n_max = 5000

    # 1. p=6, m=31 (index 5)
    r_6a = compute_labels(SystemSpec(6, (124, 93, 62, 31)), n_max)
    r_6b = compute_labels(SystemSpec(6, (124, 93, 62, 186)), n_max)
    assert r_6a.unconverged_count == 0 and r_6b.unconverged_count == 0
    leak_6 = check_coset_leakage(build_contingency(r_6a.labels, r_6b.labels, n_max=n_max), 6, 6, 31)
    assert leak_6["join_index"] == 5
    assert leak_6["leakage_count"] == 0

    # 2. p=8, m=19 (index 3)
    r_8a = compute_labels(SystemSpec(8, (76, 19, 95, 38, 114, 57)), n_max)
    r_8b = compute_labels(SystemSpec(8, (76, 19, 95, 38, 114, 190)), n_max)
    assert r_8a.unconverged_count == 0 and r_8b.unconverged_count == 0
    leak_8 = check_coset_leakage(build_contingency(r_8a.labels, r_8b.labels, n_max=n_max), 8, 8, 19)
    assert leak_8["join_index"] == 3
    assert leak_8["leakage_count"] == 0

    # 3. p=9, m=7 (index 2)
    r_9a = compute_labels(SystemSpec(9, (7, 14, 21, 28, 35, 42, 49)), n_max)
    r_9b = compute_labels(SystemSpec(9, (7, 14, 21, 28, 35, 42, 105)), n_max)
    ct_9 = build_contingency(r_9a.labels, r_9b.labels, n_max=n_max)
    leak_9 = check_coset_leakage(ct_9, 9, 9, 7)
    pm_9 = compute_pair_metrics(ct_9)
    assert leak_9["join_index"] == 2
    assert leak_9["leakage_count"] == 0
    assert pm_9 is not None and pm_9.exact_equalities >= 1

    # 4. p=9, m=7, c=1 shifted quadratic (gcd=1, idx2=2 -> 3 sealed worlds)
    s9_sh1 = SystemSpec(9, (15, 22, 29, 36, 43, 50, 1))
    s9_sh2 = SystemSpec(9, (15, 22, 29, 36, 43, 50, 57))
    assert s9_sh1.gcd_q == 1 and s9_sh2.gcd_q == 1
    assert find_shifted_congruences(9, s9_sh1.q_tuple) == [(7, 1, 2)]
    r_9sh1 = compute_labels(s9_sh1, n_max)
    r_9sh2 = compute_labels(s9_sh2, n_max)
    ct_9sh = build_contingency(r_9sh1.labels, r_9sh2.labels, n_max=n_max)
    leak_9sh = check_coset_leakage(ct_9sh, 9, 9, 7, shift_c=1)
    assert leak_9sh["idx2"] == 2
    assert leak_9sh["fixed_total"] > 0
    assert leak_9sh["leakage_count"] == 0

    # 5. Nested cross-p mod 73: p=4 (146, 73) vs p=9 (511, 438, 365, 292, 219, 146, 73)
    r_4_73 = compute_labels(SystemSpec(4, (146, 73)), n_max)
    r_9_73 = compute_labels(SystemSpec(9, (511, 438, 365, 292, 219, 146, 73)), n_max)
    leak_4_9 = check_coset_leakage(build_contingency(r_4_73.labels, r_9_73.labels, n_max=n_max), 4, 9, 73)
    assert leak_4_9["subgroup_relation"] == "B_sub_A"
    assert leak_4_9["join_index"] == 2
    assert leak_4_9["leakage_count"] == 0

    # 6. Orthogonal cross-p mod 19: p=6 (19, 38, 57, 76) vs p=8 (76, 19, 95, 38, 114, 57)
    r_6_19 = compute_labels(SystemSpec(6, (19, 38, 57, 76)), n_max)
    leak_6_8 = check_coset_leakage(build_contingency(r_6_19.labels, r_8a.labels, n_max=n_max), 6, 8, 19)
    assert leak_6_8["subgroup_relation"] == "different"
    assert leak_6_8["join_index"] == 1
    assert leak_6_8["leakage_count"] == 0
