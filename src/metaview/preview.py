from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QEvent, QPointF, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QImageReader,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QFrame,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolButton,
)


class ImageView(QGraphicsView):
    """Graphics view providing smooth zoom, fit-to-window and panning."""

    zoom_changed = Signal(int)

    MIN_SCALE = 0.02
    MAX_SCALE = 64.0
    ZOOM_STEP = 1.20

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)

        self._fit_mode = True
        self._native_scale = 1.0
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setFrameStyle(0)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    @property
    def has_image(self) -> bool:
        return not self._pixmap_item.pixmap().isNull()

    @property
    def fit_mode(self) -> bool:
        return self._fit_mode

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.resetTransform()
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._fit_mode = True
        self.fit_to_window()

    def clear_image(self) -> None:
        self._pixmap_item.setPixmap(QPixmap())
        self._scene.setSceneRect(0, 0, 0, 0)
        self.resetTransform()
        self.zoom_changed.emit(0)

    def fit_to_window(self) -> None:
        if not self.has_image:
            return
        self.resetTransform()
        self.fitInView(
            self._pixmap_item,
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._fit_mode = True
        self._emit_zoom()

    def actual_size(self) -> None:
        if not self.has_image:
            return
        self.resetTransform()
        self.centerOn(self._pixmap_item)
        self._fit_mode = False
        self._emit_zoom()

    def toggle_fit_actual(self) -> None:
        if self._fit_mode:
            self.actual_size()
        else:
            self.fit_to_window()

    def zoom_by(self, factor: float) -> None:
        if not self.has_image:
            return
        current = self.transform().m11()
        target = current * factor
        if target < self.MIN_SCALE:
            factor = self.MIN_SCALE / current
        elif target > self.MAX_SCALE:
            factor = self.MAX_SCALE / current
        self.scale(factor, factor)
        self._fit_mode = False
        self._emit_zoom()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.has_image or event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return
        self.zoom_by(self.ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self.ZOOM_STEP)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.has_image:
            self.toggle_fit_actual()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_to_window()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(round(self.transform().m11() * 100))


class PreviewWindow(QMainWindow):
    """Reusable image preview window with folder-result navigation."""

    def __init__(
        self,
        paths: Iterable[Path],
        current_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.paths = [Path(path) for path in paths]
        try:
            self.index = self.paths.index(Path(current_path))
        except ValueError:
            self.paths.insert(0, Path(current_path))
            self.index = 0

        self._was_maximized = False
        self.settings = QSettings("Martin Hammond", "ComfyUI Image Browser")
        self._toolbar_windowed_visible = self.settings.value("preview/toolbar_visible", True, type=bool)
        self._fullscreen_toolbar_pinned: bool | None = None
        self._toolbar_hovered = False

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("metaView Preview")
        geometry = self.settings.value("preview/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1200, 800)

        self.view = ImageView(self)
        self.view.zoom_changed.connect(self._update_zoom_label)
        self.setCentralWidget(self.view)

        self.filename_label = QLabel()
        self.resolution_label = QLabel()
        self.position_label = QLabel()
        self.zoom_label = QLabel()
        self.statusBar().addWidget(self.filename_label, 1)
        self.statusBar().addPermanentWidget(self.resolution_label)
        self.statusBar().addPermanentWidget(self.position_label)
        self.statusBar().addPermanentWidget(self.zoom_label)

        self._create_actions()
        self._create_toolbar_overlay()

        self._toolbar_hide_timer = QTimer(self)
        self._toolbar_hide_timer.setSingleShot(True)
        self._toolbar_hide_timer.setInterval(2000)
        self._toolbar_hide_timer.timeout.connect(self._auto_hide_toolbar)

        self.setMouseTracking(True)
        self.view.setMouseTracking(True)
        self.view.viewport().setMouseTracking(True)
        self.installEventFilter(self)
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)
        self.toolbar_overlay.installEventFilter(self)

        self.load_current_image()

    @property
    def current_path(self) -> Path:
        return self.paths[self.index]

    def _create_actions(self) -> None:
        self.previous_action = QAction("Previous", self)
        self.previous_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        self.previous_action.triggered.connect(self.show_previous)
        self.addAction(self.previous_action)

        self.next_action = QAction("Next", self)
        self.next_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        self.next_action.triggered.connect(self.show_next)
        self.addAction(self.next_action)

        self.first_action = QAction("First", self)
        self.first_action.setShortcut(QKeySequence(Qt.Key.Key_Home))
        self.first_action.triggered.connect(self.show_first)
        self.addAction(self.first_action)

        self.last_action = QAction("Last", self)
        self.last_action.setShortcut(QKeySequence(Qt.Key.Key_End))
        self.last_action.triggered.connect(self.show_last)
        self.addAction(self.last_action)

        self.fit_action = QAction("Fit", self)
        self.fit_action.setShortcut("F")
        self.fit_action.triggered.connect(self.view.fit_to_window)
        self.addAction(self.fit_action)

        self.actual_size_action = QAction("100%", self)
        self.actual_size_action.setShortcut("1")
        self.actual_size_action.triggered.connect(self.view.actual_size)
        self.addAction(self.actual_size_action)

        self.zoom_out_action = QAction("Zoom Out", self)
        self.zoom_out_action.setShortcuts(["-", "_"])
        self.zoom_out_action.triggered.connect(
            lambda: self.view.zoom_by(1 / self.view.ZOOM_STEP)
        )
        self.addAction(self.zoom_out_action)

        self.zoom_in_action = QAction("Zoom In", self)
        self.zoom_in_action.setShortcuts(["+", "="])
        self.zoom_in_action.triggered.connect(
            lambda: self.view.zoom_by(self.view.ZOOM_STEP)
        )
        self.addAction(self.zoom_in_action)

        self.toggle_toolbar_action = QAction("Toggle Toolbar", self)
        self.toggle_toolbar_action.setShortcut("T")
        self.toggle_toolbar_action.triggered.connect(self.toggle_toolbar)
        self.addAction(self.toggle_toolbar_action)

        self.fullscreen_action = QAction("Fullscreen", self)
        self.fullscreen_action.setShortcut("F11")
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(self.fullscreen_action)

        self.close_action = QAction("Close", self)
        self.close_action.setShortcut("Ctrl+W")
        self.close_action.triggered.connect(self.close)
        self.addAction(self.close_action)

    def _create_toolbar_overlay(self) -> None:
        self.toolbar_overlay = QFrame(self.view.viewport())
        self.toolbar_overlay.setObjectName("previewToolbarOverlay")
        layout = QHBoxLayout(self.toolbar_overlay)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        for action in (
            self.previous_action,
            self.next_action,
            None,
            self.fit_action,
            self.actual_size_action,
            self.zoom_out_action,
            self.zoom_in_action,
            None,
            self.fullscreen_action,
            self.close_action,
        ):
            if action is None:
                separator = QFrame(self.toolbar_overlay)
                separator.setFrameShape(QFrame.Shape.VLine)
                separator.setStyleSheet(
                    "color: rgba(255, 255, 255, 45); margin: 5px 3px;"
                )
                layout.addWidget(separator)
                continue

            button = QToolButton(self.toolbar_overlay)
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            shortcut = action.shortcut().toString()
            button.setToolTip(
                f"{action.text()} ({shortcut})" if shortcut else action.text()
            )
            layout.addWidget(button)

        self.toolbar_overlay.adjustSize()
        self.toolbar_overlay.raise_()
        self._position_toolbar()

    def _position_toolbar(self) -> None:
        if not hasattr(self, "toolbar_overlay"):
            return
        self.toolbar_overlay.adjustSize()
        viewport_width = self.view.viewport().width()
        x = max(8, (viewport_width - self.toolbar_overlay.width()) // 2)
        self.toolbar_overlay.move(x, 12)
        self.toolbar_overlay.raise_()

    def toggle_toolbar(self) -> None:
        if self.isFullScreen():
            visible = not self.toolbar_overlay.isVisible()
            self._fullscreen_toolbar_pinned = visible
            self._set_toolbar_visible(visible)
            return

        self._toolbar_windowed_visible = not self.toolbar_overlay.isVisible()
        self._set_toolbar_visible(self._toolbar_windowed_visible)

    def _set_toolbar_visible(self, visible: bool) -> None:
        self._toolbar_hide_timer.stop()
        self.toolbar_overlay.setVisible(visible)
        if visible:
            self._position_toolbar()

    def _schedule_toolbar_hide(self) -> None:
        if (
            self.isFullScreen()
            and self._fullscreen_toolbar_pinned is None
            and not self._toolbar_hovered
        ):
            self._toolbar_hide_timer.start()

    def _auto_hide_toolbar(self) -> None:
        if (
            self.isFullScreen()
            and self._fullscreen_toolbar_pinned is None
            and not self._toolbar_hovered
        ):
            self.toolbar_overlay.hide()

    def eventFilter(self, watched, event: QEvent) -> bool:
        if watched is self.toolbar_overlay:
            if event.type() == QEvent.Type.Enter:
                self._toolbar_hovered = True
                self._toolbar_hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                self._toolbar_hovered = False
                self._schedule_toolbar_hide()

        if event.type() == QEvent.Type.MouseMove and self.isFullScreen():
            if self._fullscreen_toolbar_pinned is None:
                position = event.position()
                if watched is not self.view.viewport():
                    position = self.view.viewport().mapFromGlobal(
                        watched.mapToGlobal(position.toPoint())
                    )
                if position.y() <= 72:
                    self._set_toolbar_visible(True)
                self._schedule_toolbar_hide()

        return super().eventFilter(watched, event)

    def load_current_image(self) -> None:
        path = self.current_path
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.view.clear_image()
            self.resolution_label.clear()
            QMessageBox.warning(
                self,
                "Unable to preview image",
                f'Could not load "{path.name}".\n\n{reader.errorString()}',
            )
        else:
            self.view.set_pixmap(QPixmap.fromImage(image))
            self.resolution_label.setText(f"{image.width()} × {image.height()}")

        self.setWindowTitle(f"{path.name} — metaView Preview")
        self.filename_label.setText(str(path))
        self.position_label.setText(f"{self.index + 1} of {len(self.paths)}")
        self.previous_action.setEnabled(self.index > 0)
        self.first_action.setEnabled(self.index > 0)
        self.next_action.setEnabled(self.index < len(self.paths) - 1)
        self.last_action.setEnabled(self.index < len(self.paths) - 1)

    def show_previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.load_current_image()

    def show_next(self) -> None:
        if self.index < len(self.paths) - 1:
            self.index += 1
            self.load_current_image()

    def show_first(self) -> None:
        if self.paths:
            self.index = 0
            self.load_current_image()

    def show_last(self) -> None:
        if self.paths:
            self.index = len(self.paths) - 1
            self.load_current_image()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            if self._was_maximized:
                self.showMaximized()
            self.statusBar().show()
            self._fullscreen_toolbar_pinned = None
            self._set_toolbar_visible(self._toolbar_windowed_visible)
            return

        self._was_maximized = self.isMaximized()
        self.statusBar().hide()
        self._fullscreen_toolbar_pinned = None
        self.showFullScreen()
        self._set_toolbar_visible(True)
        self._schedule_toolbar_hide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_toolbar()

    def closeEvent(self, event) -> None:
        self.settings.setValue("preview/geometry", self.saveGeometry())
        self.settings.setValue("preview/toolbar_visible", self._toolbar_windowed_visible)
        self.settings.sync()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.toggle_fullscreen()
            else:
                self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def _update_zoom_label(self, percentage: int) -> None:
        self.zoom_label.setText(f"{percentage}%" if percentage else "")
