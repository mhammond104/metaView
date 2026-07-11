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

from .constants import asset_path

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

