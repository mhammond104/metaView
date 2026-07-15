from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
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
from .metadata import display_json, extract_loras, extract_summary, parse_json_value

class ImageDragListWidget(QListWidget):
    """Thumbnail list that drags the original image file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supported_actions) -> None:
        selected = self.selectedItems()
        item = self.currentItem()
        if item is None:
            return
        if item not in selected:
            selected = [item]

        image_paths: list[Path] = []
        for selected_item in selected:
            path_value = selected_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(path_value, str):
                path = Path(path_value)
                if path.is_file():
                    image_paths.append(path)
        if not image_paths:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in image_paths])
        mime_data.setText("\n".join(str(path) for path in image_paths))

        drag = QDrag(self)
        drag.setMimeData(mime_data)

        icon = item.icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(self.iconSize()))

        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


def workflow_drag_mime_data(workflow_path: Path) -> QMimeData:
    """Create a cross-platform file drag payload for an exported workflow."""
    resolved_path = workflow_path.expanduser().resolve()
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(resolved_path))])
    mime_data.setText(str(resolved_path))

    if sys.platform == "win32":
        # Qt translates URLs for many Windows drop targets, but Explorer and
        # Chromium-based applications can also request the native shell
        # filename formats directly. Supplying them makes the drag reliable
        # across both kinds of target.
        filename_w = (str(resolved_path) + "\0").encode("utf-16le")
        mime_data.setData(
            'application/x-qt-windows-mime;value="FileNameW"',
            filename_w,
        )
        mime_data.setData(
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
            struct.pack("<I", 1),  # DROPEFFECT_COPY
        )

    return mime_data


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

        workflow_path = workflow_path.expanduser().resolve()
        mime_data = workflow_drag_mime_data(workflow_path)

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        if self.pixmap() is not None:
            drag.setPixmap(self.pixmap())
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
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
    def __init__(self, workflow_exporter, add_prompt_callback=None) -> None:
        super().__init__()
        self.add_prompt_callback = add_prompt_callback
        self.current_path: Path | None = None
        self.fields: dict[str, CopyableValue] = {}

        parameters_contents = QWidget()
        parameters_layout_outer = QVBoxLayout(parameters_contents)
        parameters_layout_outer.setContentsMargins(6, 6, 3, 6)
        parameters_layout_outer.setSpacing(6)

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
        workflow_layout.setContentsMargins(6, 4, 6, 4)
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
        prompts_layout.setContentsMargins(3, 6, 6, 6)
        prompts_layout.setSpacing(6)
        prompts_layout.addWidget(self.positive_prompt, 1)
        self.add_to_library_button = QPushButton("Add to Library")
        self.add_to_library_button.setEnabled(False)
        self.add_to_library_button.clicked.connect(self._add_to_library)
        prompts_layout.addWidget(self.add_to_library_button)
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

    def _add_to_library(self) -> None:
        if self.add_prompt_callback is None:
            return
        self.add_prompt_callback(
            self.positive_prompt.editor.toPlainText(),
            self.negative_prompt.editor.toPlainText(),
            self.current_path,
        )

    def clear(self) -> None:
        self.current_path = None
        self.add_to_library_button.setEnabled(False)
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
        self.current_path = path
        self.add_to_library_button.setEnabled(bool(summary["positive"].strip()))
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





class CollectionListWidget(QListWidget):
    """Collection sidebar accepting image-file drops from the thumbnail view."""

    imagesDropped = Signal(int, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self.itemAt(event.position().toPoint()) is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is None:
            event.ignore()
            return
        collection_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(collection_id, int):
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            event.ignore()
            return
        self.imagesDropped.emit(collection_id, paths)
        event.acceptProposedAction()
