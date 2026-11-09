"""后端入口：python -m app.main"""
from __future__ import annotations

import os

import uvicorn

from .api import create_app

app = create_app()


def main() -> None:
    host = os.environ.get("MULTI_AI_HOST", "127.0.0.1")
    port = int(os.environ.get("MULTI_AI_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
