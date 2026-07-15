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
from .metadata import extract_loras, extract_summary, read_image_metadata, thumbnail_cache_path

class ThumbnailSignals(QObject):
    loaded = Signal(str, QImage, bool, int)
    failed = Signal(str, str, int)


class ThumbnailWorker(QRunnable):
    def __init__(self, path: Path, thumbnail_size: QSize, generation: int) -> None:
        super().__init__()
        self.path = path
        self.thumbnail_size = thumbnail_size
        self.generation = generation
        self.signals = ThumbnailSignals()

    def run(self) -> None:
        cache_path = thumbnail_cache_path(self.path, self.thumbnail_size)
        if cache_path.is_file():
            cached = QImage(str(cache_path))
            if not cached.isNull():
                self.signals.loaded.emit(str(self.path), cached, True, self.generation)
                return

        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        source_size = reader.size()
        if source_size.isValid():
            scaled_size = source_size.scaled(
                self.thumbnail_size,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            if scaled_size.isValid():
                reader.setScaledSize(scaled_size)

        image = reader.read()
        if image.isNull():
            self.signals.failed.emit(str(self.path), reader.errorString(), self.generation)
            return

        image.save(str(cache_path), "PNG")
        self.signals.loaded.emit(str(self.path), image, False, self.generation)


class MetadataSignals(QObject):
    loaded = Signal(str, str, str, str, str, object, int, object, object)
    failed = Signal(str, str, int)


class MetadataWorker(QRunnable):
    def __init__(self, path: Path, generation: int) -> None:
        super().__init__()
        self.path = path
        self.generation = generation
        self.signals = MetadataSignals()

    def run(self) -> None:
        try:
            metadata = read_image_metadata(self.path)
            summary = extract_summary(metadata)
            model = summary["model"] or UNKNOWN_MODEL
            sampler = summary["sampler"] or UNKNOWN_SAMPLER
            scheduler = summary["scheduler"] or UNKNOWN_SCHEDULER
            positive_prompt = summary["positive"]

            image_size = QImageReader(str(self.path)).size()
            resolution = ""
            if image_size.isValid():
                resolution = f"{image_size.width()} × {image_size.height()}"

            tooltip_data = {
                "model": model,
                "sampler": sampler,
                "steps": summary.get("steps", ""),
                "scheduler": scheduler,
                "resolution": resolution,
                "loras": extract_loras(metadata),
            }
            try:
                stat = self.path.stat()
                modified_ns = int(stat.st_mtime_ns)
                file_size = int(stat.st_size)
            except OSError:
                modified_ns = 0
                file_size = 0
            self.signals.loaded.emit(
                str(self.path), model, sampler, scheduler,
                positive_prompt, tooltip_data, self.generation, modified_ns, file_size
            )
        except Exception as error:
            self.signals.failed.emit(str(self.path), str(error), self.generation)


