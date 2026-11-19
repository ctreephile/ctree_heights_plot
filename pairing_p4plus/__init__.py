"""Generalized (p >= 4, Q) CTree basin pairing and algebraic invariance study."""

from .algebra import (
    CosetStructure,
    SystemSpec,
    find_shifted_congruences,
    is_prime,
    load_p4_grid80,
    load_sqlite_summary,
    make_minimal_q_for_m,
    multiplicative_subgroup_cosets,
    p_free_core,
    primitive_family_key,
)
from .metrics import (
    ContainmentBest,
    PairMetrics,
    build_contingency,
    check_coset_leakage,
    chi2_sf,
    compute_pair_metrics,
    summarize_exact_relations,
)
from .solver import LoopInfo, SolverResult, compute_labels, compute_systems_parallel

__all__ = [
    "ContainmentBest",
    "CosetStructure",
    "LoopInfo",
    "PairMetrics",
    "SolverResult",
    "SystemSpec",
    "build_contingency",
    "check_coset_leakage",
    "chi2_sf",
    "compute_labels",
    "compute_pair_metrics",
    "compute_systems_parallel",
    "find_shifted_congruences",
    "is_prime",
    "load_p4_grid80",
    "load_sqlite_summary",
    "make_minimal_q_for_m",
    "multiplicative_subgroup_cosets",
    "p_free_core",
    "primitive_family_key",
    "summarize_exact_relations",
]

