from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import (
    QDir,
    QFileSystemWatcher,
    QPoint,
    QRectF,
    QMimeData,
    QObject,
    QRunnable,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QDrag,
    QColor,
    QIcon,
    QImage,
    QImageReader,
    QPixmap,
    QPalette,
    QPainter,
    QPainterPath,
    QFont,
    QPen,
    QPolygon,
    QBrush,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFileSystemModel,
    QFormLayout,
    QHeaderView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplashScreen,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .constants import *

from .metadata_parsing import (
    extract_loras,
    extract_summary,
    find_model,
    find_sampler,
    node_text,
    parse_json_value,
    read_image_metadata as _read_image_metadata,
    resolve_node,
)

# Explicit facade binding retained for UI modules and frozen builds.
read_image_metadata = _read_image_metadata

def display_json(value: Any) -> str:
    if value is None:
        return ""
    value = parse_json_value(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def model_display_name(model: str) -> str:
    name = Path(model).name
    for suffix in (".safetensors", ".ckpt", ".pt", ".pth", ".bin"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def thumbnail_cache_path(path: Path, size: QSize) -> Path:
    try:
        stat = path.stat()
        identity = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{size.width()}x{size.height()}"
    except OSError:
        identity = f"{path.absolute()}|{size.width()}x{size.height()}"

    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    cache_dir = Path(base or (Path.home() / ".cache" / "comfyui-image-browser")) / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{digest}.png"
