from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
PATH_ROLE = int(Qt.ItemDataRole.UserRole)
MODEL_ROLE = PATH_ROLE + 1
THUMB_STATE_ROLE = PATH_ROLE + 2
POSITIVE_PROMPT_ROLE = PATH_ROLE + 3
SAMPLER_ROLE = PATH_ROLE + 4
SCHEDULER_ROLE = PATH_ROLE + 5
MODIFIED_ROLE = PATH_ROLE + 6
RATING_ROLE = PATH_ROLE + 7
STATE_NOT_REQUESTED = 0
STATE_QUEUED = 1
STATE_READY = 2
STATE_FAILED = 3
UNKNOWN_MODEL = "Unknown"
UNKNOWN_SAMPLER = "Unknown"
UNKNOWN_SCHEDULER = "Unknown"


def asset_path(filename: str) -> Path:
    """
    Return the location of a bundled application asset.

    This works when running from source and is also compatible with common
    PyInstaller builds that expose their extraction directory through
    ``sys._MEIPASS``.
    """
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "assets" / filename
    return Path(__file__).resolve().parent / "assets" / filename


