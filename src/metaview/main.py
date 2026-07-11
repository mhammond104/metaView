#!/usr/bin/env python3
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



def parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def read_image_metadata(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            metadata = dict(image.info)
    except (OSError, UnidentifiedImageError):
        return {}

    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        result[key] = parse_json_value(value)
    return result


def resolve_node(prompt: dict[str, Any], link: Any) -> dict[str, Any] | None:
    if not isinstance(link, list) or not link:
        return None
    node = prompt.get(str(link[0]))
    return node if isinstance(node, dict) else None


def node_text(
    prompt: dict[str, Any],
    node: dict[str, Any] | None,
    visited: set[str] | None = None,
) -> str:
    if not node:
        return ""
    if visited is None:
        visited = set()

    node_key = str(id(node))
    if node_key in visited:
        return ""
    visited.add(node_key)

    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return ""

    for key in (
        "text", "prompt", "positive", "negative", "string", "value",
        "text_a", "text_b",
    ):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            text = node_text(prompt, resolve_node(prompt, value), visited)
            if text:
                return text
    return ""


def find_sampler(prompt: dict[str, Any]) -> dict[str, Any] | None:
    preferred = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}
    for node in prompt.values():
        if isinstance(node, dict) and node.get("class_type") in preferred:
            return node
    for node in prompt.values():
        if isinstance(node, dict) and "sampler" in str(node.get("class_type", "")).lower():
            return node
    return None


def find_model(prompt: dict[str, Any]) -> str:
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for key in ("ckpt_name", "unet_name", "model_name", "checkpoint"):
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def extract_summary(metadata: dict[str, Any]) -> dict[str, str]:
    empty = {
        "positive": "", "negative": "", "model": "", "seed": "",
        "steps": "", "cfg": "", "sampler": "", "scheduler": "",
        "denoise": "",
    }
    prompt = parse_json_value(metadata.get("prompt"))
    if not isinstance(prompt, dict):
        return empty

    sampler = find_sampler(prompt)
    inputs = sampler.get("inputs", {}) if isinstance(sampler, dict) else {}
    if not isinstance(inputs, dict):
        inputs = {}

    def simple_value(*keys: str) -> str:
        for key in keys:
            value = inputs.get(key)
            if value is not None and not isinstance(value, list):
                return str(value)
        return ""

    return {
        "positive": node_text(prompt, resolve_node(prompt, inputs.get("positive"))),
        "negative": node_text(prompt, resolve_node(prompt, inputs.get("negative"))),
        "model": find_model(prompt),
        "seed": simple_value("seed", "noise_seed"),
        "steps": simple_value("steps"),
        "cfg": simple_value("cfg", "cfg_scale"),
        "sampler": simple_value("sampler_name", "sampler"),
        "scheduler": simple_value("scheduler"),
        "denoise": simple_value("denoise"),
    }


def _format_strength(value: Any) -> str:
    """Format a LoRA strength without unnecessary trailing zeroes."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _looks_like_lora_filename(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.casefold()
    return (
        "lora" in lowered
        or lowered.endswith((".safetensors", ".ckpt", ".pt", ".pth"))
    )


def extract_loras(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """
    Extract LoRA names and strengths from common ComfyUI prompt nodes.

    Handles standard LoraLoader variants and common custom loaders whose
    inputs contain nested LoRA definitions.
    """
    prompt = parse_json_value(metadata.get("prompt"))
    if not isinstance(prompt, dict):
        return []

    results: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_lora(name: Any, model_strength: Any = None, clip_strength: Any = None) -> None:
        if not isinstance(name, str) or not name.strip():
            return

        clean_name = name.strip()
        model_text = _format_strength(model_strength)
        clip_text = _format_strength(clip_strength)

        key = (clean_name, model_text, clip_text)
        if key in seen:
            return

        seen.add(key)
        results.append(
            {
                "name": clean_name,
                "model_strength": model_text,
                "clip_strength": clip_text,
            }
        )

    name_keys = (
        "lora_name",
        "lora",
        "lora_file",
        "lora_path",
        "lora_model",
    )
    model_strength_keys = (
        "strength_model",
        "model_strength",
        "strength",
        "weight",
        "lora_strength",
    )
    clip_strength_keys = (
        "strength_clip",
        "clip_strength",
    )

    def first_scalar(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = mapping.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return value
        return None

    def inspect_nested(value: Any) -> None:
        if isinstance(value, dict):
            enabled = value.get("on", value.get("enabled", value.get("active", True)))
            if enabled is False:
                return

            name = first_scalar(value, name_keys + ("name", "filename",))
            if _looks_like_lora_filename(name):
                add_lora(
                    name,
                    first_scalar(value, model_strength_keys),
                    first_scalar(value, clip_strength_keys),
                )

            for nested_value in value.values():
                inspect_nested(nested_value)

        elif isinstance(value, list):
            for nested_value in value:
                inspect_nested(nested_value)

    for node in prompt.values():
        if not isinstance(node, dict):
            continue

        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue

        class_is_lora = "lora" in class_type.casefold()

        direct_name = first_scalar(inputs, name_keys)
        if class_is_lora and isinstance(direct_name, str):
            add_lora(
                direct_name,
                first_scalar(inputs, model_strength_keys),
                first_scalar(inputs, clip_strength_keys),
            )

        # Custom loaders often store one or more LoRAs inside nested mappings
        # such as lora_1, lora_2, loras, or stack entries.
        if class_is_lora:
            inspect_nested(inputs)
        else:
            for key, value in inputs.items():
                if "lora" in key.casefold():
                    inspect_nested(value)

    return results


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
    loaded = Signal(str, str, str, str, str, int)


class MetadataWorker(QRunnable):
    def __init__(self, path: Path, generation: int) -> None:
        super().__init__()
        self.path = path
        self.generation = generation
        self.signals = MetadataSignals()

    def run(self) -> None:
        metadata = read_image_metadata(self.path)
        summary = extract_summary(metadata)
        model = summary["model"] or UNKNOWN_MODEL
        sampler = summary["sampler"] or UNKNOWN_SAMPLER
        scheduler = summary["scheduler"] or UNKNOWN_SCHEDULER
        positive_prompt = summary["positive"]
        self.signals.loaded.emit(
            str(self.path), model, sampler, scheduler,
            positive_prompt, self.generation
        )


class ImageDragListWidget(QListWidget):
    """Thumbnail list that drags the original image file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return

        path_value = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path_value, str):
            return

        image_path = Path(path_value)
        if not image_path.is_file():
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(image_path))])
        mime_data.setText(str(image_path))

        drag = QDrag(self)
        drag.setMimeData(mime_data)

        icon = item.icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(self.iconSize()))

        drag.exec(Qt.DropAction.CopyAction)


class WorkflowDragIcon(QLabel):
    """Draggable JSON-document icon for the selected image workflow."""

    def __init__(self, workflow_exporter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workflow_exporter = workflow_exporter
        self.image_path: Path | None = None
        self.drag_start_position = QPoint()

        self.setFixedSize(54, 62)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(self._create_icon_pixmap(False))
        self.setEnabled(False)
        self.setToolTip("No embedded workflow available")

    @staticmethod
    def _create_icon_pixmap(enabled: bool) -> QPixmap:
        pixmap = QPixmap(44, 52)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outline = QColor(65, 105, 170) if enabled else QColor(135, 135, 135)
        fill = QColor(245, 248, 255) if enabled else QColor(230, 230, 230)
        text_colour = QColor(40, 75, 135) if enabled else QColor(130, 130, 130)

        painter.setPen(QPen(outline, 2))
        painter.setBrush(fill)

        # Document body with folded top-right corner.
        points = [
            QPoint(6, 2),
            QPoint(29, 2),
            QPoint(39, 12),
            QPoint(39, 49),
            QPoint(6, 49),
        ]
        polygon = QPolygon(points)
        painter.drawPolygon(polygon)
        painter.drawLine(29, 2, 29, 12)
        painter.drawLine(29, 12, 39, 12)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(16)
        painter.setFont(font)
        painter.setPen(text_colour)
        painter.drawText(
            pixmap.rect().adjusted(2, 12, -2, -2),
            Qt.AlignmentFlag.AlignCenter,
            "{}",
        )

        painter.end()
        return pixmap

    def set_workflow_source(self, image_path: Path | None, available: bool) -> None:
        self.image_path = image_path if available else None
        self.setEnabled(available)
        self.setPixmap(self._create_icon_pixmap(available))
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if available
            else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(
            "Drag workflow JSON into ComfyUI"
            if available
            else "No embedded workflow available"
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.drag_start_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self.isEnabled() or self.image_path is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (
            event.position().toPoint() - self.drag_start_position
        ).manhattanLength() < QApplication.startDragDistance():
            return

        workflow_path = self.workflow_exporter(self.image_path, show_errors=True)
        if workflow_path is None:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(workflow_path))])
        mime_data.setText(str(workflow_path))

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        if self.pixmap() is not None:
            drag.setPixmap(self.pixmap())
        drag.exec(Qt.DropAction.CopyAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self.isEnabled():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class CopyableValue(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setFixedWidth(56)
        self.copy_button.clicked.connect(self.copy_value)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.copy_button)

    def setText(self, text: str) -> None:
        self.label.setText(text)
        self.copy_button.setEnabled(bool(text))

    def clear(self) -> None:
        self.setText("")

    def copy_value(self) -> None:
        QApplication.clipboard().setText(self.label.text())


class PromptBox(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 600;")

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setMinimumHeight(100)

        copy_button = QPushButton("Copy")
        copy_button.setFixedWidth(56)
        copy_button.clicked.connect(self.copy_text)

        heading = QHBoxLayout()
        heading.addWidget(title_label)
        heading.addStretch(1)
        heading.addWidget(copy_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(heading)
        layout.addWidget(self.editor)

    def setPlainText(self, text: str) -> None:
        self.editor.setPlainText(text)

    def clear(self) -> None:
        self.editor.clear()

    def copy_text(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())


class MetadataPanel(QWidget):
    def __init__(self, workflow_exporter) -> None:
        super().__init__()
        self.fields: dict[str, CopyableValue] = {}

        parameters_contents = QWidget()
        parameters_layout_outer = QVBoxLayout(parameters_contents)
        parameters_layout_outer.setContentsMargins(8, 8, 4, 8)
        parameters_layout_outer.setSpacing(8)

        parameters_frame = QFrame()
        parameters_frame.setFrameShape(QFrame.Shape.StyledPanel)
        parameters_layout = QFormLayout(parameters_frame)
        parameters_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        for key, text in (
            ("filename", "Filename"),
            ("model", "Model"),
            ("seed", "Seed"),
            ("steps", "Steps"),
            ("cfg", "CFG"),
            ("sampler", "Sampler"),
            ("scheduler", "Scheduler"),
            ("denoise", "Denoise"),
        ):
            value = CopyableValue()
            self.fields[key] = value
            parameters_layout.addRow(f"{text}:", value)

        workflow_frame = QFrame()
        workflow_frame.setFrameShape(QFrame.Shape.StyledPanel)
        workflow_layout = QHBoxLayout(workflow_frame)
        workflow_layout.setContentsMargins(8, 6, 8, 6)
        workflow_label = QLabel("Workflow JSON")
        workflow_label.setStyleSheet("font-weight: 600;")
        self.workflow_drag_icon = WorkflowDragIcon(workflow_exporter)
        workflow_layout.addWidget(workflow_label)
        workflow_layout.addStretch(1)
        workflow_layout.addWidget(self.workflow_drag_icon)

        parameters_layout_outer.addWidget(parameters_frame)
        parameters_layout_outer.addWidget(workflow_frame)
        parameters_layout_outer.addStretch(1)

        parameters_scroll = QScrollArea()
        parameters_scroll.setWidgetResizable(True)
        parameters_scroll.setFrameShape(QFrame.Shape.NoFrame)
        parameters_scroll.setWidget(parameters_contents)

        self.positive_prompt = PromptBox("Positive prompt")
        self.negative_prompt = PromptBox("Negative prompt")

        prompts_contents = QWidget()
        prompts_layout = QVBoxLayout(prompts_contents)
        prompts_layout.setContentsMargins(4, 8, 8, 8)
        prompts_layout.setSpacing(8)
        prompts_layout.addWidget(self.positive_prompt, 1)
        prompts_layout.addWidget(self.negative_prompt, 1)

        self.summary_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.summary_splitter.addWidget(parameters_scroll)
        self.summary_splitter.addWidget(prompts_contents)
        self.summary_splitter.setSizes([360, 640])
        self.summary_splitter.setStretchFactor(0, 0)
        self.summary_splitter.setStretchFactor(1, 1)

        self.lora_table = QTableWidget(0, 3)
        self.lora_table.setHorizontalHeaderLabels(
            ["LoRA", "Model strength", "CLIP strength"]
        )
        self.lora_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.lora_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.lora_table.setAlternatingRowColors(True)
        self.lora_table.verticalHeader().setVisible(False)
        self.lora_table.horizontalHeader().setStretchLastSection(False)
        self.lora_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.lora_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.lora_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )

        self.lora_empty_label = QLabel(
            "No LoRAs detected in this image's ComfyUI metadata."
        )
        self.lora_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lora_empty_label.setWordWrap(True)

        self.lora_stack = QStackedWidget()
        self.lora_stack.addWidget(self.lora_empty_label)
        self.lora_stack.addWidget(self.lora_table)

        self.prompt_json = QPlainTextEdit()
        self.workflow_json = QPlainTextEdit()
        self.raw_metadata = QPlainTextEdit()
        for editor in (self.prompt_json, self.workflow_json, self.raw_metadata):
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.summary_splitter, "Summary")
        self.tabs.addTab(self.lora_stack, "LoRAs")
        self.tabs.addTab(self.prompt_json, "Prompt JSON")
        self.tabs.addTab(self.workflow_json, "Workflow JSON")
        self.tabs.addTab(self.raw_metadata, "All metadata")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

    def clear(self) -> None:
        for field in self.fields.values():
            field.clear()
        self.positive_prompt.clear()
        self.negative_prompt.clear()
        self.lora_table.setRowCount(0)
        self.lora_stack.setCurrentWidget(self.lora_empty_label)
        self.prompt_json.clear()
        self.workflow_json.clear()
        self.raw_metadata.clear()
        self.workflow_drag_icon.set_workflow_source(None, False)

    def show_metadata(self, path: Path, metadata: dict[str, Any]) -> None:
        summary = extract_summary(metadata)
        self.fields["filename"].setText(path.name)
        for key in ("model", "seed", "steps", "cfg", "sampler", "scheduler", "denoise"):
            self.fields[key].setText(summary[key])
        self.positive_prompt.setPlainText(summary["positive"])
        self.negative_prompt.setPlainText(summary["negative"])

        loras = extract_loras(metadata)
        self.lora_table.setRowCount(len(loras))
        for row, lora in enumerate(loras):
            name_item = QTableWidgetItem(lora["name"])
            name_item.setToolTip(lora["name"])
            model_item = QTableWidgetItem(lora["model_strength"])
            clip_item = QTableWidgetItem(lora["clip_strength"])

            model_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            clip_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.lora_table.setItem(row, 0, name_item)
            self.lora_table.setItem(row, 1, model_item)
            self.lora_table.setItem(row, 2, clip_item)

        self.lora_stack.setCurrentWidget(
            self.lora_table if loras else self.lora_empty_label
        )

        self.prompt_json.setPlainText(display_json(metadata.get("prompt")))
        self.workflow_json.setPlainText(display_json(metadata.get("workflow")))
        self.raw_metadata.setPlainText(display_json(metadata))
        workflow = parse_json_value(metadata.get("workflow"))
        self.workflow_drag_icon.set_workflow_source(
            path, isinstance(workflow, (dict, list))
        )



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


class MainWindow(QMainWindow):
    PREFETCH_ROWS = 2

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("Martin Hammond", "ComfyUI Image Browser")
        self.current_directory: Path | None = None
        self.current_pixmap: QPixmap | None = None
        self.current_image_path: Path | None = None
        self.current_metadata: dict[str, Any] = {}
        self.thumbnail_generation = 0
        self.thumbnail_items: dict[str, QListWidgetItem] = {}
        self.model_buttons: dict[str, QToolButton] = {}
        self.sampler_buttons: dict[str, QToolButton] = {}
        self.scheduler_buttons: dict[str, QToolButton] = {}
        self.active_model = "All"
        self.active_sampler = "All"
        self.active_scheduler = "All"
        self.cache_hits = 0
        self.generated_thumbnails = 0
        self.thread_pool = QThreadPool.globalInstance()
        self.pending_filter_restore: dict[str, str] = {}
        self.pending_selection_restore: set[str] = set()
        self.similarity_matches: set[str] | None = None
        self.similarity_reference: Path | None = None
        self.similarity_criteria: dict[str, bool] = {}
        self.prompt_library_database = PromptLibraryDatabase()
        self.ratings_database = ImageRatingsDatabase()
        self.active_rating_filter = "all"

        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.directoryChanged.connect(self.directory_contents_changed)

        self.watcher_refresh_timer = QTimer(self)
        self.watcher_refresh_timer.setSingleShot(True)
        self.watcher_refresh_timer.setInterval(500)
        self.watcher_refresh_timer.timeout.connect(self.refresh_from_watcher)

        self.lazy_load_timer = QTimer(self)
        self.lazy_load_timer.setSingleShot(True)
        self.lazy_load_timer.setInterval(60)
        self.lazy_load_timer.timeout.connect(self.queue_visible_thumbnails)

        self.setWindowTitle("metaView GenAI Metadata Viewer")
        self.setWindowIcon(QApplication.instance().windowIcon())
        self.resize(1500, 900)
        self.create_directory_tree()
        self.create_thumbnail_list()
        self.create_preview()
        self.create_layout()
        self.create_toolbar()
        self.restore_settings()
        self.statusBar().showMessage("Ready")

    def create_directory_tree(self) -> None:
        self.file_model = QFileSystemModel(self)
        self.file_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.file_model.setRootPath("")
        self.directory_tree = QTreeView()
        self.directory_tree.setModel(self.file_model)
        self.directory_tree.setRootIndex(self.file_model.index(str(Path.home())))
        for column in (1, 2, 3):
            self.directory_tree.setColumnHidden(column, True)
        self.directory_tree.setMinimumWidth(220)
        self.directory_tree.clicked.connect(self.directory_selected)

    def create_thumbnail_list(self) -> None:
        self.image_list = ImageDragListWidget()
        self.image_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_list.setIconSize(QSize(180, 180))
        self.image_list.setGridSize(QSize(210, 225))
        self.image_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_list.setMovement(QListWidget.Movement.Static)
        self.image_list.setWordWrap(True)
        self.image_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.image_list.currentItemChanged.connect(self.image_selected)
        self.image_list.itemSelectionChanged.connect(self.update_compare_button)
        self.image_list.verticalScrollBar().valueChanged.connect(self.schedule_visible_thumbnail_load)
        self.image_list.horizontalScrollBar().valueChanged.connect(self.schedule_visible_thumbnail_load)

        self.filename_search_box = QLineEdit()
        self.filename_search_box.setPlaceholderText("Search filename…")
        self.filename_search_box.setClearButtonEnabled(True)
        self.filename_search_box.textChanged.connect(self.search_changed)

        self.prompt_search_box = QLineEdit()
        self.prompt_search_box.setPlaceholderText("Search positive prompt…")
        self.prompt_search_box.setClearButtonEnabled(True)
        self.prompt_search_box.textChanged.connect(self.search_changed)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Filename (A–Z)", "filename_asc")
        self.sort_combo.addItem("Filename (Z–A)", "filename_desc")
        self.sort_combo.addItem("Newest first", "modified_desc")
        self.sort_combo.addItem("Oldest first", "modified_asc")
        self.sort_combo.addItem("Rating (high to low)", "rating_desc")
        self.sort_combo.addItem("Rating (low to high)", "rating_asc")
        self.sort_combo.setToolTip("Sort images")
        self.sort_combo.currentIndexChanged.connect(self.sort_changed)

        self.rating_filter_combo = QComboBox()
        self.rating_filter_combo.addItem("All ratings", "all")
        self.rating_filter_combo.addItem("Unrated", "unrated")
        self.rating_filter_combo.addItem("1★ or better", "1plus")
        self.rating_filter_combo.addItem("2★ or better", "2plus")
        self.rating_filter_combo.addItem("3★ or better", "3plus")
        self.rating_filter_combo.addItem("4★ or better", "4plus")
        self.rating_filter_combo.addItem("5★ only", "5only")
        self.rating_filter_combo.setToolTip("Filter images by rating")
        self.rating_filter_combo.currentIndexChanged.connect(self.rating_filter_changed)

        (
            self.model_group,
            self.model_filter_layout,
            self.model_filter_scroll,
        ) = self.create_filter_row("model")
        self.model_group.buttonClicked.connect(self.model_filter_clicked)

        (
            self.sampler_group,
            self.sampler_filter_layout,
            self.sampler_filter_scroll,
        ) = self.create_filter_row("sampler")
        self.sampler_group.buttonClicked.connect(self.sampler_filter_clicked)

        (
            self.scheduler_group,
            self.scheduler_filter_layout,
            self.scheduler_filter_scroll,
        ) = self.create_filter_row("scheduler")
        self.scheduler_group.buttonClicked.connect(self.scheduler_filter_clicked)

        self.add_filter_button("model", "All", checked=True)
        self.add_filter_button("sampler", "All", checked=True)
        self.add_filter_button("scheduler", "All", checked=True)

        self.thumbnail_panel = QWidget()
        panel_layout = QVBoxLayout(self.thumbnail_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(2)
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)
        search_layout.addWidget(self.filename_search_box)
        search_layout.addWidget(self.prompt_search_box)
        search_layout.addWidget(QLabel("Sort:"))
        search_layout.addWidget(self.sort_combo)
        search_layout.addWidget(QLabel("Rating:"))
        search_layout.addWidget(self.rating_filter_combo)

        panel_layout.addWidget(search_row)
        panel_layout.addWidget(self.make_filter_labeled_row("Model", self.model_filter_scroll))
        panel_layout.addWidget(self.make_filter_labeled_row("Sampler", self.sampler_filter_scroll))
        panel_layout.addWidget(self.make_filter_labeled_row("Scheduler", self.scheduler_filter_scroll))
        panel_layout.addWidget(self.image_list, 1)

    def create_preview(self) -> None:
        self.preview = QLabel("Select a folder containing images")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(400, 300)
        self.preview.setStyleSheet("QLabel { background: palette(base); border: 1px solid palette(mid); }")
        self.metadata_panel = MetadataPanel(self.export_workflow_for_image)

    def create_layout(self) -> None:
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.addWidget(self.preview)
        self.right_splitter.addWidget(self.metadata_panel)
        self.right_splitter.setSizes([470, 370])
        self.right_splitter.splitterMoved.connect(self._preview_splitter_moved)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.directory_tree)
        self.main_splitter.addWidget(self.thumbnail_panel)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setSizes([260, 540, 700])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 1)
        self.main_splitter.splitterMoved.connect(self._preview_splitter_moved)

        self.find_similar_button = QPushButton("Find Similar")
        self.find_similar_button.setEnabled(False)
        self.find_similar_button.clicked.connect(self.find_similar_images)

        self.experiment_view_button = QPushButton("Experiment View")
        self.experiment_view_button.setEnabled(False)
        self.experiment_view_button.clicked.connect(self.open_experiment_view)

        self.save_prompt_button = QPushButton("Save Prompt")
        self.save_prompt_button.setEnabled(False)
        self.save_prompt_button.clicked.connect(self.save_current_prompt)

        self.prompt_library_button = QPushButton("Prompt Library")
        self.prompt_library_button.clicked.connect(self.open_prompt_library)

        self.clear_similarity_button = QPushButton("Clear Similarity Search")
        self.clear_similarity_button.setVisible(False)
        self.clear_similarity_button.clicked.connect(self.clear_similarity_search)

        self.compare_button = QPushButton("Compare")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self.compare_selected_images)

        self.open_image_button = QPushButton("Open Image")
        self.open_image_button.setEnabled(False)
        self.open_image_button.clicked.connect(self.open_selected_image)

        self.rating_label = QLabel("Rating:")
        self.rating_buttons: list[QToolButton] = []
        for rating in range(1, 6):
            button = QToolButton()
            button.setText("☆")
            button.setToolTip(f"Set rating to {rating} star" + ("" if rating == 1 else "s"))
            button.setEnabled(False)
            button.setAutoRaise(True)
            button.setStyleSheet("QToolButton { font-size: 22px; padding: 0 1px; }")
            button.clicked.connect(lambda _checked=False, value=rating: self.set_current_rating(value))
            self.rating_buttons.append(button)
        self.clear_rating_button = QToolButton()
        self.clear_rating_button.setText("Clear")
        self.clear_rating_button.setToolTip("Remove the rating from this image")
        self.clear_rating_button.setEnabled(False)
        self.clear_rating_button.clicked.connect(lambda: self.set_current_rating(0))

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(8, 4, 8, 8)
        action_layout.addWidget(self.clear_similarity_button)
        action_layout.addWidget(self.prompt_library_button)
        action_layout.addWidget(self.save_prompt_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.rating_label)
        for button in self.rating_buttons:
            action_layout.addWidget(button)
        action_layout.addWidget(self.clear_rating_button)
        action_layout.addSpacing(12)
        action_layout.addWidget(self.find_similar_button)
        action_layout.addWidget(self.experiment_view_button)
        action_layout.addWidget(self.compare_button)
        action_layout.addWidget(self.open_image_button)

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.main_splitter, 1)
        central_layout.addLayout(action_layout)
        self.setCentralWidget(central_widget)

    def create_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        open_action = QAction("Open folder", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_directory)
        toolbar.addAction(open_action)
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_directory)
        toolbar.addAction(refresh_action)
        similar_action = QAction("Find similar", self)
        similar_action.setShortcut("Ctrl+Shift+F")
        similar_action.triggered.connect(self.find_similar_images)
        toolbar.addAction(similar_action)
        experiment_action = QAction("Experiment view", self)
        experiment_action.setShortcut("Ctrl+E")
        experiment_action.triggered.connect(self.open_experiment_view)
        toolbar.addAction(experiment_action)
        library_action = QAction("Prompt library", self)
        library_action.setShortcut("Ctrl+L")
        library_action.triggered.connect(self.open_prompt_library)
        toolbar.addAction(library_action)
        save_prompt_action = QAction("Save prompt", self)
        save_prompt_action.setShortcut("Ctrl+Shift+S")
        save_prompt_action.triggered.connect(self.save_current_prompt)
        toolbar.addAction(save_prompt_action)
        for rating in range(6):
            rating_action = QAction(f"Set rating {rating}", self)
            rating_action.setShortcut(f"Ctrl+{rating}")
            rating_action.triggered.connect(lambda _checked=False, value=rating: self.set_current_rating(value))
            self.addAction(rating_action)
        toolbar.addSeparator()
        self.folder_label = QLabel("No folder selected")
        toolbar.addWidget(self.folder_label)

    def restore_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        main_state = self.settings.value("splitters/main")
        if main_state is not None:
            self.main_splitter.restoreState(main_state)

        right_state = self.settings.value("splitters/right")
        if right_state is not None:
            self.right_splitter.restoreState(right_state)

        summary_state = self.settings.value("splitters/summary")
        if summary_state is not None:
            self.metadata_panel.summary_splitter.restoreState(summary_state)

        metadata_tab = int(self.settings.value("metadata/current_tab", 0))
        if 0 <= metadata_tab < self.metadata_panel.tabs.count():
            self.metadata_panel.tabs.setCurrentIndex(metadata_tab)

        thumbnail_width = int(self.settings.value("thumbnails/width", 180))
        thumbnail_height = int(self.settings.value("thumbnails/height", 180))
        grid_width = int(self.settings.value("thumbnails/grid_width", 210))
        grid_height = int(self.settings.value("thumbnails/grid_height", 225))
        self.image_list.setIconSize(QSize(thumbnail_width, thumbnail_height))
        self.image_list.setGridSize(QSize(grid_width, grid_height))

        rating_filter = str(self.settings.value("filters/rating", "all"))
        rating_index = self.rating_filter_combo.findData(rating_filter)
        if rating_index >= 0:
            self.rating_filter_combo.setCurrentIndex(rating_index)

        sort_mode = self.settings.value("sorting/mode", "filename_asc")
        sort_index = self.sort_combo.findData(sort_mode)
        if sort_index >= 0:
            self.sort_combo.setCurrentIndex(sort_index)

        last_directory = self.settings.value("navigation/last_directory", "")
        if isinstance(last_directory, str) and last_directory:
            path = Path(last_directory)
            if path.is_dir():
                self.select_directory_in_tree(path)
                self.load_directory(path)

    def save_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("splitters/main", self.main_splitter.saveState())
        self.settings.setValue("splitters/right", self.right_splitter.saveState())
        self.settings.setValue(
            "splitters/summary",
            self.metadata_panel.summary_splitter.saveState(),
        )
        self.settings.setValue(
            "metadata/current_tab",
            self.metadata_panel.tabs.currentIndex(),
        )
        self.settings.setValue("thumbnails/width", self.image_list.iconSize().width())
        self.settings.setValue("thumbnails/height", self.image_list.iconSize().height())
        self.settings.setValue("thumbnails/grid_width", self.image_list.gridSize().width())
        self.settings.setValue("thumbnails/grid_height", self.image_list.gridSize().height())
        self.settings.setValue("sorting/mode", self.current_sort_mode())
        self.settings.setValue("filters/rating", self.rating_filter_combo.currentData())
        if self.current_directory is not None:
            self.settings.setValue("navigation/last_directory", str(self.current_directory))
        self.settings.sync()

    def current_sort_mode(self) -> str:
        value = self.sort_combo.currentData()
        return str(value) if value else "filename_asc"

    def sort_key_for_path(self, path: Path) -> tuple[Any, ...]:
        mode = self.current_sort_mode()
        try:
            modified_ns = path.stat().st_mtime_ns
        except OSError:
            modified_ns = 0

        filename_key = path.name.casefold()
        rating = self.ratings_database.get(path)
        if mode == "rating_desc":
            return (-rating, filename_key)
        if mode == "rating_asc":
            return (rating, filename_key)
        if mode == "filename_desc":
            return (filename_key,)
        if mode == "modified_desc":
            return (-modified_ns, filename_key)
        if mode == "modified_asc":
            return (modified_ns, filename_key)
        return (filename_key,)

    def sorted_image_paths(self, directory: Path) -> list[Path]:
        paths = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        mode = self.current_sort_mode()
        reverse = mode == "filename_desc"
        return sorted(paths, key=self.sort_key_for_path, reverse=reverse)

    def rating_filter_changed(self, _index: int) -> None:
        value = self.rating_filter_combo.currentData()
        self.active_rating_filter = str(value) if value else "all"
        self.apply_filters()
        self.schedule_visible_thumbnail_load()

    def sort_changed(self, _index: int) -> None:
        if self.current_directory is not None:
            self.load_directory(self.current_directory, preserve_state=True)

    def watch_directory(self, directory: Path) -> None:
        watched = self.file_watcher.directories()
        if watched:
            self.file_watcher.removePaths(watched)
        directory_string = str(directory)
        if directory.is_dir():
            self.file_watcher.addPath(directory_string)

    def directory_contents_changed(self, changed_path: str) -> None:
        if (
            self.current_directory is not None
            and Path(changed_path) == self.current_directory
        ):
            self.watcher_refresh_timer.start()

    def refresh_from_watcher(self) -> None:
        directory = self.current_directory
        if directory is None or not directory.is_dir():
            return
        self.load_directory(directory, preserve_state=True)
        # Some platforms can drop a watch after directory replacement.
        if str(directory) not in self.file_watcher.directories():
            self.file_watcher.addPath(str(directory))

    def choose_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Choose image directory", str(self.current_directory or Path.home())
        )
        if selected:
            directory = Path(selected)
            self.select_directory_in_tree(directory)
            self.load_directory(directory)

    def select_directory_in_tree(self, directory: Path) -> None:
        index = self.file_model.index(str(directory))
        if index.isValid():
            self.directory_tree.setCurrentIndex(index)
            self.directory_tree.scrollTo(index)

    def directory_selected(self, index) -> None:
        path = Path(self.file_model.filePath(index))
        if path.is_dir():
            self.load_directory(path)

    def refresh_directory(self) -> None:
        if self.current_directory:
            self.load_directory(self.current_directory, preserve_state=True)

    def create_filter_row(
        self,
        filter_kind: str,
    ) -> tuple[QButtonGroup, QHBoxLayout, QScrollArea]:
        group = QButtonGroup(self)
        group.setExclusive(True)

        contents = QWidget()
        layout = QHBoxLayout(contents)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(contents)
        scroll.setFixedHeight(44)
        scroll.setProperty("filter_kind", filter_kind)
        return group, layout, scroll

    @staticmethod
    def make_filter_labeled_row(
        title: str,
        scroll: QScrollArea,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel(f"{title}:")
        label.setMinimumWidth(68)
        label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(label)
        layout.addWidget(scroll, 1)
        return row

    def filter_components(
        self,
        filter_kind: str,
    ) -> tuple[dict[str, QToolButton], QButtonGroup, QHBoxLayout]:
        if filter_kind == "model":
            return (
                self.model_buttons,
                self.model_group,
                self.model_filter_layout,
            )
        if filter_kind == "sampler":
            return (
                self.sampler_buttons,
                self.sampler_group,
                self.sampler_filter_layout,
            )
        if filter_kind == "scheduler":
            return (
                self.scheduler_buttons,
                self.scheduler_group,
                self.scheduler_filter_layout,
            )
        raise ValueError(f"Unknown filter kind: {filter_kind}")

    def reset_filter_buttons(self, filter_kind: str) -> None:
        buttons, group, _layout = self.filter_components(filter_kind)
        for value, button in list(buttons.items()):
            if value != "All":
                group.removeButton(button)
                button.deleteLater()
                del buttons[value]

        setattr(self, f"active_{filter_kind}", "All")
        all_button = buttons.get("All")
        if all_button is not None:
            all_button.setChecked(True)

    def add_filter_button(
        self,
        filter_kind: str,
        value: str,
        checked: bool = False,
    ) -> None:
        buttons, group, layout = self.filter_components(filter_kind)
        if value in buttons:
            return

        button = QToolButton()
        if filter_kind == "model" and value != "All":
            button.setText(model_display_name(value))
        else:
            button.setText(value)
        button.setToolTip(value)
        button.setCheckable(True)
        button.setProperty("filter_value", value)
        group.addButton(button)
        layout.insertWidget(max(0, layout.count() - 1), button)
        buttons[value] = button

        desired = self.pending_filter_restore.get(filter_kind)
        if desired == value:
            setattr(self, f"active_{filter_kind}", value)
            button.setChecked(True)
        else:
            button.setChecked(checked)

    def reset_filter_rows(self) -> None:
        self.reset_filter_buttons("model")
        self.reset_filter_buttons("sampler")
        self.reset_filter_buttons("scheduler")

    def model_filter_clicked(self, button: QToolButton) -> None:
        value = button.property("filter_value")
        self.pending_filter_restore.pop("model", None)
        self.active_model = str(value) if value else "All"
        self.apply_filters()
        self.schedule_visible_thumbnail_load()

    def sampler_filter_clicked(self, button: QToolButton) -> None:
        value = button.property("filter_value")
        self.pending_filter_restore.pop("sampler", None)
        self.active_sampler = str(value) if value else "All"
        self.apply_filters()
        self.schedule_visible_thumbnail_load()

    def scheduler_filter_clicked(self, button: QToolButton) -> None:
        value = button.property("filter_value")
        self.pending_filter_restore.pop("scheduler", None)
        self.active_scheduler = str(value) if value else "All"
        self.apply_filters()
        self.schedule_visible_thumbnail_load()

    def load_directory(self, directory: Path, preserve_state: bool = False) -> None:
        preserved_filename_search = (
            self.filename_search_box.text() if preserve_state else ""
        )
        preserved_prompt_search = (
            self.prompt_search_box.text() if preserve_state else ""
        )
        preserved_filters = (
            {
                "model": self.active_model,
                "sampler": self.active_sampler,
                "scheduler": self.active_scheduler,
            }
            if preserve_state
            else {"model": "All", "sampler": "All", "scheduler": "All"}
        )
        preserved_selection = (
            {
                str(item.data(PATH_ROLE))
                for item in self.image_list.selectedItems()
                if isinstance(item.data(PATH_ROLE), str)
            }
            if preserve_state
            else set()
        )
        preserved_current = (
            str(self.current_image_path)
            if preserve_state and self.current_image_path is not None
            else None
        )

        self.thumbnail_generation += 1
        generation = self.thumbnail_generation
        self.lazy_load_timer.stop()
        self.current_directory = directory
        self.watch_directory(directory)
        self.folder_label.setText(str(directory))
        self.image_list.clear()
        self.thumbnail_items.clear()
        self.filename_search_box.blockSignals(True)
        self.prompt_search_box.blockSignals(True)
        self.filename_search_box.setText(preserved_filename_search)
        self.prompt_search_box.setText(preserved_prompt_search)
        self.filename_search_box.blockSignals(False)
        self.prompt_search_box.blockSignals(False)
        self.reset_filter_rows()
        self.pending_filter_restore = preserved_filters
        self.active_model = preserved_filters["model"]
        self.active_sampler = preserved_filters["sampler"]
        self.active_scheduler = preserved_filters["scheduler"]
        self.pending_selection_restore = preserved_selection
        self.metadata_panel.clear()
        self.current_pixmap = None
        self.current_image_path = None
        self.current_metadata = {}
        self.open_image_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        self.find_similar_button.setEnabled(False)
        self.experiment_view_button.setEnabled(False)
        self.save_prompt_button.setEnabled(False)
        self.update_rating_controls(0, enabled=False)
        self.similarity_matches = None
        self.similarity_reference = None
        self.similarity_criteria = {}
        self.clear_similarity_button.setVisible(False)
        self.preview.clear()
        self.preview.setText("Select an image")
        self.cache_hits = 0
        self.generated_thumbnails = 0

        try:
            image_paths = self.sorted_image_paths(directory)
        except OSError as error:
            QMessageBox.critical(self, "Unable to open folder", str(error))
            return

        for path in image_paths:
            item = QListWidgetItem(path.name)
            item.setData(PATH_ROLE, str(path))
            item.setData(MODEL_ROLE, None)
            item.setData(SAMPLER_ROLE, None)
            item.setData(SCHEDULER_ROLE, None)
            item.setData(THUMB_STATE_ROLE, STATE_NOT_REQUESTED)
            item.setData(POSITIVE_PROMPT_ROLE, None)
            item.setData(RATING_ROLE, self.ratings_database.get(path))
            try:
                item.setData(MODIFIED_ROLE, path.stat().st_mtime_ns)
            except OSError:
                item.setData(MODIFIED_ROLE, 0)
            item.setToolTip(str(path))
            self.image_list.addItem(item)
            self.thumbnail_items[str(path)] = item

            if str(path) in preserved_selection:
                item.setSelected(True)

            metadata_worker = MetadataWorker(path, generation)
            metadata_worker.signals.loaded.connect(self.model_loaded)
            self.thread_pool.start(metadata_worker)

        count = len(image_paths)
        if count == 0:
            self.statusBar().showMessage("No images found")
            return

        self.statusBar().showMessage(
            f"{count} images — scanning generation metadata"
        )

        current_item = (
            self.thumbnail_items.get(preserved_current)
            if preserved_current is not None
            else None
        )
        if current_item is not None:
            self.image_list.setCurrentItem(current_item)
        elif count and not preserved_selection:
            self.image_list.setCurrentRow(0)

        self.apply_filters()
        QTimer.singleShot(0, self.queue_visible_thumbnails)

    def model_loaded(
        self,
        path_string: str,
        model: str,
        sampler: str,
        scheduler: str,
        positive_prompt: str,
        generation: int,
    ) -> None:
        if generation != self.thumbnail_generation:
            return

        item = self.thumbnail_items.get(path_string)
        if item is None:
            return

        item.setData(MODEL_ROLE, model)
        item.setData(SAMPLER_ROLE, sampler)
        item.setData(SCHEDULER_ROLE, scheduler)
        item.setData(POSITIVE_PROMPT_ROLE, positive_prompt)

        self.add_filter_button("model", model)
        self.add_filter_button("sampler", sampler)
        self.add_filter_button("scheduler", scheduler)

        self.apply_filters()

    def search_changed(self, _text: str) -> None:
        self.apply_filters()
        self.schedule_visible_thumbnail_load()

    def apply_filters(self) -> None:
        filename_terms = [
            term.casefold()
            for term in self.filename_search_box.text().split()
            if term.strip()
        ]
        prompt_terms = [
            term.casefold()
            for term in self.prompt_search_box.text().split()
            if term.strip()
        ]

        visible_count = 0
        for index in range(self.image_list.count()):
            item = self.image_list.item(index)
            model = item.data(MODEL_ROLE)
            model_matches = (
                self.active_model == "All"
                or model == self.active_model
            )

            sampler = item.data(SAMPLER_ROLE)
            sampler_matches = (
                self.active_sampler == "All"
                or sampler == self.active_sampler
            )

            scheduler = item.data(SCHEDULER_ROLE)
            scheduler_matches = (
                self.active_scheduler == "All"
                or scheduler == self.active_scheduler
            )

            filename = item.text().casefold()
            filename_matches = all(
                term in filename for term in filename_terms
            )

            positive_value = item.data(POSITIVE_PROMPT_ROLE)
            positive_prompt = (
                positive_value.casefold()
                if isinstance(positive_value, str)
                else ""
            )
            prompt_matches = all(
                term in positive_prompt for term in prompt_terms
            )

            path_value = item.data(PATH_ROLE)
            similarity_matches = (
                self.similarity_matches is None
                or (isinstance(path_value, str) and path_value in self.similarity_matches)
            )

            rating_value = item.data(RATING_ROLE)
            rating = int(rating_value) if isinstance(rating_value, int) else 0
            rating_filter = self.active_rating_filter
            if rating_filter == "unrated":
                rating_matches = rating == 0
            elif rating_filter == "5only":
                rating_matches = rating == 5
            elif rating_filter.endswith("plus") and rating_filter[0].isdigit():
                rating_matches = rating >= int(rating_filter[0])
            else:
                rating_matches = True

            hide = not (
                model_matches
                and sampler_matches
                and scheduler_matches
                and filename_matches
                and prompt_matches
                and similarity_matches
                and rating_matches
            )
            item.setHidden(hide)
            if not hide:
                visible_count += 1

        total = self.image_list.count()
        filtering = (
            bool(filename_terms)
            or bool(prompt_terms)
            or self.active_model != "All"
            or self.active_sampler != "All"
            or self.active_scheduler != "All"
            or self.similarity_matches is not None
            or self.active_rating_filter != "all"
        )
        if filtering:
            self.statusBar().showMessage(
                f"Showing {visible_count} of {total} images"
            )

    def schedule_visible_thumbnail_load(self, *_args) -> None:
        self.lazy_load_timer.start()

    def queue_visible_thumbnails(self) -> None:
        if self.image_list.count() == 0:
            return

        viewport_rect = self.image_list.viewport().rect()
        margin = self.image_list.gridSize().height() * self.PREFETCH_ROWS
        expanded = viewport_rect.adjusted(0, -margin, 0, margin)
        generation = self.thumbnail_generation

        queued = 0
        for index in range(self.image_list.count()):
            item = self.image_list.item(index)
            if item.isHidden() or item.data(THUMB_STATE_ROLE) != STATE_NOT_REQUESTED:
                continue
            rect = self.image_list.visualItemRect(item)
            if rect.isValid() and rect.intersects(expanded):
                path_string = item.data(PATH_ROLE)
                if not isinstance(path_string, str):
                    continue
                item.setData(THUMB_STATE_ROLE, STATE_QUEUED)
                worker = ThumbnailWorker(Path(path_string), self.image_list.iconSize(), generation)
                worker.signals.loaded.connect(self.thumbnail_loaded)
                worker.signals.failed.connect(self.thumbnail_failed)
                self.thread_pool.start(worker)
                queued += 1

        if queued:
            self.statusBar().showMessage(f"Loading {queued} visible thumbnail{'s' if queued != 1 else ''}…")

    def thumbnail_loaded(
        self,
        path_string: str,
        image: QImage,
        cache_hit: bool,
        generation: int,
    ) -> None:
        if generation != self.thumbnail_generation:
            return
        item = self.thumbnail_items.get(path_string)
        if item is None:
            return
        item.setIcon(QIcon(QPixmap.fromImage(image)))
        item.setData(THUMB_STATE_ROLE, STATE_READY)
        if cache_hit:
            self.cache_hits += 1
        else:
            self.generated_thumbnails += 1
        self.update_thumbnail_status()

    def thumbnail_failed(self, path_string: str, error_message: str, generation: int) -> None:
        if generation != self.thumbnail_generation:
            return
        item = self.thumbnail_items.get(path_string)
        if item is not None:
            item.setData(THUMB_STATE_ROLE, STATE_FAILED)
            item.setToolTip(f"{path_string}\nThumbnail error: {error_message}")
        self.update_thumbnail_status()

    def update_thumbnail_status(self) -> None:
        ready = 0
        queued = 0
        for index in range(self.image_list.count()):
            state = self.image_list.item(index).data(THUMB_STATE_ROLE)
            ready += state in (STATE_READY, STATE_FAILED)
            queued += state == STATE_QUEUED
        total = self.image_list.count()
        self.statusBar().showMessage(
            f"{total} images — {ready} thumbnails loaded"
            f" ({self.cache_hits} cached, {self.generated_thumbnails} generated)"
            + (f", {queued} loading" if queued else "")
        )

    def image_selected(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        path_value = current.data(PATH_ROLE)
        if not isinstance(path_value, str):
            return
        path = Path(path_value)

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.preview.clear()
            self.preview.setText("Unable to load image")
            self.current_pixmap = None
            self.current_image_path = None
            self.current_metadata = {}
            self.open_image_button.setEnabled(False)
            self.find_similar_button.setEnabled(False)
            self.experiment_view_button.setEnabled(False)
            self.update_rating_controls(0, enabled=False)
            self.metadata_panel.clear()
            return

        self.current_pixmap = pixmap
        self.current_image_path = path
        self.update_preview()
        metadata = read_image_metadata(path)
        self.current_metadata = metadata
        self.metadata_panel.show_metadata(path, metadata)
        self.open_image_button.setEnabled(True)
        self.find_similar_button.setEnabled(True)
        self.experiment_view_button.setEnabled(True)
        rating = self.ratings_database.get(path)
        current.setData(RATING_ROLE, rating)
        self.update_rating_controls(rating, enabled=True)
        summary = extract_summary(metadata)
        self.save_prompt_button.setEnabled(bool(summary["positive"] or summary["negative"]))

        message = (
            f"{path.name} — {rating_text(rating)} — ComfyUI metadata found"
            if "prompt" in metadata or "workflow" in metadata
            else f"{path.name} — {rating_text(rating)} — no ComfyUI metadata found"
        )
        self.statusBar().showMessage(message)


    def update_rating_controls(self, rating: int, enabled: bool = True) -> None:
        value = max(0, min(5, int(rating)))
        for index, button in enumerate(self.rating_buttons, start=1):
            button.setText("★" if index <= value else "☆")
            button.setEnabled(enabled)
        self.clear_rating_button.setEnabled(enabled and value > 0)
        self.rating_label.setEnabled(enabled)

    def set_current_rating(self, rating: int) -> None:
        path = self.current_image_path
        if path is None:
            return
        value = max(0, min(5, int(rating)))
        self.ratings_database.set(path, value)
        item = self.thumbnail_items.get(str(path))
        if item is not None:
            item.setData(RATING_ROLE, value)
            base_tip = str(path)
            item.setToolTip(f"{base_tip}\nRating: {rating_text(value)}" if value else base_tip)
        self.update_rating_controls(value, enabled=True)
        self.statusBar().showMessage(
            f"{path.name}: " + (f"rated {value} star" + ("" if value == 1 else "s") if value else "rating cleared"),
            3000,
        )
        if self.current_sort_mode().startswith("rating_") and self.current_directory is not None:
            self.load_directory(self.current_directory, preserve_state=True)
        else:
            self.apply_filters()
            self.schedule_visible_thumbnail_load()

    def prompt_values_for_current_image(self) -> dict[str, str] | None:
        if self.current_image_path is None:
            return None
        summary = extract_summary(self.current_metadata)
        if not summary["positive"] and not summary["negative"]:
            return None
        loras = extract_loras(self.current_metadata)
        return {
            "title": self.current_image_path.stem,
            "description": "",
            "tags": "",
            "positive_prompt": summary["positive"],
            "negative_prompt": summary["negative"],
            "source_image": str(self.current_image_path),
            "model": summary["model"],
            "loras_json": json.dumps(loras, ensure_ascii=False),
        }

    def save_current_prompt(self) -> None:
        values = self.prompt_values_for_current_image()
        if values is None:
            QMessageBox.information(self, "No prompt found", "The selected image does not contain a readable positive or negative prompt.")
            return
        dialog = PromptEntryDialog(values, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.prompt_library_database.add(dialog.values())
            self.statusBar().showMessage("Prompt saved to library", 4000)

    def open_prompt_library(self) -> None:
        dialog = PromptLibraryDialog(self.prompt_library_database, self.open_library_source_image, self)
        dialog.exec()

    def open_library_source_image(self, path: Path) -> None:
        # Prefer selecting it inside metaView when its folder is already loaded.
        item = self.thumbnail_items.get(str(path))
        if item is not None:
            self.image_list.setCurrentItem(item)
            self.image_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if not opened:
            QMessageBox.warning(self, "Unable to open image", "The operating system could not open the originating image.")

    def open_experiment_view(self) -> None:
        reference = self.current_image_path
        if reference is None:
            QMessageBox.information(self, "Select an image", "Select an image to open in Experiment View.")
            return
        if self.current_directory is None:
            return

        reference_prompt = extract_summary(self.current_metadata)["positive"]
        if not reference_prompt:
            QMessageBox.information(
                self,
                "No positive prompt",
                "The selected image does not contain a detectable positive prompt.",
            )
            return

        matches: list[Path] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Finding images with an identical positive prompt…")
        try:
            for path in self.sorted_image_paths(self.current_directory):
                metadata = self.current_metadata if path == reference else read_image_metadata(path)
                if extract_summary(metadata)["positive"] == reference_prompt:
                    matches.append(path)
                if len(matches) and len(matches) % 50 == 0:
                    QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()

        if reference not in matches:
            matches.insert(0, reference)
        if len(matches) < 2:
            QMessageBox.information(
                self,
                "No matching generations",
                "No other images in this directory have an identical positive prompt.",
            )
            self.statusBar().showMessage("No matching experiment images found", 3000)
            return

        self.statusBar().showMessage(f"Experiment View: {len(matches)} matching images")
        dialog = ExperimentDialog(reference, matches, self)
        dialog.exec()

    def find_similar_images(self) -> None:
        reference = self.current_image_path
        if reference is None:
            QMessageBox.information(
                self,
                "Select an image",
                "Select the image you want to use as the similarity reference.",
            )
            return

        dialog = SimilaritySearchDialog(reference, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        criteria = dialog.criteria()
        reference_metadata = read_image_metadata(reference)
        reference_summary = extract_summary(reference_metadata)
        reference_loras = lora_signature(reference_metadata)
        reference_resolution = image_resolution(reference)

        def matches(path: Path) -> bool:
            metadata = read_image_metadata(path)
            summary = extract_summary(metadata)

            if criteria["model"] and summary["model"].casefold() != reference_summary["model"].casefold():
                return False
            if criteria["loras"] and lora_signature(metadata) != reference_loras:
                return False
            if criteria["seed"] and summary["seed"] != reference_summary["seed"]:
                return False
            if criteria["prompt"] and normalised_prompt(summary["positive"]) != normalised_prompt(reference_summary["positive"]):
                return False
            if criteria["sampler"] and summary["sampler"].casefold() != reference_summary["sampler"].casefold():
                return False
            if criteria["scheduler"] and summary["scheduler"].casefold() != reference_summary["scheduler"].casefold():
                return False
            if criteria["resolution"] and image_resolution(path) != reference_resolution:
                return False
            return True

        matching_paths: set[str] = set()
        total = self.image_list.count()
        self.statusBar().showMessage(f"Searching {total} images for metadata matches…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for index in range(total):
                item = self.image_list.item(index)
                path_value = item.data(PATH_ROLE)
                if isinstance(path_value, str) and matches(Path(path_value)):
                    matching_paths.add(path_value)
                if index and index % 50 == 0:
                    QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()

        self.similarity_matches = matching_paths
        self.similarity_reference = reference
        self.similarity_criteria = criteria
        self.clear_similarity_button.setVisible(True)
        self.apply_filters()
        self.schedule_visible_thumbnail_load()

        count = len(matching_paths)
        selected_names = [
            label
            for key, label in (
                ("model", "model"),
                ("loras", "LoRAs"),
                ("seed", "seed"),
                ("prompt", "prompt"),
                ("sampler", "sampler"),
                ("scheduler", "scheduler"),
                ("resolution", "resolution"),
            )
            if criteria[key]
        ]
        self.statusBar().showMessage(
            f"{count} similar image{'s' if count != 1 else ''} found using "
            + ", ".join(selected_names)
        )

    def clear_similarity_search(self) -> None:
        self.similarity_matches = None
        self.similarity_reference = None
        self.similarity_criteria = {}
        self.clear_similarity_button.setVisible(False)
        self.apply_filters()
        self.schedule_visible_thumbnail_load()
        self.statusBar().showMessage("Similarity search cleared")

    def update_compare_button(self) -> None:
        self.compare_button.setEnabled(
            len(self.image_list.selectedItems()) == 2
        )

    def compare_selected_images(self) -> None:
        selected = self.image_list.selectedItems()
        if len(selected) != 2:
            QMessageBox.information(
                self,
                "Select two images",
                "Select exactly two thumbnails using Ctrl-click, then choose Compare.",
            )
            return

        paths: list[Path] = []
        for item in selected:
            value = item.data(PATH_ROLE)
            if isinstance(value, str):
                paths.append(Path(value))
        if len(paths) != 2:
            return

        dialog = ComparisonDialog(paths[0], paths[1], self)
        dialog.exec()

    def open_selected_image(self) -> None:
        if self.current_image_path is None:
            return
        opened = QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.current_image_path))
        )
        if not opened:
            QMessageBox.warning(
                self,
                "Unable to open image",
                "The operating system could not open the selected image.",
            )

    def export_workflow_for_image(
        self,
        image_path: Path,
        show_errors: bool = False,
    ) -> Path | None:
        metadata = (
            self.current_metadata
            if image_path == self.current_image_path
            else read_image_metadata(image_path)
        )
        workflow = parse_json_value(metadata.get("workflow"))

        if not isinstance(workflow, (dict, list)):
            if show_errors:
                QMessageBox.information(
                    self,
                    "No embedded workflow",
                    "The selected image does not contain a readable ComfyUI workflow to drag.",
                )
            return None

        cache_root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        if not cache_root:
            cache_root = str(Path.home() / ".cache" / "comfyui-image-browser")

        workflow_directory = Path(cache_root) / "dragged-workflows"
        try:
            workflow_directory.mkdir(parents=True, exist_ok=True)
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", image_path.stem).strip("._") or "workflow"
            stat = image_path.stat()
            workflow_path = workflow_directory / f"{safe_stem}-{stat.st_mtime_ns:x}.json"
            workflow_path.write_text(
                json.dumps(workflow, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return workflow_path
        except OSError as error:
            if show_errors:
                QMessageBox.critical(self, "Unable to export workflow", str(error))
            return None

    def _preview_splitter_moved(self, _position: int, _index: int) -> None:
        # Splitter geometry settles after the signal; defer one event-loop turn.
        QTimer.singleShot(0, self.update_preview)
        QTimer.singleShot(0, self.schedule_visible_thumbnail_load)

    def update_preview(self) -> None:
        if self.current_pixmap is None:
            return
        available_size = self.preview.size() - QSize(20, 20)
        if available_size.width() <= 0 or available_size.height() <= 0:
            return
        self.preview.setPixmap(
            self.current_pixmap.scaled(
                available_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_preview()
        self.schedule_visible_thumbnail_load()

    def closeEvent(self, event) -> None:
        self.save_settings()
        super().closeEvent(event)




def apply_dark_theme(app: QApplication) -> None:
    """Apply a consistent cross-platform dark palette and widget styling."""

    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(235, 235, 235))
    palette.setColor(QPalette.ColorRole.Base, QColor(22, 22, 22))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(245, 245, 245))
    palette.setColor(QPalette.ColorRole.Text, QColor(235, 235, 235))
    palette.setColor(QPalette.ColorRole.Button, QColor(42, 42, 42))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(235, 235, 235))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 95, 95))
    palette.setColor(QPalette.ColorRole.Link, QColor(90, 165, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(52, 105, 165))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(145, 145, 145))

    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(105, 105, 105))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(105, 105, 105))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(105, 105, 105))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(55, 55, 55))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(130, 130, 130))

    app.setPalette(palette)

    app.setStyleSheet(
        """
        QMainWindow, QDialog, QWidget {
            background-color: #1e1e1e;
            color: #ebebeb;
        }
        QToolBar, QStatusBar, QMenuBar {
            background-color: #242424;
            border: none;
        }
        QToolBar {
            spacing: 6px;
            padding: 4px;
            border-bottom: 1px solid #3a3a3a;
        }
        QLineEdit, QPlainTextEdit, QTextEdit, QTreeView, QListWidget, QTableWidget, QComboBox {
            background-color: #161616;
            color: #ebebeb;
            border: 1px solid #444444;
            border-radius: 4px;
            selection-background-color: #3469a5;
            selection-color: #ffffff;
        }
        QLineEdit, QComboBox {
            padding: 5px 7px;
            min-height: 22px;
        }
        QPlainTextEdit, QTextEdit, QTreeView, QListWidget, QTableWidget {
            alternate-background-color: #232323;
        }
        QTreeView::item, QListWidget::item { padding: 3px; }
        QTreeView::item:selected, QListWidget::item:selected {
            background-color: #3469a5;
            color: #ffffff;
        }
        QPushButton, QToolButton {
            background-color: #303030;
            color: #ebebeb;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            padding: 5px 9px;
        }
        QPushButton:hover, QToolButton:hover {
            background-color: #3b3b3b;
            border-color: #666666;
        }
        QPushButton:pressed, QToolButton:pressed, QToolButton:checked {
            background-color: #3469a5;
            border-color: #4a85c6;
            color: #ffffff;
        }
        QPushButton:disabled, QToolButton:disabled {
            background-color: #252525;
            color: #707070;
            border-color: #333333;
        }
        QTabWidget::pane {
            border: 1px solid #3f3f3f;
            background-color: #1e1e1e;
        }
        QTabBar::tab {
            background-color: #292929;
            color: #cfcfcf;
            border: 1px solid #3f3f3f;
            border-bottom: none;
            padding: 7px 12px;
            margin-right: 1px;
        }
        QTabBar::tab:selected {
            background-color: #1e1e1e;
            color: #ffffff;
        }
        QTabBar::tab:hover:!selected { background-color: #343434; }
        QHeaderView::section {
            background-color: #2c2c2c;
            color: #ebebeb;
            border: none;
            border-right: 1px solid #454545;
            border-bottom: 1px solid #454545;
            padding: 6px;
        }
        QTableWidget { gridline-color: #3b3b3b; }
        QScrollBar:vertical {
            background: #202020;
            width: 13px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #505050;
            min-height: 28px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover { background: #626262; }
        QScrollBar:horizontal {
            background: #202020;
            height: 13px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #505050;
            min-width: 28px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal:hover { background: #626262; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QSplitter::handle { background-color: #383838; }
        QSplitter::handle:hover { background-color: #505050; }
        QToolTip {
            background-color: #2d2d2d;
            color: #ffffff;
            border: 1px solid #5a5a5a;
            padding: 4px;
        }
        QComboBox QAbstractItemView {
            background-color: #202020;
            color: #ebebeb;
            selection-background-color: #3469a5;
        }
        QCheckBox { spacing: 6px; }
        QLabel { background: transparent; }
        """
    )


def create_splash_pixmap() -> QPixmap:
    """
    Render the branded startup splash using the metaView application icon.
    """
    width = 760
    height = 420

    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#141414"))

    painter = QPainter(pixmap)

    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        painter.fillRect(0, 0, width, height, QColor("#141414"))
        painter.fillRect(0, height - 8, width, 8, QColor("#3469a5"))

        icon = QPixmap(str(asset_path("metaview.png")))
        if not icon.isNull():
            icon = icon.scaled(
                150,
                150,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_x = 72 + (150 - icon.width()) // 2
            icon_y = 72 + (150 - icon.height()) // 2
            painter.drawPixmap(icon_x, icon_y, icon)

        title_font = QFont("Sans Serif", 36)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(250, 92, 430, 60),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            "metaView",
        )

        subtitle_font = QFont("Sans Serif", 17)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#d5d5d5"))
        painter.drawText(
            QRectF(250, 154, 430, 68),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop,
            "GenAI image browser and metadata analyser.",
        )

        byline_font = QFont("Sans Serif", 12)
        painter.setFont(byline_font)
        painter.setPen(QColor("#9a9a9a"))
        painter.drawText(
            QRectF(72, 320, 616, 36),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            "Broomfield Developments, 2026",
        )

    finally:
        painter.end()

    return pixmap

def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("Broomfield Developments")
    app.setApplicationName("metaView GenAI Metadata Viewer")

    application_icon = QIcon(str(asset_path("metaview.ico")))
    if application_icon.isNull():
        application_icon = QIcon(str(asset_path("metaview.png")))
    app.setWindowIcon(application_icon)

    apply_dark_theme(app)

    splash = QSplashScreen(
        create_splash_pixmap(),
        Qt.WindowType.WindowStaysOnTopHint,
    )
    splash.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    splash.show()
    app.processEvents()

    window = MainWindow()
    window.show()

    # Keep the splash visible for three seconds after the main window
    # has finished constructing and has been shown.
    QTimer.singleShot(3000, lambda: splash.finish(window))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
