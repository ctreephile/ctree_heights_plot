"""
Tests for batch_p4_grid.py (30x30 grid runner for p=4, Q=[_, q1, q2]).
"""

from __future__ import annotations

import csv
from pathlib import Path

from backend.engine import CollatzPQEngine
from batch_p4_grid import DEFAULT_Q1_LIST, DEFAULT_Q2_LIST, run_batch


def test_q1_and_q2_header_lists():
    assert len(DEFAULT_Q1_LIST) == 30
    assert DEFAULT_Q1_LIST[:4] == [2, 5, 8, 11]
    assert DEFAULT_Q1_LIST[-1] == 89

    assert len(DEFAULT_Q2_LIST) == 30
    assert DEFAULT_Q2_LIST[:4] == [1, 4, 7, 10]
    assert DEFAULT_Q2_LIST[-1] == 88


def test_run_batch_subset_creates_dbs_images_and_csv(tmp_path: Path):
    db_dir = tmp_path / "DB"
    img_dir = tmp_path / "Images"
    csv_path = tmp_path / "p4_grid.csv"

    q1_sub = [2, 5]
    q2_sub = [1, 4]

    counts = run_batch(
        q1_list=q1_sub,
        q2_list=q2_sub,
        max_n=500,
        max_steps=5000,
        db_dir=db_dir,
        img_dir=img_dir,
        csv_path=csv_path,
        workers=1,
        skip_images=False,
    )

    assert len(counts) == 4
    for q1 in q1_sub:
        for q2 in q2_sub:
            stem = f"p4_{q1}_{q2}"
            db_file = db_dir / f"{stem}.db"
            png_file = img_dir / f"{stem}.png"
            svg_file = img_dir / f"{stem}.svg"
            assert db_file.exists() and db_file.stat().st_size > 0
            assert png_file.exists() and png_file.stat().st_size > 0
            assert svg_file.exists() and svg_file.stat().st_size > 0

    # Verify compatibility with backend CollatzPQEngine
    eng = CollatzPQEngine(db_path=db_dir / "p4_2_1.db")
    res = eng.compute_range(p=4, q_input=[None, 2, 1], n_start=1, n_end=500)
    assert res["newly_added_nodes"] == 0
    assert len(res["loops"]) == counts[(2, 1)]

    # Verify CSV structure
    assert csv_path.exists()
    with csv_path.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["q2 \\ q1", "2", "5"]
    assert rows[1][0] == "1"
    assert int(rows[1][1]) == counts[(2, 1)]
    assert int(rows[1][2]) == counts[(5, 1)]
    assert rows[2][0] == "4"
    assert int(rows[2][1]) == counts[(2, 4)]
    assert int(rows[2][2]) == counts[(5, 4)]

