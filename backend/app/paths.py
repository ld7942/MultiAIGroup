from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "MultiAIGroup"


def data_dir() -> Path:
    override = os.getenv("MULTI_AI_DATA_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        path = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "multi_ai_group.db"
