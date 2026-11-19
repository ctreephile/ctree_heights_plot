"""
FastAPI backend for the Interactive (p, Q) Collatz Height Plotter Web Application.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.crystal import compute_crystal_generations, render_crystal_growth_gif
from backend.engine import CollatzPQEngine, DEFAULT_DB_PATH, validate_pq
from backend.logger import get_logger
from backend.p4_heatmap import compute_p4_cell, load_p4_heatmap, next_family_member_q

logger = get_logger("api")

app = FastAPI(
    title="(p, Q) Collatz Interactive Plotter API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = CollatzPQEngine(db_path=DEFAULT_DB_PATH)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    logger.info("HTTP %s %s started", request.method, request.url.path)
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "HTTP %s %s completed -> status=%d (%.2f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.exception(
            "HTTP %s %s failed after %.2f ms: %s",
            request.method,
            request.url.path,
            elapsed_ms,
            exc,
        )
        raise


class ValidateRequest(BaseModel):
    p: int = Field(..., ge=2, description="Multiplier p (natural number >= 2)")
    q: List[Optional[int]] = Field(
        ..., description="Vector Q = [_, q_1, ..., q_{p-2}] or [q_1, ..., q_{p-2}]"
    )


class ComputeRequest(BaseModel):
    p: int = Field(default=3, ge=2)
    q: List[Optional[int]] = Field(default_factory=lambda: [None, 5])
    n_start: int = Field(default=1, ge=1)
    n_end: int = Field(default=10000, ge=1)
    max_steps: int = Field(default=10000, ge=10, le=500000)


class NodeDetailsRequest(BaseModel):
    p: int = Field(default=3, ge=2)
    q: List[Optional[int]] = Field(default_factory=lambda: [None, 5])
    target_n: int = Field(..., ge=1)
    n_start: int = Field(default=1, ge=1)
    n_end: int = Field(default=10000, ge=1)
    max_steps: int = Field(default=10000, ge=10, le=500000)
    same_height_limit: int = Field(default=500, ge=10, le=10000)


class LoopTreeRequest(BaseModel):
    p: int = Field(default=3, ge=2)
    q: List[Optional[int]] = Field(default_factory=lambda: [None, 5])
    loop_id: Optional[int] = Field(default=None)
    root_n: Optional[int] = Field(default=None)
    root_mode: str = Field(default="loop", pattern="^(loop|single)$")
    max_height: int = Field(default=10, ge=1, le=25)
    max_nodes: int = Field(default=10000, ge=50, le=50000)


class CrystalGrowthRequest(BaseModel):
    p: int = Field(default=3, ge=2)
    q: List[Optional[int]] = Field(default_factory=lambda: [None, 1])
    loop_id: Optional[int] = Field(default=None)
    root_n: Optional[int] = Field(default=None)
    root_mode: str = Field(default="loop", pattern="^(loop|single)$")
    max_height: int = Field(default=8, ge=1, le=14)
    max_gen: int = Field(default=5, ge=1, le=8)
    base_multiplier: Optional[int] = Field(default=None, ge=2, le=30)
    layout_mode: str = Field(default="radial", pattern="^(radial|tree)$")
    frame_duration_ms: int = Field(default=900, ge=200, le=3000)
    show_labels: bool = Field(default=False)


class ExportRequest(BaseModel):
    p: int = Field(default=3, ge=2)
    q: List[Optional[int]] = Field(default_factory=lambda: [None, 5])
    n_start: int = Field(default=1, ge=1)
    n_end: int = Field(default=10000, ge=1)
    max_steps: int = Field(default=10000, ge=10, le=500000)
    format: str = Field(default="png", pattern="^(png|svg|PNG|SVG)$")
    visible_loop_ids: Optional[List[int]] = None
    custom_colors: Optional[Dict[str, str]] = None
    node_size: float = Field(default=2.0, ge=0.5, le=20.0)
    opacity: float = Field(default=0.88, ge=0.05, le=1.0)


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    return {"status": "ok", "db_path": str(engine.db_path)}


@app.get("/api/presets")
def get_presets() -> List[Dict[str, Any]]:
    """Return helpful (p, Q) presets satisfying (p*r + q_r) % (p-1) == 0."""
    return [
        {
            "name": "3n + 5 問題 (6ループ)",
            "p": 3,
            "q": [None, 5],
            "description": "d=2: 偶数は n/2, 奇数は 3n+5 (6つのループに到達)",
        },
        {
            "name": "3n + 1 コラッツ予想 (1ループ)",
            "p": 3,
            "q": [None, 1],
            "description": "d=2: 偶数は n/2, 奇数は 3n+1 ([1, 4, 2] ループ)",
        },
        {
            "name": "3n + 7 問題",
            "p": 3,
            "q": [None, 7],
            "description": "d=2: 偶数は n/2, 奇数は 3n+7",
        },
        {
            "name": "4n + Q (p=4, Q=[_, 2, 1])",
            "p": 4,
            "q": [None, 2, 1],
            "description": "d=3: r=0 -> n/3, r=1 -> 4n+2, r=2 -> 4n+1",
        },
        {
            "name": "4n + Q (p=4, Q=[_, 5, 4])",
            "p": 4,
            "q": [None, 5, 4],
            "description": "d=3: r=0 -> n/3, r=1 -> 4n+5, r=2 -> 4n+4",
        },
        {
            "name": "5n + Q (p=5, Q=[_, 3, 2, 1])",
            "p": 5,
            "q": [None, 3, 2, 1],
            "description": "d=4: r=0 -> n/4, r=1 -> 5n+3, r=2 -> 5n+2, r=3 -> 5n+1",
        },
    ]


@app.get("/api/summary-system")
def get_summary_system(p: int, sys_id: int) -> Dict[str, Any]:
    """Look up a system's (p, Q) by (p, system_id) from data/p{p}/summary_p{p}.db."""
    if p < 2 or p > 100 or sys_id < 1:
        raise HTTPException(status_code=400, detail="p と sys_id は正の整数を指定してください")

    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "data" / f"p{p}" / f"summary_p{p}.db"
    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"p={p} の探索データベース (data/p{p}/summary_p{p}.db) が見つかりません",
        )

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT system_id, p, q_json, gcd_q, num_loops, gini_norm "
            "FROM systems WHERE system_id = ?",
            (sys_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"p={p} のDBに sys_id={sys_id} は見つかりません",
        )

    raw_q = json.loads(row[2])
    if not raw_q or raw_q[0] is not None:
        q_norm = [None] + list(raw_q)
    else:
        q_norm = list(raw_q)

    return {
        "system_id": row[0],
        "p": row[1],
        "q": q_norm,
        "gcd_q": row[3],
        "num_loops": row[4],
        "gini_norm": row[5],
    }


@app.post("/api/validate")
def api_validate(req: ValidateRequest) -> Dict[str, Any]:
    return validate_pq(req.p, req.q)


@app.post("/api/compute")
def api_compute(req: ComputeRequest) -> Dict[str, Any]:
    try:
        return engine.compute_range(
            p=req.p,
            q_input=req.q,
            n_start=req.n_start,
            n_end=req.n_end,
            max_steps=req.max_steps,
        )
    except ValueError as exc:
        logger.warning("Validation/range error in /api/compute: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/node-details")
def api_node_details(req: NodeDetailsRequest) -> Dict[str, Any]:
    try:
        return engine.get_node_details(
            p=req.p,
            q_input=req.q,
            target_n=req.target_n,
            n_start=req.n_start,
            n_end=req.n_end,
            max_steps=req.max_steps,
            same_height_limit=req.same_height_limit,
        )
    except ValueError as exc:
        logger.warning("Validation error in /api/node-details: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/loop-tree")
def api_loop_tree(req: LoopTreeRequest) -> Dict[str, Any]:
    try:
        return engine.build_loop_tree(
            p=req.p,
            q_input=req.q,
            loop_id=req.loop_id,
            root_n=req.root_n,
            root_mode=req.root_mode,
            max_height=req.max_height,
            max_nodes=req.max_nodes,
        )
    except ValueError as exc:
        logger.warning("Validation error in /api/loop-tree: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/crystal-growth")
def api_crystal_growth(req: CrystalGrowthRequest) -> Dict[str, Any]:
    try:
        return compute_crystal_generations(
            engine=engine,
            p=req.p,
            q_input=req.q,
            loop_id=req.loop_id,
            root_n=req.root_n,
            root_mode=req.root_mode,
            max_height=req.max_height,
            max_gen=req.max_gen,
            base_multiplier=req.base_multiplier,
        )
    except ValueError as exc:
        logger.warning("Validation error in /api/crystal-growth: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/crystal-growth-gif")
def api_crystal_growth_gif(req: CrystalGrowthRequest) -> Response:
    try:
        crystal_data = compute_crystal_generations(
            engine=engine,
            p=req.p,
            q_input=req.q,
            loop_id=req.loop_id,
            root_n=req.root_n,
            root_mode=req.root_mode,
            max_height=req.max_height,
            max_gen=req.max_gen,
            base_multiplier=req.base_multiplier,
        )
        gif_bytes = render_crystal_growth_gif(
            crystal_data=crystal_data,
            layout_mode=req.layout_mode,
            frame_duration_ms=req.frame_duration_ms,
            show_labels=req.show_labels,
        )
        q_str = "_".join(str(x) for x in req.q[1:] if x is not None)
        g = crystal_data["base_multiplier"]
        filename = f"CTree_Crystal_p{req.p}_Q{q_str}_x{g}_h{req.max_height}.gif"
        return Response(
            content=gif_bytes,
            media_type="image/gif",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as exc:
        logger.warning("Validation error in /api/crystal-growth-gif: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/export")
def api_export(req: ExportRequest) -> Response:
    try:
        fmt = req.format.lower()
        img_bytes = engine.export_plot_bytes(
            p=req.p,
            q_input=req.q,
            n_start=req.n_start,
            n_end=req.n_end,
            max_steps=req.max_steps,
            fmt=fmt,
            visible_loop_ids=req.visible_loop_ids,
            custom_colors=req.custom_colors,
            node_size=req.node_size,
            opacity=req.opacity,
        )
        media_type = "image/svg+xml" if fmt == "svg" else "image/png"
        q_str = "_".join(str(x) for x in req.q[1:] if x is not None)
        filename = f"iter_p{req.p}_Q{q_str}_{req.n_start}_{req.n_end}.{fmt}"
        return Response(
            content=img_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as exc:
        logger.warning("Error in /api/export: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class P4HeatmapAddNextRequest(BaseModel):
    base_q1: int = Field(..., ge=2)
    base_q2: int = Field(..., ge=1)
    existing_qs: List[List[int]] = Field(default_factory=list)
    max_height: int = Field(default=10, ge=1, le=14)


@app.get("/api/p4-heatmap")
def api_p4_heatmap(max_height: int = 10, grid_size: Optional[int] = None) -> Dict[str, Any]:
    try:
        return load_p4_heatmap(max_height=max_height, grid_size=grid_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error in /api/p4-heatmap: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/p4-heatmap/add-next")
def api_p4_heatmap_add_next(req: P4HeatmapAddNextRequest) -> Dict[str, Any]:
    try:
        existing = {(int(pair[0]), int(pair[1])) for pair in req.existing_qs if len(pair) == 2}
        g, q1, q2 = next_family_member_q(req.base_q1, req.base_q2, existing)
        cell = compute_p4_cell(q1=q1, q2=q2, max_height=req.max_height)
        return {"g": g, "cell": cell}
    except ValueError as exc:
        logger.warning("Validation error in /api/p4-heatmap/add-next: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error in /api/p4-heatmap/add-next: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Serve built Svelte frontend if available
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

