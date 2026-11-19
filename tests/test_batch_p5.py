"""
Tests for batch_p5.py and analyze_p5.py (disk-efficient p=5 master SQLite DB & analyzer).
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from analyze_p5 import analyze_db
from batch_p5 import build_q_lists, run_batch_p5


def test_p5_q_lists_divisibility():
    q1_list, q2_list, q3_list = build_q_lists(20, 20, 20)
    assert len(q1_list) == 20
    assert len(q2_list) == 20
    assert len(q3_list) == 20

    assert q1_list[:4] == [3, 7, 11, 15]
    assert q1_list[-1] == 79
    assert q2_list[:4] == [2, 6, 10, 14]
    assert q2_list[-1] == 78
    assert q3_list[:4] == [1, 5, 9, 13]
    assert q3_list[-1] == 77

    # Verify (5 * r + q_r) % 4 == 0
    for q1 in q1_list:
        assert (5 * 1 + q1) % 4 == 0
    for q2 in q2_list:
        assert (5 * 2 + q2) % 4 == 0
    for q3 in q3_list:
        assert (5 * 3 + q3) % 4 == 0


def test_run_batch_p5_and_analyze(tmp_path: Path):
    db_path = tmp_path / "p5" / "summary_p5.db"
    csv_path = tmp_path / "p5" / "summary_p5.csv"
    loops_csv_path = tmp_path / "p5" / "loops_p5.csv"
    img_dir = tmp_path / "p5" / "Images"
    traj_dir = tmp_path / "p5" / "trajectories"
    report_path = tmp_path / "p5_report.md"
    plot_path = tmp_path / "p5_diag.png"

    counts = run_batch_p5(
        q1_list=[3, 7],
        q2_list=[2, 6],
        q3_list=[1, 5],
        max_n=500,
        max_steps=5000,
        db_path=db_path,
        csv_path=csv_path,
        loops_csv_path=loops_csv_path,
        img_dir=img_dir,
        traj_dir=traj_dir,
        plot_mode="interesting",
        save_compressed_nodes=True,
        workers=1,
    )

    assert len(counts) == 8
    assert db_path.exists() and db_path.stat().st_size > 0
    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert loops_csv_path.exists() and loops_csv_path.stat().st_size > 0

    # Verify baseline (3, 2, 1) was plotted under 'interesting' mode
    assert (img_dir / "p5_3_2_1.png").exists()
    # Verify compressed binary blob was created
    assert (traj_dir / "p5_3_2_1.bin.zlib").exists()

    # Check SQLite schema & contents
    conn = sqlite3.connect(db_path)
    sys_cnt = conn.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
    loops_cnt = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    conn.close()
    assert sys_cnt == 8
    assert loops_cnt == sum(counts.values())

    # Verify CSV rows
    with csv_path.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 8

    # Run analyzer on the generated summary_p5.db
    summary = analyze_db(db_path=db_path, report_path=report_path, plot_path=plot_path)
    assert summary["total_systems"] == 8
    assert report_path.exists() and report_path.stat().st_size > 0
    assert plot_path.exists() and plot_path.stat().st_size > 0

