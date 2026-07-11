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
from .metadata import (
    extract_loras, extract_summary, read_image_metadata,
)
from .widgets import ImageDragListWidget

class CompareImageView(QScrollArea):
    """Scrollable image view with wheel zoom and drag panning."""

    zoom_changed = Signal(float)
    pan_changed = Signal(float, float)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.original = QPixmap(str(path))
        self.zoom_factor = 1.0
        self._dragging = False
        self._drag_origin = QPoint()
        self._scroll_origin = QPoint()
        self._syncing = False

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setBackgroundRole(QPalette.ColorRole.Base)
        self.setWidget(self.label)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        self.horizontalScrollBar().valueChanged.connect(self._emit_pan)
        self.verticalScrollBar().valueChanged.connect(self._emit_pan)

        if self.original.isNull():
            self.label.setText(f"Unable to load {path.name}")
        else:
            self.fit_to_view()

    def set_image(self, path: Path) -> None:
        """Replace the displayed image while preserving the view widget."""
        self.path = path
        self.original = QPixmap(str(path))
        self.zoom_factor = 1.0
        self.label.clear()
        if self.original.isNull():
            self.label.setText(f"Unable to load {path.name}")
            self.label.adjustSize()
        else:
            QTimer.singleShot(0, self.fit_to_view)

    def _render(self) -> None:
        if self.original.isNull():
            return
        size = self.original.size() * self.zoom_factor
        size.setWidth(max(1, size.width()))
        size.setHeight(max(1, size.height()))
        scaled = self.original.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.label.setPixmap(scaled)
        self.label.resize(scaled.size())

    def fit_to_view(self) -> None:
        if self.original.isNull():
            return
        viewport = self.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return
        self.zoom_factor = min(
            viewport.width() / self.original.width(),
            viewport.height() / self.original.height(),
            1.0,
        )
        self._render()
        self.zoom_changed.emit(self.zoom_factor)

    def set_actual_size(self) -> None:
        self.set_zoom(1.0)

    def set_zoom(self, factor: float, emit_signal: bool = True) -> None:
        if self.original.isNull():
            return
        factor = max(0.05, min(factor, 16.0))
        if abs(factor - self.zoom_factor) < 1e-6:
            return
        centre_x, centre_y = self.normalized_pan()
        self.zoom_factor = factor
        self._render()
        QTimer.singleShot(0, lambda: self.set_normalized_pan(centre_x, centre_y))
        if emit_signal:
            self.zoom_changed.emit(self.zoom_factor)

    def normalized_pan(self) -> tuple[float, float]:
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        x = h.value() / h.maximum() if h.maximum() else 0.5
        y = v.value() / v.maximum() if v.maximum() else 0.5
        return x, y

    def set_normalized_pan(self, x: float, y: float) -> None:
        self._syncing = True
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        h.setValue(round(max(0.0, min(x, 1.0)) * h.maximum()))
        v.setValue(round(max(0.0, min(y, 1.0)) * v.maximum()))
        self._syncing = False

    def _emit_pan(self, _value: int) -> None:
        if not self._syncing:
            self.pan_changed.emit(*self.normalized_pan())

    def wheelEvent(self, event) -> None:
        if True:
            step = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom_factor * step)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_origin = event.position().toPoint()
            self._scroll_origin = QPoint(
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            delta = event.position().toPoint() - self._drag_origin
            self.horizontalScrollBar().setValue(self._scroll_origin.x() - delta.x())
            self.verticalScrollBar().setValue(self._scroll_origin.y() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ComparisonDialog(QDialog):
    """Side-by-side image and metadata comparison."""

    def __init__(self, path_a: Path, path_b: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Compare — {path_a.name} / {path_b.name}")
        self.resize(1500, 900)
        self.path_a = path_a
        self.path_b = path_b
        self.metadata_a = read_image_metadata(path_a)
        self.metadata_b = read_image_metadata(path_b)
        self.summary_a = extract_summary(self.metadata_a)
        self.summary_b = extract_summary(self.metadata_b)
        self._syncing = False

        self.view_a = CompareImageView(path_a)
        self.view_b = CompareImageView(path_b)
        self.link_checkbox = QCheckBox("Link zoom and pan")
        self.link_checkbox.setChecked(True)

        self.view_a.zoom_changed.connect(lambda z: self._sync_zoom(self.view_b, z))
        self.view_b.zoom_changed.connect(lambda z: self._sync_zoom(self.view_a, z))
        self.view_a.pan_changed.connect(lambda x, y: self._sync_pan(self.view_b, x, y))
        self.view_b.pan_changed.connect(lambda x, y: self._sync_pan(self.view_a, x, y))

        image_splitter = QSplitter(Qt.Orientation.Horizontal)
        image_splitter.addWidget(self._image_column("Image A", path_a, self.view_a))
        image_splitter.addWidget(self._image_column("Image B", path_b, self.view_b))
        image_splitter.setSizes([750, 750])
        image_splitter.splitterMoved.connect(
            lambda _position, _index: QTimer.singleShot(0, self.fit_both)
        )

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Field", "Image A", "Image B"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._populate_table()

        prompt_a = QPlainTextEdit(self.summary_a["positive"])
        prompt_b = QPlainTextEdit(self.summary_b["positive"])
        for editor in (prompt_a, prompt_b):
            editor.setReadOnly(True)
            editor.setMinimumHeight(100)
        prompt_splitter = QSplitter(Qt.Orientation.Horizontal)
        prompt_splitter.addWidget(self._prompt_column("Positive prompt A", prompt_a))
        prompt_splitter.addWidget(self._prompt_column("Positive prompt B", prompt_b))

        lora_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.lora_table_a = self._create_lora_table()
        self.lora_table_b = self._create_lora_table()
        lora_splitter.addWidget(self._lora_column("LoRAs used by Image A", self.lora_table_a))
        lora_splitter.addWidget(self._lora_column("LoRAs used by Image B", self.lora_table_b))
        lora_splitter.setSizes([750, 750])
        self._populate_lora_tables()

        fit_button = QPushButton("Fit Both")
        fit_button.clicked.connect(self.fit_both)
        actual_button = QPushButton("100%")
        actual_button.clicked.connect(self.actual_both)
        swap_button = QPushButton("Swap A/B")
        swap_button.clicked.connect(self.swap_images)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)

        controls = QHBoxLayout()
        controls.addWidget(self.link_checkbox)
        controls.addWidget(fit_button)
        controls.addWidget(actual_button)
        controls.addWidget(swap_button)
        controls.addStretch(1)
        controls.addWidget(close_buttons)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_tabs = QTabWidget()
        lower_tabs.addTab(self.table, "Parameters")
        lower_tabs.addTab(prompt_splitter, "Positive prompts")
        lower_tabs.addTab(lora_splitter, "LoRAs")
        lower_layout.addWidget(lower_tabs)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(image_splitter)
        main_splitter.addWidget(lower)
        main_splitter.setSizes([580, 300])

        layout = QVBoxLayout(self)
        layout.addWidget(main_splitter, 1)
        layout.addLayout(controls)
        QTimer.singleShot(0, self.fit_both)

    @staticmethod
    def _image_column(title: str, path: Path, view: CompareImageView) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(f"<b>{title}</b> — {path.name}")
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)
        layout.addWidget(view, 1)
        return widget

    @staticmethod
    def _prompt_column(title: str, editor: QPlainTextEdit) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        layout.addWidget(editor)
        return widget

    @staticmethod
    def _create_lora_table() -> QTableWidget:
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["LoRA", "Model strength", "CLIP strength"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        return table

    @staticmethod
    def _lora_column(title: str, table: QTableWidget) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        layout.addWidget(table)
        return widget

    def _populate_lora_tables(self) -> None:
        loras_a = {item["name"]: item for item in extract_loras(self.metadata_a)}
        loras_b = {item["name"]: item for item in extract_loras(self.metadata_b)}
        names = sorted(set(loras_a) | set(loras_b), key=str.casefold)

        self.lora_table_a.setRowCount(len(names))
        self.lora_table_b.setRowCount(len(names))
        difference_brush = QBrush(QColor(58, 79, 102))
        missing_brush = QBrush(QColor(92, 52, 52))
        foreground = QBrush(QColor(255, 255, 255))

        for row, name in enumerate(names):
            item_a = loras_a.get(name)
            item_b = loras_b.get(name)
            values_a = (
                name if item_a else f"{name} (not used)",
                item_a["model_strength"] if item_a else "—",
                item_a["clip_strength"] if item_a else "—",
            )
            values_b = (
                name if item_b else f"{name} (not used)",
                item_b["model_strength"] if item_b else "—",
                item_b["clip_strength"] if item_b else "—",
            )
            differs = item_a != item_b

            for table, values, present in (
                (self.lora_table_a, values_a, item_a is not None),
                (self.lora_table_b, values_b, item_b is not None),
            ):
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column in (1, 2):
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if not present:
                        cell.setBackground(missing_brush)
                        cell.setForeground(foreground)
                    elif differs:
                        cell.setBackground(difference_brush)
                        cell.setForeground(foreground)
                    table.setItem(row, column, cell)

        if not names:
            for table in (self.lora_table_a, self.lora_table_b):
                table.setRowCount(1)
                message = QTableWidgetItem("No LoRAs detected")
                message.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setSpan(0, 0, 1, 3)
                table.setItem(0, 0, message)

        self.lora_table_a.resizeRowsToContents()
        self.lora_table_b.resizeRowsToContents()

    def _populate_table(self) -> None:
        fields = [
            ("Filename", self.path_a.name, self.path_b.name),
            ("Model", self.summary_a["model"], self.summary_b["model"]),
            ("Seed", self.summary_a["seed"], self.summary_b["seed"]),
            ("Steps", self.summary_a["steps"], self.summary_b["steps"]),
            ("CFG", self.summary_a["cfg"], self.summary_b["cfg"]),
            ("Sampler", self.summary_a["sampler"], self.summary_b["sampler"]),
            ("Scheduler", self.summary_a["scheduler"], self.summary_b["scheduler"]),
            ("Denoise", self.summary_a["denoise"], self.summary_b["denoise"]),
            ("Resolution", self._resolution(self.path_a), self._resolution(self.path_b)),
        ]
        self.table.setRowCount(len(fields))
        difference_brush = QBrush(QColor(58, 79, 102))
        for row, (field, a, b) in enumerate(fields):
            values = (field, a or "—", b or "—")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (1, 2) and str(a) != str(b):
                    item.setBackground(difference_brush)
                    item.setForeground(QBrush(QColor(255, 255, 255)))
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()

    @staticmethod
    def _resolution(path: Path) -> str:
        reader = QImageReader(str(path))
        size = reader.size()
        return f"{size.width()}×{size.height()}" if size.isValid() else ""

    def _sync_zoom(self, target: CompareImageView, factor: float) -> None:
        if not self.link_checkbox.isChecked() or self._syncing:
            return
        self._syncing = True
        target.set_zoom(factor, emit_signal=False)
        self._syncing = False

    def _sync_pan(self, target: CompareImageView, x: float, y: float) -> None:
        if not self.link_checkbox.isChecked() or self._syncing:
            return
        self._syncing = True
        target.set_normalized_pan(x, y)
        self._syncing = False

    def fit_both(self) -> None:
        self._syncing = True
        self.view_a.fit_to_view()
        self.view_b.fit_to_view()
        self._syncing = False

    def actual_both(self) -> None:
        self._syncing = True
        self.view_a.set_zoom(1.0, emit_signal=False)
        self.view_b.set_zoom(1.0, emit_signal=False)
        self._syncing = False

    def swap_images(self) -> None:
        replacement = ComparisonDialog(self.path_b, self.path_a, self.parent())
        replacement.show()
        self.close()





class ExperimentDialog(QDialog):
    """Compare generations in one directory that share an identical positive prompt."""

    def __init__(self, path_a: Path, experiment_paths: list[Path], parent=None) -> None:
        super().__init__(parent)
        self.path_a = path_a
        self.experiment_paths = experiment_paths
        self.path_b = next((path for path in experiment_paths if path != path_a), path_a)
        self.metadata_a = read_image_metadata(path_a)
        self.summary_a = extract_summary(self.metadata_a)
        self.metadata_b: dict[str, Any] = {}
        self.summary_b: dict[str, str] = {}
        self._syncing = False

        self.setWindowTitle(f"Experiment View — {len(experiment_paths)} images")
        self.resize(1550, 980)

        self.view_a = CompareImageView(path_a)
        self.view_b = CompareImageView(self.path_b)
        self.label_a = QLabel()
        self.label_b = QLabel()
        self.label_a.setTextFormat(Qt.TextFormat.RichText)
        self.label_b.setTextFormat(Qt.TextFormat.RichText)
        self.link_checkbox = QCheckBox("Link zoom and pan")
        self.link_checkbox.setChecked(True)

        self.view_a.zoom_changed.connect(lambda z: self._sync_zoom(self.view_b, z))
        self.view_b.zoom_changed.connect(lambda z: self._sync_zoom(self.view_a, z))
        self.view_a.pan_changed.connect(lambda x, y: self._sync_pan(self.view_b, x, y))
        self.view_b.pan_changed.connect(lambda x, y: self._sync_pan(self.view_a, x, y))

        image_splitter = QSplitter(Qt.Orientation.Horizontal)
        image_splitter.addWidget(self._image_column(self.label_a, self.view_a))
        image_splitter.addWidget(self._image_column(self.label_b, self.view_b))
        image_splitter.setSizes([775, 775])
        image_splitter.splitterMoved.connect(lambda _p, _i: QTimer.singleShot(0, self.fit_both))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Field", "Image A", "Image B"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.prompt_a = QPlainTextEdit(self.summary_a["positive"])
        self.prompt_b = QPlainTextEdit()
        for editor in (self.prompt_a, self.prompt_b):
            editor.setReadOnly(True)
            editor.setMinimumHeight(100)
        prompt_splitter = QSplitter(Qt.Orientation.Horizontal)
        prompt_splitter.addWidget(self._prompt_column("Positive prompt A", self.prompt_a))
        prompt_splitter.addWidget(self._prompt_column("Positive prompt B", self.prompt_b))

        self.lora_table_a = ComparisonDialog._create_lora_table()
        self.lora_table_b = ComparisonDialog._create_lora_table()
        lora_splitter = QSplitter(Qt.Orientation.Horizontal)
        lora_splitter.addWidget(ComparisonDialog._lora_column("LoRAs used by Image A", self.lora_table_a))
        lora_splitter.addWidget(ComparisonDialog._lora_column("LoRAs used by Image B", self.lora_table_b))
        lora_splitter.setSizes([775, 775])

        tabs = QTabWidget()
        tabs.addTab(self.table, "Parameters")
        tabs.addTab(prompt_splitter, "Positive prompts")
        tabs.addTab(lora_splitter, "LoRAs")

        comparison_splitter = QSplitter(Qt.Orientation.Vertical)
        comparison_splitter.addWidget(image_splitter)
        comparison_splitter.addWidget(tabs)
        comparison_splitter.setSizes([570, 260])

        self.filmstrip = QListWidget()
        self.filmstrip.setViewMode(QListWidget.ViewMode.IconMode)
        self.filmstrip.setFlow(QListWidget.Flow.LeftToRight)
        self.filmstrip.setWrapping(False)
        self.filmstrip.setIconSize(QSize(120, 120))
        self.filmstrip.setGridSize(QSize(145, 155))
        self.filmstrip.setFixedHeight(180)
        self.filmstrip.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.filmstrip.currentItemChanged.connect(self._filmstrip_selection_changed)
        self._populate_filmstrip()

        fit_button = QPushButton("Fit Both")
        fit_button.clicked.connect(self.fit_both)
        actual_button = QPushButton("100%")
        actual_button.clicked.connect(self.actual_both)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        controls = QHBoxLayout()
        controls.addWidget(self.link_checkbox)
        controls.addWidget(fit_button)
        controls.addWidget(actual_button)
        controls.addStretch(1)
        controls.addWidget(QLabel(f"{len(experiment_paths)} images with identical positive prompt"))
        controls.addWidget(close_buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(comparison_splitter, 1)
        layout.addLayout(controls)
        layout.addWidget(QLabel("<b>Experiment filmstrip</b> — choose Image B"))
        layout.addWidget(self.filmstrip)

        self._set_b_image(self.path_b)
        QTimer.singleShot(0, self.fit_both)

    @staticmethod
    def _image_column(label: QLabel, view: CompareImageView) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(label)
        layout.addWidget(view, 1)
        return widget

    @staticmethod
    def _prompt_column(title: str, editor: QPlainTextEdit) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        layout.addWidget(editor)
        return widget

    def _populate_filmstrip(self) -> None:
        selected_item = None
        for path in self.experiment_paths:
            item = QListWidgetItem(path.name)
            item.setData(PATH_ROLE, str(path))
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap.scaled(
                    self.filmstrip.iconSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )))
            item.setToolTip(str(path))
            if path == self.path_a:
                item.setText(f"A: {path.name}")
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.filmstrip.addItem(item)
            if path == self.path_b:
                selected_item = item
        if selected_item is not None:
            self.filmstrip.setCurrentItem(selected_item)

    def _filmstrip_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        value = current.data(PATH_ROLE)
        if isinstance(value, str):
            self._set_b_image(Path(value))

    def _set_b_image(self, path: Path) -> None:
        self.path_b = path
        self.metadata_b = read_image_metadata(path)
        self.summary_b = extract_summary(self.metadata_b)
        self.view_b.set_image(path)
        self.label_a.setText(f"<b>Image A</b> — {self.path_a.name}")
        self.label_b.setText(f"<b>Image B</b> — {self.path_b.name}")
        self.setWindowTitle(f"Experiment View — {self.path_a.name} / {self.path_b.name}")
        self.prompt_b.setPlainText(self.summary_b["positive"])
        self._populate_parameter_table()
        self._populate_lora_tables()
        QTimer.singleShot(0, self.fit_both)

    def _populate_parameter_table(self) -> None:
        fields = [
            ("Filename", self.path_a.name, self.path_b.name),
            ("Model", self.summary_a["model"], self.summary_b["model"]),
            ("Seed", self.summary_a["seed"], self.summary_b["seed"]),
            ("Steps", self.summary_a["steps"], self.summary_b["steps"]),
            ("CFG", self.summary_a["cfg"], self.summary_b["cfg"]),
            ("Sampler", self.summary_a["sampler"], self.summary_b["sampler"]),
            ("Scheduler", self.summary_a["scheduler"], self.summary_b["scheduler"]),
            ("Denoise", self.summary_a["denoise"], self.summary_b["denoise"]),
            ("Resolution", ComparisonDialog._resolution(self.path_a), ComparisonDialog._resolution(self.path_b)),
        ]
        self.table.setRowCount(len(fields))
        difference_brush = QBrush(QColor(58, 79, 102))
        foreground = QBrush(QColor(255, 255, 255))
        for row, (field, a, b) in enumerate(fields):
            for column, value in enumerate((field, a or "—", b or "—")):
                item = QTableWidgetItem(str(value))
                if column in (1, 2) and str(a) != str(b):
                    item.setBackground(difference_brush)
                    item.setForeground(foreground)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()

    def _populate_lora_tables(self) -> None:
        loras_a = {item["name"]: item for item in extract_loras(self.metadata_a)}
        loras_b = {item["name"]: item for item in extract_loras(self.metadata_b)}
        names = sorted(set(loras_a) | set(loras_b), key=str.casefold)
        self.lora_table_a.clearSpans()
        self.lora_table_b.clearSpans()
        self.lora_table_a.setRowCount(len(names))
        self.lora_table_b.setRowCount(len(names))
        difference_brush = QBrush(QColor(58, 79, 102))
        missing_brush = QBrush(QColor(92, 52, 52))
        foreground = QBrush(QColor(255, 255, 255))
        for row, name in enumerate(names):
            item_a = loras_a.get(name)
            item_b = loras_b.get(name)
            values_a = (name if item_a else f"{name} (not used)", item_a["model_strength"] if item_a else "—", item_a["clip_strength"] if item_a else "—")
            values_b = (name if item_b else f"{name} (not used)", item_b["model_strength"] if item_b else "—", item_b["clip_strength"] if item_b else "—")
            differs = item_a != item_b
            for table, values, present in ((self.lora_table_a, values_a, item_a is not None), (self.lora_table_b, values_b, item_b is not None)):
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column in (1, 2):
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if not present:
                        cell.setBackground(missing_brush)
                        cell.setForeground(foreground)
                    elif differs:
                        cell.setBackground(difference_brush)
                        cell.setForeground(foreground)
                    table.setItem(row, column, cell)
        if not names:
            for table in (self.lora_table_a, self.lora_table_b):
                table.setRowCount(1)
                table.setSpan(0, 0, 1, 3)
                cell = QTableWidgetItem("No LoRAs detected")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(0, 0, cell)
        self.lora_table_a.resizeRowsToContents()
        self.lora_table_b.resizeRowsToContents()

    def _sync_zoom(self, target: CompareImageView, factor: float) -> None:
        if not self.link_checkbox.isChecked() or self._syncing:
            return
        self._syncing = True
        target.set_zoom(factor, emit_signal=False)
        self._syncing = False

    def _sync_pan(self, target: CompareImageView, x: float, y: float) -> None:
        if not self.link_checkbox.isChecked() or self._syncing:
            return
        self._syncing = True
        target.set_normalized_pan(x, y)
        self._syncing = False

    def fit_both(self) -> None:
        self._syncing = True
        self.view_a.fit_to_view()
        self.view_b.fit_to_view()
        self._syncing = False

    def actual_both(self) -> None:
        self._syncing = True
        self.view_a.set_zoom(1.0, emit_signal=False)
        self.view_b.set_zoom(1.0, emit_signal=False)
        self._syncing = False



def image_resolution(path: Path) -> tuple[int, int] | None:
    """Return an image's pixel dimensions without fully decoding it."""
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError):
        return None


def normalised_prompt(value: str) -> str:
    """Normalise insignificant prompt whitespace for exact comparisons."""
    return " ".join(value.split()).casefold()


def lora_signature(metadata: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    """Return a stable, order-independent LoRA signature."""
    entries = []
    for lora in extract_loras(metadata):
        entries.append(
            (
                lora.get("name", "").strip().casefold(),
                lora.get("model_strength", "").strip(),
                lora.get("clip_strength", "").strip(),
            )
        )
    return tuple(sorted(entries))


class SimilaritySearchDialog(QDialog):
    """Choose the metadata fields used to find images similar to a reference."""

    def __init__(self, reference_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find Similar Images")
        self.setMinimumWidth(390)

        intro = QLabel(
            f"Find images in the current folder matching:\n"
            f"<b>{reference_path.name}</b>"
        )
        intro.setWordWrap(True)

        self.model_box = QCheckBox("Checkpoint / model")
        self.loras_box = QCheckBox("LoRA list and strengths")
        self.seed_box = QCheckBox("Seed")
        self.prompt_box = QCheckBox("Positive prompt")
        self.sampler_box = QCheckBox("Sampler")
        self.scheduler_box = QCheckBox("Scheduler")
        self.resolution_box = QCheckBox("Image resolution")

        for box in (
            self.model_box,
            self.loras_box,
            self.sampler_box,
            self.scheduler_box,
        ):
            box.setChecked(True)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(6)
        for box in (
            self.model_box,
            self.loras_box,
            self.seed_box,
            self.prompt_box,
            self.sampler_box,
            self.scheduler_box,
            self.resolution_box,
        ):
            layout.addWidget(box)

        note = QLabel(
            "All selected fields must match. LoRA matching includes model and "
            "CLIP strengths, but ignores their order in the workflow."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addSpacing(6)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Find Similar")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def criteria(self) -> dict[str, bool]:
        return {
            "model": self.model_box.isChecked(),
            "loras": self.loras_box.isChecked(),
            "seed": self.seed_box.isChecked(),
            "prompt": self.prompt_box.isChecked(),
            "sampler": self.sampler_box.isChecked(),
            "scheduler": self.scheduler_box.isChecked(),
            "resolution": self.resolution_box.isChecked(),
        }

    def _validate_and_accept(self) -> None:
        if not any(self.criteria().values()):
            QMessageBox.information(
                self,
                "Choose matching fields",
                "Select at least one field to compare.",
            )
            return
        self.accept()



def ratings_database_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "image_ratings.sqlite3"


class ImageRatingsDatabase:
    """Persistent 0–5 image ratings, stored without modifying image files."""

    def __init__(self) -> None:
        self.path = ratings_database_path()
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS image_ratings (
                image_path TEXT PRIMARY KEY,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 0 AND 5),
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def key(path: Path | str) -> str:
        return str(Path(path).expanduser().resolve(strict=False))

    def get(self, path: Path | str) -> int:
        row = self.connection.execute(
            "SELECT rating FROM image_ratings WHERE image_path=?",
            (self.key(path),),
        ).fetchone()
        return int(row[0]) if row else 0

    def set(self, path: Path | str, rating: int) -> None:
        value = max(0, min(5, int(rating)))
        key = self.key(path)
        if value == 0:
            self.connection.execute("DELETE FROM image_ratings WHERE image_path=?", (key,))
        else:
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            self.connection.execute(
                """
                INSERT INTO image_ratings(image_path, rating, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(image_path) DO UPDATE SET rating=excluded.rating, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )
        self.connection.commit()


def rating_text(rating: int) -> str:
    value = max(0, min(5, int(rating)))
    return "★" * value + "☆" * (5 - value)


def prompt_library_database_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "prompt_library.sqlite3"


class PromptLibraryDatabase:
    def __init__(self) -> None:
        self.path = prompt_library_database_path()
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                positive_prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                source_image TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                loras_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def add(self, values: dict[str, str]) -> int:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            """
            INSERT INTO prompts (
                title, description, tags, positive_prompt, negative_prompt,
                source_image, model, loras_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["title"], values["description"], values["tags"],
                values["positive_prompt"], values["negative_prompt"],
                values["source_image"], values["model"], values["loras_json"],
                now, now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update(self, prompt_id: int, values: dict[str, str]) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        self.connection.execute(
            """
            UPDATE prompts SET title=?, description=?, tags=?, positive_prompt=?,
                negative_prompt=?, source_image=?, model=?, loras_json=?, updated_at=?
            WHERE id=?
            """,
            (
                values["title"], values["description"], values["tags"],
                values["positive_prompt"], values["negative_prompt"],
                values["source_image"], values["model"], values["loras_json"],
                now, prompt_id,
            ),
        )
        self.connection.commit()

    def delete(self, prompt_id: int) -> None:
        self.connection.execute("DELETE FROM prompts WHERE id=?", (prompt_id,))
        self.connection.commit()

    def get(self, prompt_id: int) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()

    def search(self, text: str = "") -> list[sqlite3.Row]:
        term = text.strip()
        if not term:
            return list(self.connection.execute("SELECT * FROM prompts ORDER BY updated_at DESC, id DESC"))
        pattern = f"%{term}%"
        return list(self.connection.execute(
            """
            SELECT * FROM prompts
            WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?
               OR positive_prompt LIKE ? OR negative_prompt LIKE ? OR model LIKE ?
            ORDER BY updated_at DESC, id DESC
            """,
            (pattern, pattern, pattern, pattern, pattern, pattern),
        ))


class PromptEntryDialog(QDialog):
    def __init__(self, values: dict[str, str], parent: QWidget | None = None, editing: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Library Prompt" if editing else "Save Prompt to Library")
        self.resize(760, 690)

        self.title_edit = QLineEdit(values.get("title", ""))
        self.title_edit.setPlaceholderText("A memorable prompt name")
        self.tags_edit = QLineEdit(values.get("tags", ""))
        self.tags_edit.setPlaceholderText("Comma-separated tags, e.g. portrait, lighting, beach")
        self.description_edit = QPlainTextEdit(values.get("description", ""))
        self.description_edit.setPlaceholderText("Optional notes about how or when to use this prompt")
        self.description_edit.setMaximumHeight(90)
        self.positive_edit = QPlainTextEdit(values.get("positive_prompt", ""))
        self.negative_edit = QPlainTextEdit(values.get("negative_prompt", ""))

        self.source_image = values.get("source_image", "")
        self.model = values.get("model", "")
        self.loras_json = values.get("loras_json", "[]")

        source_label = QLabel(self.source_image or "No originating image")
        source_label.setWordWrap(True)
        source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        model_label = QLabel(self.model or "Unknown")
        model_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("Title:", self.title_edit)
        form.addRow("Tags:", self.tags_edit)
        form.addRow("Description:", self.description_edit)
        form.addRow("Positive prompt:", self.positive_edit)
        form.addRow("Negative prompt:", self.negative_edit)
        form.addRow("Originating image:", source_label)
        form.addRow("Checkpoint/model:", model_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def validate_and_accept(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.information(self, "Title required", "Enter a title for the library prompt.")
            self.title_edit.setFocus()
            return
        if not self.positive_edit.toPlainText().strip() and not self.negative_edit.toPlainText().strip():
            QMessageBox.information(self, "Prompt required", "The entry must contain a positive or negative prompt.")
            return
        self.accept()

    def values(self) -> dict[str, str]:
        return {
            "title": self.title_edit.text().strip(),
            "tags": self.tags_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "positive_prompt": self.positive_edit.toPlainText().strip(),
            "negative_prompt": self.negative_edit.toPlainText().strip(),
            "source_image": self.source_image,
            "model": self.model,
            "loras_json": self.loras_json,
        }


class PromptLibraryDialog(QDialog):
    def __init__(self, database: PromptLibraryDatabase, open_image_callback, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.open_image_callback = open_image_callback
        self.setWindowTitle("Prompt Library")
        self.resize(1100, 760)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search titles, tags, prompts, notes, or models…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Title", "Tags", "Model", "Created", "Originating image"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.itemDoubleClicked.connect(lambda _item: self.copy_positive_prompt())

        self.details_tabs = QTabWidget()
        self.positive_view = QPlainTextEdit(); self.positive_view.setReadOnly(True)
        self.negative_view = QPlainTextEdit(); self.negative_view.setReadOnly(True)
        self.notes_view = QPlainTextEdit(); self.notes_view.setReadOnly(True)
        self.details_tabs.addTab(self.positive_view, "Positive prompt")
        self.details_tabs.addTab(self.negative_view, "Negative prompt")
        self.details_tabs.addTab(self.notes_view, "Notes and metadata")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.details_tabs)
        splitter.setSizes([390, 270])

        copy_positive = QPushButton("Copy Positive Prompt")
        copy_positive.clicked.connect(self.copy_positive_prompt)
        copy_negative = QPushButton("Copy Negative Prompt")
        copy_negative.clicked.connect(self.copy_negative_prompt)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self.edit_selected)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected)
        open_button = QPushButton("Open Originating Image")
        open_button.clicked.connect(self.open_originating_image)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(copy_positive)
        buttons.addWidget(copy_negative)
        buttons.addWidget(edit_button)
        buttons.addWidget(delete_button)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_edit)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        self.refresh()

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        value = item.data(PATH_ROLE) if item else None
        return int(value) if value is not None else None

    def selected_record(self) -> sqlite3.Row | None:
        prompt_id = self.selected_id()
        return self.database.get(prompt_id) if prompt_id is not None else None

    def refresh(self) -> None:
        selected_id = self.selected_id()
        records = self.database.search(self.search_edit.text())
        self.table.setRowCount(len(records))
        selected_row = -1
        for row_index, record in enumerate(records):
            title_item = QTableWidgetItem(record["title"])
            title_item.setData(PATH_ROLE, record["id"])
            self.table.setItem(row_index, 0, title_item)
            self.table.setItem(row_index, 1, QTableWidgetItem(record["tags"]))
            self.table.setItem(row_index, 2, QTableWidgetItem(model_display_name(record["model"])))
            created = record["created_at"].replace("T", " ")[:16]
            self.table.setItem(row_index, 3, QTableWidgetItem(created))
            self.table.setItem(row_index, 4, QTableWidgetItem(Path(record["source_image"]).name if record["source_image"] else ""))
            if record["id"] == selected_id:
                selected_row = row_index
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        elif records:
            self.table.selectRow(0)
        else:
            self.positive_view.clear(); self.negative_view.clear(); self.notes_view.clear()

    def show_selected(self) -> None:
        record = self.selected_record()
        if record is None:
            return
        self.positive_view.setPlainText(record["positive_prompt"])
        self.negative_view.setPlainText(record["negative_prompt"])
        try:
            loras = json.loads(record["loras_json"])
        except (json.JSONDecodeError, TypeError):
            loras = []
        lora_lines = []
        for entry in loras if isinstance(loras, list) else []:
            if isinstance(entry, dict):
                name = entry.get("name", "")
                model = entry.get("model_strength", "")
                clip = entry.get("clip_strength", "")
                strengths = ", ".join(part for part in (f"model {model}" if model else "", f"CLIP {clip}" if clip else "") if part)
                lora_lines.append(f"{name}" + (f" ({strengths})" if strengths else ""))
        details = [record["description"]]
        if record["tags"]: details.extend(["", f"Tags: {record['tags']}"])
        if record["model"]: details.append(f"Model: {record['model']}")
        if lora_lines: details.extend(["", "LoRAs:", *lora_lines])
        if record["source_image"]: details.extend(["", f"Originating image: {record['source_image']}"])
        self.notes_view.setPlainText("\n".join(details).strip())

    def copy_text(self, field: str, label: str) -> None:
        record = self.selected_record()
        if record is None:
            return
        text = record[field]
        if not text:
            QMessageBox.information(self, "Nothing to copy", f"This entry has no {label.lower()}.")
            return
        QApplication.clipboard().setText(text)
        parent = self.parentWidget()
        if isinstance(parent, QMainWindow):
            parent.statusBar().showMessage(f"{label} copied to clipboard", 3000)

    def copy_positive_prompt(self) -> None:
        self.copy_text("positive_prompt", "Positive prompt")

    def copy_negative_prompt(self) -> None:
        self.copy_text("negative_prompt", "Negative prompt")

    def edit_selected(self) -> None:
        record = self.selected_record()
        if record is None:
            return
        values = {key: str(record[key]) for key in (
            "title", "description", "tags", "positive_prompt", "negative_prompt",
            "source_image", "model", "loras_json",
        )}
        dialog = PromptEntryDialog(values, self, editing=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.database.update(int(record["id"]), dialog.values())
            self.refresh()

    def delete_selected(self) -> None:
        record = self.selected_record()
        if record is None:
            return
        answer = QMessageBox.question(self, "Delete library prompt", f"Delete “{record['title']}” from the prompt library?")
        if answer == QMessageBox.StandardButton.Yes:
            self.database.delete(int(record["id"]))
            self.refresh()

    def open_originating_image(self) -> None:
        record = self.selected_record()
        if record is None or not record["source_image"]:
            QMessageBox.information(self, "No originating image", "This library entry has no originating image path.")
            return
        path = Path(record["source_image"])
        if not path.is_file():
            QMessageBox.warning(self, "Image not found", f"The originating image no longer exists:\n{path}")
            return
        self.open_image_callback(path)


