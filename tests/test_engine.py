"""
Pytest suite for the generalized (p, Q) Collatz backend engine and logging.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.engine import (
    CollatzPQEngine,
    normalize_q,
    predecessors_pq,
    step_pq,
    validate_pq,
)
from backend.logger import LOG_FILE, get_logger


def test_normalize_and_validate_pq():
    # p=3, Q=[None, 5] -> d=2, r=1: 3*1 + 5 = 8 (divisible by 2)
    v = validate_pq(3, [None, 5])
    assert v["valid"] is True
    assert v["strictly_divisible"] is True
    assert v["d"] == 2
    assert v["q_normalized"] == [None, 5]

    # Shorthand [5] for p=3 should also normalize to [None, 5]
    assert normalize_q(3, [5]) == [None, 5]

    # p=4 (d=3), Q=[None, 2, 1]:
    #   r=1: 4*1 + 2 = 6 (divisible by 3)
    #   r=2: 4*2 + 1 = 9 (divisible by 3)
    v4 = validate_pq(4, [None, 2, 1])
    assert v4["valid"] is True
    assert v4["strictly_divisible"] is True

    # Non-divisible warning check: p=3 (d=2), q_1=2 -> 3*1 + 2 = 5 (not divisible by 2)
    v_warn = validate_pq(3, [None, 2])
    assert v_warn["valid"] is True
    assert v_warn["strictly_divisible"] is False
    assert len(v_warn["warnings"]) == 1

    # Negative q_r should be invalid
    v_err = validate_pq(3, [None, -1])
    assert v_err["valid"] is False
    assert len(v_err["errors"]) > 0


def test_step_and_predecessors_3n1_example():
    """
    Verify user's exact specification:
    In Collatz 3n+1 (p=3, d=2, Q=[None, 1]), for n=16:
      - Forward ("前"): 8
      - Predecessors ("後"): 32 and 5
    """
    p, d, q = 3, 2, [None, 1]
    assert step_pq(16, p, d, q) == 8

    preds = predecessors_pq(16, p, d, q)
    pred_numbers = [item["n"] for item in preds]
    assert pred_numbers == [32, 5]
    # Verify both map to 16 under step_pq
    for m in pred_numbers:
        assert step_pq(m, p, d, q) == 16


def test_compute_range_3n5_and_sqlite_cache(tmp_path: Path):
    db_file = tmp_path / "test_collatz.db"
    eng = CollatzPQEngine(db_path=db_file)

    # First run: compute 1..2000 for 3n+5
    res1 = eng.compute_range(p=3, q_input=[None, 5], n_start=1, n_end=2000)
    assert res1["Newly_added_nodes" if "Newly_added_nodes" in res1 else "newly_added_nodes"] > 0

    loops = res1["loops"]
    min_vals = [lp["min_value"] for lp in loops]
    # All 6 loops of 3n+5 should be found within 1..2000 (min values: 1, 5, 19, 23, 187, 347)
    assert min_vals == [1, 5, 19, 23, 187, 347]

    # Loop [5, 20, 10] members must have 0 steps
    pts_n = res1["points"]["n"]
    pts_steps = res1["points"]["steps"]
    step_map = dict(zip(pts_n, pts_steps))
    assert step_map[5] == 0
    assert step_map[20] == 0
    assert step_map[10] == 0
    # 40 -> 20 (which is in loop), so 40 has 1 step
    assert step_map[40] == 1

    # Second run on same range: 0 newly added nodes (all cached)
    res2 = eng.compute_range(p=3, q_input=[None, 5], n_start=1, n_end=2000)
    assert res2["newly_added_nodes"] == 0

    # Reload from SQLite in a fresh engine instance
    eng_reloaded = CollatzPQEngine(db_path=db_file)
    res3 = eng_reloaded.compute_range(p=3, q_input=[None, 5], n_start=1, n_end=2000)
    assert res3["newly_added_nodes"] == 0
    assert res3["points"]["steps"] == res1["points"]["steps"]


def test_node_details_neighbors_and_same_height(tmp_path: Path):
    db_file = tmp_path / "test_details.db"
    eng = CollatzPQEngine(db_path=db_file)

    # Test node 16 in 3n+1 (p=3, Q=[None, 1])
    details = eng.get_node_details(
        p=3, q_input=[None, 1], target_n=16, n_start=1, n_end=100
    )
    assert details["target"]["n"] == 16
    assert details["target"]["next_n"] == 8

    # Immediate forward ("前") is 8
    imm_fwd = details["algorithmic_neighbors"]["immediate_forward"]
    assert imm_fwd is not None
    assert imm_fwd["n"] == 8

    # 1-step predecessors ("後") are 32 and 5
    preds1 = [x["n"] for x in details["algorithmic_neighbors"]["predecessors_step1"]]
    assert preds1 == [32, 5]

    # 2-step predecessors of 16:
    #   From 32: 64 (r=0)
    #   From 5:  10 (r=0) and (5-1)/3 not int -> [64, 10]
    preds2 = [x["n"] for x in details["algorithmic_neighbors"]["predecessors_step2"]]
    assert preds2 == [64, 10]

    # Same height nodes must all share the same step count as 16
    target_h = details["target"]["steps"]
    for node in details["same_height"]["nodes"]:
        assert node["steps"] == target_h


def test_export_png_and_svg(tmp_path: Path):
    db_file = tmp_path / "test_export.db"
    eng = CollatzPQEngine(db_path=db_file)

    png_bytes = eng.export_plot_bytes(
        p=3, q_input=[None, 5], n_start=1, n_end=500, fmt="png"
    )
    # Verify PNG signature
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    svg_bytes = eng.export_plot_bytes(
        p=3, q_input=[None, 5], n_start=1, n_end=500, fmt="svg"
    )
    assert b"<svg" in svg_bytes


def test_runtime_log_file_output():
    logger = get_logger("test_suite")
    logger.info("Verification log message from pytest.")
    assert LOG_FILE.exists()
    content = LOG_FILE.read_text(encoding="utf-8")
    assert "Verification log message from pytest." in content

