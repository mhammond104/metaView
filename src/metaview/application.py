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
from .main_window import MainWindow
from .theme import apply_theme, create_splash_pixmap

def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("Broomfield Developments")
    app.setApplicationName("metaView GenAI Image and Experiment Manager")

    application_icon = QIcon(str(asset_path("metaview.ico")))
    if application_icon.isNull():
        application_icon = QIcon(str(asset_path("metaview.png")))
    app.setWindowIcon(application_icon)

    apply_theme(app)

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


