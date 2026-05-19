#!/usr/bin/env python3
"""Launch the local Vibelution web workbench."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def default_port() -> int:
    raw_value = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw_value)
    except ValueError:
        return 8000
    return port if 0 < port < 65536 else 8000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Vibelution web workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port())
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    uvicorn.run("core.web.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
