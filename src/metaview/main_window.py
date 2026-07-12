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
    QMenu,
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
from .dialogs import (
    ComparisonDialog, ExperimentDialog, ImageRatingsDatabase,
    SimilaritySearchDialog, image_resolution, lora_signature,
    normalised_prompt, rating_text,
)
from .metadata import (
    display_json, extract_summary, read_image_metadata,
    model_display_name, thumbnail_cache_path,
)
from .widgets import ImageDragListWidget, MetadataPanel
from .prompt_library import (
    ImageIndexService,
    Prompt,
    PromptEditorDialog,
    PromptLibraryController,
    PromptLibraryDialog,
    SQLiteImageIndexRepository,
    SQLitePromptRepository,
    import_legacy_prompt_library,
)
from .workers import MetadataWorker, ThumbnailWorker
from .experiments import ExperimentService, SQLiteExperimentRepository, AnalysedImage, analyse_images
from .experiments.ui import CreateExperimentDialog, ExperimentSummaryDialog

def legacy_prompt_library_database_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "prompt_library.sqlite3"


def prompt_library_database_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "prompt_library_v2.sqlite3"


def image_index_database_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "image_index.sqlite3"

def experiment_database_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "experiments.sqlite3"



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
        self.prompt_repository = SQLitePromptRepository(
            prompt_library_database_path()
        )
        import_legacy_prompt_library(
            legacy_prompt_library_database_path(),
            self.prompt_repository,
        )
        self.image_index = ImageIndexService(
            SQLiteImageIndexRepository(image_index_database_path())
        )
        self.experiment_service = ExperimentService(
            SQLiteExperimentRepository(experiment_database_path())
        )
        self.prompt_library = PromptLibraryController(
            self.prompt_repository,
            self.image_index,
            self,
        )
        self.prompt_view_state: dict[str, Any] | None = None
        self.prompt_view_paths: list[Path] | None = None
        self.prompt_view_title = ""
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
        self.image_list.itemSelectionChanged.connect(self.thumbnail_selection_changed)
        self.image_list.verticalScrollBar().valueChanged.connect(self.schedule_visible_thumbnail_load)
        self.image_list.horizontalScrollBar().valueChanged.connect(self.schedule_visible_thumbnail_load)
        self.image_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_list.customContextMenuRequested.connect(self.show_thumbnail_context_menu)

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

        self.prompt_view_bar = QFrame()
        self.prompt_view_bar.setFrameShape(QFrame.Shape.StyledPanel)
        self.prompt_view_bar.setVisible(False)
        prompt_view_layout = QHBoxLayout(self.prompt_view_bar)
        prompt_view_layout.setContentsMargins(8, 5, 8, 5)
        self.prompt_view_label = QLabel()
        self.return_prompt_view_button = QPushButton("Return to previous view")
        self.return_prompt_view_button.clicked.connect(self.return_from_prompt_view)
        prompt_view_layout.addWidget(self.prompt_view_label, 1)
        prompt_view_layout.addWidget(self.return_prompt_view_button)
        panel_layout.addWidget(self.prompt_view_bar)
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
        self.metadata_panel = MetadataPanel(
            self.export_workflow_for_image,
            self.add_prompt_to_library,
        )

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

        self.create_experiment_button = QPushButton("Create Experiment")
        self.create_experiment_button.setEnabled(False)
        self.create_experiment_button.clicked.connect(self.create_experiment_from_selection)

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
        action_layout.addStretch(1)
        action_layout.addWidget(self.rating_label)
        for button in self.rating_buttons:
            action_layout.addWidget(button)
        action_layout.addWidget(self.clear_rating_button)
        action_layout.addSpacing(12)
        action_layout.addWidget(self.find_similar_button)
        action_layout.addWidget(self.experiment_view_button)
        action_layout.addWidget(self.create_experiment_button)
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
        library_action = QAction("Prompt library", self)
        library_action.setShortcut("Ctrl+L")
        library_action.triggered.connect(self.open_prompt_library)
        toolbar.addAction(library_action)
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
            self.load_directory(
                self.current_directory,
                preserve_state=True,
                image_paths=self.prompt_view_paths,
            )

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
            self.clear_prompt_view_state()
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
            self.clear_prompt_view_state()
            self.load_directory(path)

    def refresh_directory(self) -> None:
        if self.current_directory:
            self.load_directory(
                self.current_directory,
                preserve_state=True,
                image_paths=self.prompt_view_paths,
            )

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

    def load_directory(
        self,
        directory: Path,
        preserve_state: bool = False,
        image_paths: list[Path] | None = None,
    ) -> None:
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
        if image_paths is None:
            self.watch_directory(directory)
            self.folder_label.setText(str(directory))
        else:
            watched = self.file_watcher.directories()
            if watched:
                self.file_watcher.removePaths(watched)
            self.folder_label.setText(
                f"Prompt Library — {self.prompt_view_title} ({len(image_paths)} images)"
            )
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
        self.update_rating_controls(0, enabled=False)
        self.similarity_matches = None
        self.similarity_reference = None
        self.similarity_criteria = {}
        self.preview.clear()
        self.preview.setText("Select an image")
        self.cache_hits = 0
        self.generated_thumbnails = 0

        try:
            if image_paths is None:
                image_paths = self.sorted_image_paths(directory)
                self.image_index.prune_directory(directory, image_paths)
            else:
                image_paths = sorted(
                    [path for path in image_paths if path.is_file()],
                    key=self.sort_key_for_path,
                    reverse=self.current_sort_mode() == "filename_desc",
                )
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
        modified_ns: int,
        file_size: int,
    ) -> None:
        self.image_index.index_metadata(
            Path(path_string),
            positive_prompt,
            modified_ns,
            file_size,
        )
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
            self.create_experiment_button.setEnabled(False)
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

        message = (
            f"{path.name} — {rating_text(rating)} — ComfyUI metadata found"
            if "prompt" in metadata or "workflow" in metadata
            else f"{path.name} — {rating_text(rating)} — no ComfyUI metadata found"
        )
        self.statusBar().showMessage(message)


    def selected_image_path(self) -> Path | None:
        """Return the current selected thumbnail path without relying on cached state."""
        current = self.image_list.currentItem()
        if current is None:
            selected = self.image_list.selectedItems()
            current = selected[-1] if selected else None
        if current is None:
            return None
        path_value = current.data(PATH_ROLE)
        if not isinstance(path_value, str):
            return None
        return Path(path_value)

    def update_rating_controls(self, rating: int, enabled: bool = True) -> None:
        value = max(0, min(5, int(rating)))
        for index, button in enumerate(self.rating_buttons, start=1):
            button.setText("★" if index <= value else "☆")
            button.setEnabled(enabled)
        self.clear_rating_button.setEnabled(enabled and value > 0)
        self.rating_label.setEnabled(enabled)

    def set_current_rating(self, rating: int) -> None:
        path = self.selected_image_path()
        if path is None:
            QMessageBox.information(
                self,
                "Select an image",
                "Select a thumbnail before setting its rating.",
            )
            return
        self.current_image_path = path
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

    def capture_browser_state(self) -> dict[str, Any]:
        current_item = self.image_list.currentItem()
        return {
            "directory": self.current_directory,
            "filename_search": self.filename_search_box.text(),
            "prompt_search": self.prompt_search_box.text(),
            "model": self.active_model,
            "sampler": self.active_sampler,
            "scheduler": self.active_scheduler,
            "rating_filter": self.active_rating_filter,
            "sort_mode": self.current_sort_mode(),
            "selected": [
                str(item.data(PATH_ROLE))
                for item in self.image_list.selectedItems()
                if isinstance(item.data(PATH_ROLE), str)
            ],
            "current": (
                str(current_item.data(PATH_ROLE))
                if current_item is not None
                and isinstance(current_item.data(PATH_ROLE), str)
                else None
            ),
            "scroll": self.image_list.verticalScrollBar().value(),
        }

    def clear_prompt_view_state(self) -> None:
        """Leave any temporary prompt or similarity-results view."""
        self.prompt_view_state = None
        self.prompt_view_paths = None
        self.prompt_view_title = ""
        self.similarity_matches = None
        self.similarity_reference = None
        self.similarity_criteria = {}
        if hasattr(self, "prompt_view_bar"):
            self.prompt_view_bar.setVisible(False)

    def enter_prompt_view(self, prompt: Prompt) -> None:
        paths = self.image_index.matching_paths(prompt)
        if not paths:
            QMessageBox.information(
                self,
                "No matching images",
                "No indexed images currently use this exact prompt.",
            )
            return
        if self.prompt_view_state is None:
            self.prompt_view_state = self.capture_browser_state()
        self.similarity_matches = None
        self.similarity_reference = None
        self.similarity_criteria = {}
        self.prompt_view_paths = paths
        self.prompt_view_title = prompt.title
        self.prompt_view_label.setText(
            f'Currently viewing images relating to prompt "{prompt.title}"'
        )
        self.prompt_view_bar.setVisible(True)
        self.filename_search_box.clear()
        self.prompt_search_box.clear()
        self.rating_filter_combo.setCurrentIndex(
            self.rating_filter_combo.findData("all")
        )
        self.load_directory(paths[0].parent, image_paths=paths)

    def return_from_prompt_view(self) -> None:
        """Restore the browser state captured before a temporary results view."""
        state = self.prompt_view_state
        self.prompt_view_paths = None
        self.prompt_view_title = ""
        self.similarity_matches = None
        self.similarity_reference = None
        self.similarity_criteria = {}
        self.prompt_view_bar.setVisible(False)
        self.prompt_view_state = None
        if not state:
            return
        directory = state.get("directory")
        if not isinstance(directory, Path) or not directory.is_dir():
            return
        sort_index = self.sort_combo.findData(state.get("sort_mode"))
        if sort_index >= 0:
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(sort_index)
            self.sort_combo.blockSignals(False)
        rating_index = self.rating_filter_combo.findData(
            state.get("rating_filter", "all")
        )
        if rating_index >= 0:
            self.rating_filter_combo.blockSignals(True)
            self.rating_filter_combo.setCurrentIndex(rating_index)
            self.rating_filter_combo.blockSignals(False)
            self.active_rating_filter = str(
                self.rating_filter_combo.currentData() or "all"
            )
        self.load_directory(directory)
        self.filename_search_box.setText(str(state.get("filename_search", "")))
        self.prompt_search_box.setText(str(state.get("prompt_search", "")))
        self.pending_filter_restore = {
            "model": str(state.get("model", "All")),
            "sampler": str(state.get("sampler", "All")),
            "scheduler": str(state.get("scheduler", "All")),
        }
        self.active_model = self.pending_filter_restore["model"]
        self.active_sampler = self.pending_filter_restore["sampler"]
        self.active_scheduler = self.pending_filter_restore["scheduler"]
        selected = {str(path) for path in state.get("selected", [])}
        for path_string in selected:
            item = self.thumbnail_items.get(path_string)
            if item is not None:
                item.setSelected(True)
        current_path = state.get("current")
        if isinstance(current_path, str):
            item = self.thumbnail_items.get(current_path)
            if item is not None:
                self.image_list.setCurrentItem(item)
        QTimer.singleShot(
            0,
            lambda: self.image_list.verticalScrollBar().setValue(
                int(state.get("scroll", 0))
            ),
        )

    def add_prompt_to_library(
        self,
        positive_prompt: str,
        negative_prompt: str,
        source_image: Path | None,
    ) -> None:
        existing = self.prompt_repository.find_exact(positive_prompt)
        if existing is not None:
            answer = QMessageBox.question(
                self,
                "Prompt already in library",
                f'This exact prompt is already saved as "{existing.title}". '
                "Open it for editing?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                PromptEditorDialog(
                    self.prompt_library,
                    prompt=existing,
                    parent=self,
                ).exec()
            return
        dialog = PromptEditorDialog(
            self.prompt_library,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            source_image=source_image,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("Prompt saved to library", 4000)

    def open_prompt_library(self) -> None:
        self.image_index.remove_missing()
        dialog = PromptLibraryDialog(self.prompt_library, self)
        dialog.browse_requested.connect(self.enter_prompt_view)
        dialog.exec()

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

        if self.prompt_view_state is None:
            self.prompt_view_state = self.capture_browser_state()
        self.prompt_view_paths = None
        self.prompt_view_title = ""
        self.similarity_matches = matching_paths
        self.similarity_reference = reference
        self.similarity_criteria = criteria
        self.prompt_view_label.setText(
            f'Currently showing similarity search results for "{reference.name}"'
        )
        self.prompt_view_bar.setVisible(True)
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


    def selected_image_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self.image_list.selectedItems():
            value = item.data(PATH_ROLE)
            if isinstance(value, str):
                paths.append(Path(value))
        return paths

    def show_thumbnail_context_menu(self, position: QPoint) -> None:
        item = self.image_list.itemAt(position)
        if item is not None and not item.isSelected():
            self.image_list.clearSelection()
            item.setSelected(True)
            self.image_list.setCurrentItem(item)
        selected = self.selected_image_paths()
        if not selected:
            return
        menu = QMenu(self.image_list)
        compare_action = menu.addAction("Compare…")
        compare_action.setEnabled(len(selected) == 2)
        compare_action.triggered.connect(self.compare_selected_images)
        similar_action = menu.addAction("Find Similar…")
        similar_action.setEnabled(len(selected) == 1)
        similar_action.triggered.connect(self.find_similar_images)
        menu.addSeparator()
        create_action = menu.addAction("Create Experiment…")
        create_action.triggered.connect(self.create_experiment_from_selection)
        menu.exec(self.image_list.viewport().mapToGlobal(position))

    def create_experiment_from_selection(self) -> None:
        paths = self.selected_image_paths()
        if not paths:
            QMessageBox.information(self, "Select images", "Select one or more thumbnails to create an experiment.")
            return
        notebooks = self.experiment_service.repository.list_notebooks()
        dialog = CreateExperimentDialog(notebooks, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            notebook = (
                self.experiment_service.create_notebook(dialog.notebook_title)
                if dialog.notebook_id is None
                else self.experiment_service.repository.get_notebook(dialog.notebook_id)
            )
            if notebook is None or notebook.id is None:
                raise RuntimeError("The selected notebook is no longer available")
            aggregate = self.experiment_service.create_experiment_from_images(
                notebook.id, dialog.title, paths, description=dialog.experiment_description
            )
            analysed = []
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for path in paths:
                    metadata = read_image_metadata(path)
                    analysed.append(AnalysedImage(path, metadata, extract_summary(metadata)))
            finally:
                QApplication.restoreOverrideCursor()
            analysis = analyse_images(analysed)
        except Exception as exc:
            QMessageBox.critical(self, "Could not create experiment", str(exc))
            return
        self.statusBar().showMessage(
            f"Created experiment '{aggregate.experiment.title}' with {len(paths)} run{'s' if len(paths) != 1 else ''}",
            5000,
        )
        ExperimentSummaryDialog(notebook, aggregate, analysis, self).exec()

    def thumbnail_selection_changed(self) -> None:
        """Refresh selection-dependent actions for any thumbnail selection change."""
        self.update_compare_button()
        selected = self.image_list.selectedItems()
        if not selected:
            self.open_image_button.setEnabled(False)
            self.find_similar_button.setEnabled(False)
            self.experiment_view_button.setEnabled(False)
            self.create_experiment_button.setEnabled(False)
            self.update_rating_controls(0, enabled=False)
            return

        current = self.image_list.currentItem()
        if current is None or current not in selected:
            current = selected[-1]
            self.image_list.setCurrentItem(current)

        path_value = current.data(PATH_ROLE)
        if not isinstance(path_value, str):
            return
        if self.current_image_path != Path(path_value):
            self.image_selected(current, None)

        # Experiment View is defined around one unambiguous starting image.
        # It must not remain enabled when a multi-selection is active.
        self.experiment_view_button.setEnabled(len(selected) == 1)
        self.create_experiment_button.setEnabled(bool(selected))

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
        path = self.selected_image_path()
        if path is None:
            QMessageBox.information(
                self,
                "Select an image",
                "Select a thumbnail before opening an image.",
            )
            return
        self.current_image_path = path
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if not opened:
            QMessageBox.warning(
                self,
                "Unable to open image",
                "The operating system could not open the selected image. "
                "On Arch Linux, install an image viewer and set it as the "
                "default application for this image type.",
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
            return workflow_path.resolve()
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
        self.prompt_repository.close()
        self.image_index.close()
        self.experiment_service.close()
        super().closeEvent(event)




