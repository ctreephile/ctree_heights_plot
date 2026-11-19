"""
Tests for batch_p3.py and analyze_p3.py (disk-efficient p=3 master SQLite DB & analyzer).
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from analyze_p3 import analyze_db
from batch_p3 import build_q1_list, run_batch_p3


def test_p3_q1_list_generation():
    q1_list = build_q1_list(10000)
    assert len(q1_list) == 10000
    assert q1_list[:5] == [1, 3, 5, 7, 9]
    assert q1_list[-1] == 19999
    for q1 in q1_list[:50]:
        assert (3 * 1 + q1) % 2 == 0


def test_run_batch_p3_and_analyze(tmp_path: Path):
    db_path = tmp_path / "p3" / "summary_p3.db"
    csv_path = tmp_path / "p3" / "summary_p3.csv"
    loops_csv_path = tmp_path / "p3" / "loops_p3.csv"
    img_dir = tmp_path / "p3" / "Images"
    traj_dir = tmp_path / "p3" / "trajectories"
    report_path = tmp_path / "p3_report.md"
    plot_path = tmp_path / "p3_diag.png"

    counts = run_batch_p3(
        q1_list=[1, 3, 5, 15, 25],
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

    assert len(counts) == 5
    # Verify complete clone heredity for 3x scaling: q1=1 -> 3 (1 loop each), q1=5 -> 15 (6 loops each)
    assert counts[1] == counts[3] == 1
    assert counts[5] == counts[15] == 6
    assert counts[25] >= counts[5]

    assert db_path.exists() and db_path.stat().st_size > 0
    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert loops_csv_path.exists() and loops_csv_path.stat().st_size > 0
    assert (img_dir / "p3_5.png").exists()
    assert (traj_dir / "p3_5.bin.zlib").exists()

    conn = sqlite3.connect(db_path)
    sys_cnt = conn.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
    loops_cnt = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
    conn.close()
    assert sys_cnt == 5
    assert loops_cnt == sum(counts.values())

    with csv_path.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5

    summary = analyze_db(db_path=db_path, report_path=report_path, plot_path=plot_path)
    assert summary["total_systems"] == 5
    assert report_path.exists() and report_path.stat().st_size > 0
    assert plot_path.exists() and plot_path.stat().st_size > 0
