#!/usr/bin/env python3
"""
Launcher script for the Interactive (p, Q) Collatz Web Application.

Usage:
    .\.venv\Scripts\python run_app.py
"""

from __future__ import annotations

import argparse
import uvicorn
from backend.logger import get_logger

logger = get_logger("launcher")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the (p, Q) Collatz Interactive Web Application server."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    logger.info("Starting uvicorn server at http://%s:%d", args.host, args.port)
    print(f"Starting server at http://{args.host}:{args.port}")
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

