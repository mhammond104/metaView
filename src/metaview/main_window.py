from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import (
    QDir,
    QFile,
    QFileSystemWatcher,
    QPoint,
    QProcess,
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
    QActionGroup,
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
    QInputDialog,
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
from .widgets import CollectionListWidget, ImageDragListWidget, MetadataPanel
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
from .preview import PreviewWindow
from .theme import THEMES, apply_theme, current_theme_key
from .experiments import ExperimentService, SQLiteExperimentRepository, AnalysedImage, analyse_images
from .collections import Collection, CollectionRepository
from .smart_collections import SmartCollectionRepository, evaluate_indexed_smart_collection
from .smart_collection_ui import SmartCollectionDialog
from .experiments.ui import (
    CreateExperimentDialog,
    ExperimentNotebookDialog,
    ExperimentSummaryDialog,
)

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

def collection_database_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    directory = Path(base or (Path.home() / ".metaview"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "collections.sqlite3"


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
        self.collection_repository = CollectionRepository(collection_database_path())
        self.smart_collection_repository = SmartCollectionRepository(collection_database_path())
        self.active_collection_id: int | None = None
        self.active_smart_collection_id: int | None = None
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
        self.preview_window: PreviewWindow | None = None
        self.index_scan_total = 0
        self.index_scan_completed = 0
        self.index_scan_generation = 0

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

        self.setWindowTitle("metaView GenAI Image and Experiment Manager")
        self.setWindowIcon(QApplication.instance().windowIcon())
        self.resize(1500, 900)
        self.create_directory_tree()
        self.create_thumbnail_list()
        self.create_preview()
        self.create_layout()
        self.create_toolbar()
        self.create_menus()
        self.index_status_label = QLabel("Index: ready")
        self.index_status_label.setObjectName("indexStatusLabel")
        self.statusBar().addPermanentWidget(self.index_status_label)
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
        self.image_list.itemDoubleClicked.connect(self.preview_thumbnail_from_item)
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
        self.thumbnail_panel.setObjectName("thumbnailPanel")
        panel_layout = QVBoxLayout(self.thumbnail_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(2)
        search_row = QWidget()
        search_row.setObjectName("searchRow")
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(3)
        search_layout.addWidget(self.filename_search_box)
        search_layout.addWidget(self.prompt_search_box)
        search_layout.addWidget(QLabel("Sort:"))
        search_layout.addWidget(self.sort_combo)
        search_layout.addWidget(QLabel("Rating:"))
        search_layout.addWidget(self.rating_filter_combo)

        self.prompt_view_bar = QFrame()
        self.prompt_view_bar.setObjectName("promptViewBar")
        self.prompt_view_bar.setFrameShape(QFrame.Shape.StyledPanel)
        self.prompt_view_bar.setVisible(False)
        prompt_view_layout = QHBoxLayout(self.prompt_view_bar)
        prompt_view_layout.setContentsMargins(6, 3, 6, 3)
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
        self.preview.setObjectName("mainImagePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(400, 300)
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

        self.collection_list = CollectionListWidget()
        self.collection_list.setObjectName("collectionList")
        self.collection_list.setMaximumHeight(220)
        self.collection_list.itemClicked.connect(self.collection_activated)
        self.collection_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.collection_list.customContextMenuRequested.connect(self.show_collection_context_menu)
        self.collection_list.imagesDropped.connect(self.add_dropped_images_to_collection)

        collection_header = QFrame()
        collection_header.setObjectName("collectionHeader")
        collection_header_layout = QHBoxLayout(collection_header)
        collection_header_layout.setContentsMargins(4, 2, 4, 2)
        collection_header_layout.addWidget(QLabel("Collections"), 1)
        new_collection_button = QToolButton()
        new_collection_button.setText("+")
        new_collection_button.setToolTip("Create collection")
        new_collection_button.clicked.connect(self.create_collection)
        collection_header_layout.addWidget(new_collection_button)

        navigation_panel = QWidget()
        navigation_layout = QVBoxLayout(navigation_panel)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(3)
        folders_label = QLabel("Folders")
        folders_label.setObjectName("sectionLabel")
        navigation_layout.addWidget(folders_label)
        navigation_layout.addWidget(self.directory_tree, 1)
        navigation_layout.addWidget(collection_header)
        navigation_layout.addWidget(self.collection_list)

        self.smart_collection_list = QListWidget()
        self.smart_collection_list.setObjectName("smartCollectionList")
        self.smart_collection_list.setMaximumHeight(180)
        self.smart_collection_list.itemClicked.connect(self.smart_collection_activated)
        self.smart_collection_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.smart_collection_list.customContextMenuRequested.connect(self.show_smart_collection_context_menu)

        smart_header = QFrame()
        smart_header.setObjectName("collectionHeader")
        smart_header_layout = QHBoxLayout(smart_header)
        smart_header_layout.setContentsMargins(4, 2, 4, 2)
        smart_header_layout.addWidget(QLabel("Smart Collections"), 1)
        new_smart_button = QToolButton()
        new_smart_button.setText("+")
        new_smart_button.setToolTip("Create smart collection")
        new_smart_button.clicked.connect(self.create_smart_collection)
        smart_header_layout.addWidget(new_smart_button)

        navigation_layout.addWidget(smart_header)
        navigation_layout.addWidget(self.smart_collection_list)
        self.refresh_collections()
        self.refresh_smart_collections()

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(navigation_panel)
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

        self.experiment_notebook_button = QPushButton("Experiment Notebook")
        self.experiment_notebook_button.setObjectName("primaryAction")
        self.experiment_notebook_button.clicked.connect(self.open_experiment_notebook)

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

        action_strip = QFrame()
        action_strip.setObjectName("mainActionStrip")
        action_layout = QHBoxLayout(action_strip)
        action_layout.setContentsMargins(7, 4, 7, 4)
        action_layout.setSpacing(3)
        action_layout.addStretch(1)
        action_layout.addWidget(self.rating_label)
        for button in self.rating_buttons:
            action_layout.addWidget(button)
        action_layout.addWidget(self.clear_rating_button)
        action_layout.addSpacing(12)
        action_layout.addWidget(self.find_similar_button)
        action_layout.addWidget(self.experiment_view_button)
        action_layout.addWidget(self.create_experiment_button)
        action_layout.addWidget(self.experiment_notebook_button)
        action_layout.addWidget(self.compare_button)
        action_layout.addWidget(self.open_image_button)

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.main_splitter, 1)
        central_layout.addWidget(action_strip)
        self.setCentralWidget(central_widget)

    def create_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.open_folder_action = QAction("Open Folder…", self)
        self.open_folder_action.setShortcut("Ctrl+O")
        self.open_folder_action.triggered.connect(self.choose_directory)
        toolbar.addAction(self.open_folder_action)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_directory)
        toolbar.addAction(self.refresh_action)

        self.preview_action = QAction("Preview", self)
        self.preview_action.setShortcut("Space")
        self.preview_action.triggered.connect(self.preview_selected_image)
        self.addAction(self.preview_action)

        self.prompt_library_action = QAction("Prompt Library", self)
        self.prompt_library_action.setShortcut("Ctrl+L")
        self.prompt_library_action.triggered.connect(self.open_prompt_library)
        toolbar.addAction(self.prompt_library_action)

        self.experiment_notebook_action = QAction("Experiment Notebook", self)
        self.experiment_notebook_action.setShortcut("Ctrl+E")
        self.experiment_notebook_action.triggered.connect(self.open_experiment_notebook)
        toolbar.addAction(self.experiment_notebook_action)

        self.rating_actions: list[QAction] = []
        for rating in range(6):
            rating_action = QAction(f"Set rating {rating}", self)
            rating_action.setShortcut(f"Ctrl+{rating}")
            rating_action.triggered.connect(
                lambda _checked=False, value=rating: self.set_current_rating(value)
            )
            self.addAction(rating_action)
            self.rating_actions.append(rating_action)

        toolbar.addSeparator()
        self.folder_label = QLabel("No folder selected")
        toolbar.addWidget(self.folder_label)

    def create_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.clear()
        menu_bar.setNativeMenuBar(False)

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.open_folder_action)
        file_menu.addAction(self.refresh_action)
        file_menu.addSeparator()
        file_menu.addAction(self.prompt_library_action)
        file_menu.addAction(self.experiment_notebook_action)
        file_menu.addSeparator()
        new_collection_action = QAction("New &Collection…", self)
        new_collection_action.setShortcut("Ctrl+Shift+N")
        new_collection_action.triggered.connect(self.create_collection)
        file_menu.addAction(new_collection_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit metaView", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("Close metaView")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menu_bar.addMenu("&Edit")
        copy_path_action = QAction("Copy Image &Path", self)
        copy_path_action.setShortcut("Ctrl+Shift+C")
        copy_path_action.setStatusTip("Copy the selected image path to the clipboard")
        copy_path_action.triggered.connect(self.copy_selected_image_path)
        edit_menu.addAction(copy_path_action)

        copy_prompt_action = QAction("Copy &Positive Prompt", self)
        copy_prompt_action.setShortcut("Ctrl+Shift+P")
        copy_prompt_action.triggered.connect(self.copy_selected_positive_prompt)
        edit_menu.addAction(copy_prompt_action)

        copy_negative_action = QAction("Copy &Negative Prompt", self)
        copy_negative_action.setShortcut("Ctrl+Shift+N")
        copy_negative_action.triggered.connect(self.copy_selected_negative_prompt)
        edit_menu.addAction(copy_negative_action)

        edit_menu.addSeparator()
        rating_menu = edit_menu.addMenu("Set &Rating")
        for rating in range(1, 6):
            action = self.rating_actions[rating]
            action.setText(f"{rating} star" + ("" if rating == 1 else "s"))
            rating_menu.addAction(action)
        self.rating_actions[0].setText("Clear rating")
        rating_menu.addSeparator()
        rating_menu.addAction(self.rating_actions[0])

        image_menu = menu_bar.addMenu("&Image")
        image_menu.addAction(self.preview_action)
        open_image_action = QAction("Open in System &Viewer", self)
        open_image_action.setShortcut("Ctrl+Return")
        open_image_action.setStatusTip("Open the selected image in the operating system viewer")
        open_image_action.triggered.connect(self.open_selected_image)
        image_menu.addAction(open_image_action)

        reveal_action = QAction(self.file_manager_action_label(), self)
        reveal_action.setStatusTip("Reveal the selected image in the file manager")
        reveal_action.triggered.connect(self.show_selected_image_in_file_manager)
        image_menu.addAction(reveal_action)

        image_menu.addSeparator()
        similar_action = QAction("Find &Similar…", self)
        similar_action.setShortcut("Ctrl+Shift+F")
        similar_action.triggered.connect(self.find_similar_images)
        image_menu.addAction(similar_action)

        image_menu.addSeparator()
        trash_action = QAction("Move to &Trash…", self)
        trash_action.setShortcut("Delete")
        trash_action.triggered.connect(self.move_selected_image_to_trash)
        image_menu.addAction(trash_action)

        self.collection_menu = menu_bar.addMenu("&Collection")
        self.collection_menu.aboutToShow.connect(self.populate_collection_menu)

        experiment_menu = menu_bar.addMenu("E&xperiment")
        experiment_menu.addAction(self.experiment_notebook_action)
        experiment_menu.addSeparator()

        compare_action = QAction("&Compare Selected Images…", self)
        compare_action.setShortcut("Ctrl+Shift+M")
        compare_action.triggered.connect(self.compare_selected_images)
        experiment_menu.addAction(compare_action)

        experiment_view_action = QAction("Open Experiment &View", self)
        experiment_view_action.triggered.connect(self.open_experiment_view)
        experiment_menu.addAction(experiment_view_action)

        experiment_menu.addSeparator()
        create_action = QAction("Create &New Experiment…", self)
        create_action.setShortcut("Ctrl+Shift+E")
        create_action.triggered.connect(self.create_experiment_from_selection)
        experiment_menu.addAction(create_action)

        add_action = QAction("&Add Selection to Experiment…", self)
        add_action.triggered.connect(self.add_selection_to_experiment)
        experiment_menu.addAction(add_action)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.refresh_action)
        view_menu.addSeparator()

        theme_menu = view_menu.addMenu("&Theme")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        current = current_theme_key()
        light_separator_added = False
        for key, theme in THEMES.items():
            if theme.light and not light_separator_added:
                theme_menu.addSeparator()
                light_separator_added = True
            action = QAction(theme.name, self, checkable=True)
            action.setData(key)
            action.setChecked(key == current)
            action.triggered.connect(
                lambda _checked=False, theme_key=key: self.set_application_theme(theme_key)
            )
            self.theme_action_group.addAction(action)
            theme_menu.addAction(action)

        help_menu = menu_bar.addMenu("&Help")
        shortcuts_action = QAction("&Keyboard Shortcuts", self)
        shortcuts_action.setShortcut("F1")
        shortcuts_action.triggered.connect(self.show_keyboard_shortcuts)
        help_menu.addAction(shortcuts_action)
        help_menu.addSeparator()
        about_action = QAction("&About metaView", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def populate_collection_menu(self) -> None:
        self.collection_menu.clear()
        new_action = self.collection_menu.addAction("New Collection…")
        new_action.setShortcut("Ctrl+Shift+N")
        new_action.triggered.connect(self.create_collection)
        new_smart_action = self.collection_menu.addAction("New Smart Collection…")
        new_smart_action.triggered.connect(self.create_smart_collection)

        add_menu = self.collection_menu.addMenu("Add Selection to Collection")
        selected = bool(self.selected_image_paths())
        collections = self.collection_repository.list()
        for collection in collections:
            action = add_menu.addAction(collection.name)
            action.setEnabled(selected)
            action.triggered.connect(
                lambda _checked=False, collection_id=collection.id: self.add_selection_to_collection(collection_id)
            )
        if not collections:
            empty_action = add_menu.addAction("No collections")
            empty_action.setEnabled(False)

        remove_action = self.collection_menu.addAction("Remove Selection from Collection")
        remove_action.setEnabled(self.active_collection_id is not None and selected)
        remove_action.triggered.connect(self.remove_selection_from_active_collection)

        self.collection_menu.addSeparator()
        if self.active_collection_id is not None:
            collection = self.collection_repository.get(self.active_collection_id)
            rename_action = self.collection_menu.addAction("Rename Current Collection…")
            rename_action.triggered.connect(
                lambda: self.rename_collection(self.active_collection_id)
                if self.active_collection_id is not None else None
            )
            delete_action = self.collection_menu.addAction("Delete Current Collection…")
            delete_action.triggered.connect(
                lambda: self.delete_collection(self.active_collection_id)
                if self.active_collection_id is not None else None
            )
            if collection is not None:
                rename_action.setStatusTip(f'Rename "{collection.name}"')
                delete_action.setStatusTip(f'Delete "{collection.name}" without deleting its images')
        elif self.active_smart_collection_id is not None:
            collection = self.smart_collection_repository.get(self.active_smart_collection_id)
            edit_action = self.collection_menu.addAction("Edit Current Smart Collection…")
            edit_action.triggered.connect(
                lambda: self.edit_smart_collection(self.active_smart_collection_id)
                if self.active_smart_collection_id is not None else None
            )
            refresh_action = self.collection_menu.addAction("Refresh Current Smart Collection")
            refresh_action.triggered.connect(
                lambda: self.open_smart_collection(self.active_smart_collection_id)
                if self.active_smart_collection_id is not None else None
            )
            delete_action = self.collection_menu.addAction("Delete Current Smart Collection…")
            delete_action.triggered.connect(
                lambda: self.delete_smart_collection(self.active_smart_collection_id)
                if self.active_smart_collection_id is not None else None
            )
            if collection is not None:
                edit_action.setStatusTip(f'Edit rules for "{collection.name}"')
        else:
            unavailable = self.collection_menu.addAction("No collection open")
            unavailable.setEnabled(False)

    @staticmethod
    def file_manager_action_label() -> str:
        return {
            "win32": "Reveal in Explorer",
            "darwin": "Reveal in Finder",
        }.get(sys.platform, "Reveal in File Manager")

    def set_application_theme(self, key: str) -> None:
        if key not in THEMES:
            return
        self.settings.setValue("appearance/theme", key)
        self.settings.sync()
        apply_theme(QApplication.instance(), key)
        self.statusBar().showMessage(f"Theme: {THEMES[key].name}", 3000)

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
        layout.setContentsMargins(3, 1, 3, 1)
        layout.setSpacing(3)
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
        layout.setSpacing(4)

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
            view_kind = "Collection" if self.active_collection_id is not None else "Prompt Library"
            self.folder_label.setText(
                f"{view_kind} — {self.prompt_view_title} ({len(image_paths)} images)"
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

        self.index_scan_generation = generation
        self.index_scan_total = len(image_paths)
        self.index_scan_completed = 0
        self.update_index_status()

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

            try:
                stat = path.stat()
                modified_ns = stat.st_mtime_ns
                file_size = stat.st_size
            except OSError:
                modified_ns = 0
                file_size = 0

            indexed = self.image_index.get(path)
            if (
                indexed is not None
                and not self.image_index.needs_refresh(path, modified_ns, file_size)
            ):
                self.apply_indexed_metadata(item, indexed)
                self.index_scan_completed += 1
            else:
                metadata_worker = MetadataWorker(path, generation)
                metadata_worker.signals.loaded.connect(self.model_loaded)
                metadata_worker.signals.failed.connect(self.model_failed)
                self.thread_pool.start(metadata_worker)

        count = len(image_paths)
        if count == 0:
            self.statusBar().showMessage("No images found")
            return

        pending = max(0, self.index_scan_total - self.index_scan_completed)
        self.statusBar().showMessage(
            f"{count} images — " + (f"indexing {pending} metadata record(s)" if pending else "metadata index up to date")
        )
        self.update_index_status()

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

    def update_index_status(self) -> None:
        total = self.index_scan_total
        completed = min(self.index_scan_completed, total)
        if total <= 0 or completed >= total:
            statistics = self.image_index.statistics()
            self.index_status_label.setText(f"Index: {statistics.image_count} images")
            self.index_status_label.setToolTip(
                f"{statistics.image_count} indexed images across {statistics.directory_count} folders"
            )
        else:
            self.index_status_label.setText(f"Indexing: {completed}/{total}")
            self.index_status_label.setToolTip("Generation metadata is being indexed in the background")

    def apply_indexed_metadata(self, item: QListWidgetItem, indexed: object) -> None:
        model = str(getattr(indexed, "model", "") or UNKNOWN_MODEL)
        sampler = str(getattr(indexed, "sampler", "") or UNKNOWN_SAMPLER)
        scheduler = str(getattr(indexed, "scheduler", "") or UNKNOWN_SCHEDULER)
        positive_prompt = str(getattr(indexed, "positive_prompt", ""))
        try:
            loras = json.loads(str(getattr(indexed, "loras_json", "[]")))
        except (TypeError, ValueError, json.JSONDecodeError):
            loras = []
        tooltip_data = {
            "model": model,
            "sampler": sampler,
            "scheduler": scheduler,
            "steps": str(getattr(indexed, "steps", "")),
            "resolution": str(getattr(indexed, "resolution", "")),
            "loras": loras,
        }
        item.setData(MODEL_ROLE, model)
        item.setData(SAMPLER_ROLE, sampler)
        item.setData(SCHEDULER_ROLE, scheduler)
        item.setData(POSITIVE_PROMPT_ROLE, positive_prompt)
        path_string = str(item.data(PATH_ROLE) or "")
        item.setToolTip(self.thumbnail_metadata_tooltip(path_string, tooltip_data))
        self.add_filter_button("model", model)
        self.add_filter_button("sampler", sampler)
        self.add_filter_button("scheduler", scheduler)

    def model_failed(self, path_string: str, error_message: str, generation: int) -> None:
        """Complete a metadata-index task even when one image cannot be parsed."""
        if generation == self.index_scan_generation:
            self.index_scan_completed = min(
                self.index_scan_total, self.index_scan_completed + 1
            )
            self.update_index_status()
            if self.index_scan_completed >= self.index_scan_total:
                self.statusBar().showMessage(
                    f"{self.index_scan_total} images — metadata index complete with errors",
                    5000,
                )
                if self.active_smart_collection_id is not None:
                    smart_id = self.active_smart_collection_id
                    QTimer.singleShot(0, lambda: self.open_smart_collection(smart_id))

        item = self.thumbnail_items.get(path_string)
        if item is not None:
            item.setToolTip(f"{path_string}\nMetadata error: {error_message}")

    def model_loaded(
        self,
        path_string: str,
        model: str,
        sampler: str,
        scheduler: str,
        positive_prompt: str,
        tooltip_data: object,
        generation: int,
        modified_ns: int,
        file_size: int,
    ) -> None:
        self.image_index.index_metadata(
            Path(path_string),
            positive_prompt,
            modified_ns,
            file_size,
            model=model,
            sampler=sampler,
            scheduler=scheduler,
            steps=str(tooltip_data.get("steps", "")) if isinstance(tooltip_data, dict) else "",
            resolution=str(tooltip_data.get("resolution", "")) if isinstance(tooltip_data, dict) else "",
            loras_json=json.dumps(tooltip_data.get("loras", [])) if isinstance(tooltip_data, dict) else "[]",
        )
        if generation == self.index_scan_generation:
            self.index_scan_completed = min(self.index_scan_total, self.index_scan_completed + 1)
            self.update_index_status()
            if self.index_scan_completed >= self.index_scan_total:
                self.statusBar().showMessage(
                    f"{self.index_scan_total} images — metadata index up to date", 3000
                )
                if self.active_smart_collection_id is not None:
                    smart_id = self.active_smart_collection_id
                    QTimer.singleShot(0, lambda: self.open_smart_collection(smart_id))
        if generation != self.thumbnail_generation:
            return

        item = self.thumbnail_items.get(path_string)
        if item is None:
            return

        item.setData(MODEL_ROLE, model)
        item.setData(SAMPLER_ROLE, sampler)
        item.setData(SCHEDULER_ROLE, scheduler)
        item.setData(POSITIVE_PROMPT_ROLE, positive_prompt)
        item.setToolTip(self.thumbnail_metadata_tooltip(path_string, tooltip_data))

        self.add_filter_button("model", model)
        self.add_filter_button("sampler", sampler)
        self.add_filter_button("scheduler", scheduler)

        self.apply_filters()

    @staticmethod
    def thumbnail_metadata_tooltip(path_string: str, tooltip_data: object) -> str:
        """Format metadata shown when hovering over a thumbnail."""
        if not isinstance(tooltip_data, dict):
            return path_string

        lines: list[str] = []
        model = str(tooltip_data.get("model", "") or "").strip()
        sampler = str(tooltip_data.get("sampler", "") or "").strip()
        steps = str(tooltip_data.get("steps", "") or "").strip()
        scheduler = str(tooltip_data.get("scheduler", "") or "").strip()
        resolution = str(tooltip_data.get("resolution", "") or "").strip()

        if model:
            lines.append(f"Model: {model_display_name(model)}")
        if sampler:
            sampler_text = sampler + (f" ({steps} steps)" if steps else "")
            lines.append(f"Sampler: {sampler_text}")
        if scheduler:
            lines.append(f"Scheduler: {scheduler}")
        if resolution:
            lines.append(f"Resolution: {resolution}")

        raw_loras = tooltip_data.get("loras", [])
        loras = raw_loras if isinstance(raw_loras, list) else []
        if loras:
            lines.extend(["", "LoRAs:"])
            maximum_loras = 8
            for lora in loras[:maximum_loras]:
                if not isinstance(lora, dict):
                    continue
                name = Path(str(lora.get("name", "") or "")).name
                model_strength = str(lora.get("model_strength", "") or "").strip()
                clip_strength = str(lora.get("clip_strength", "") or "").strip()
                strength = model_strength
                if clip_strength and clip_strength != model_strength:
                    strength = f"model {model_strength or '—'}, CLIP {clip_strength}"
                lines.append(f"  {name}: {strength}" if strength else f"  {name}")
            remaining = len(loras) - maximum_loras
            if remaining > 0:
                lines.append(f"  …and {remaining} more")

        return "\n".join(lines) if lines else path_string

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
        if self.active_smart_collection_id is not None:
            smart_id = self.active_smart_collection_id
            QTimer.singleShot(0, lambda: self.open_smart_collection(smart_id))
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
        self.active_collection_id = None
        self.active_smart_collection_id = None
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

        preview_action = menu.addAction("Preview")
        preview_action.setEnabled(len(selected) == 1)
        preview_action.triggered.connect(self.preview_selected_image)

        open_action = menu.addAction("Open Image")
        open_action.setEnabled(len(selected) == 1)
        open_action.triggered.connect(self.open_selected_image)

        reveal_label = self.file_manager_action_label()
        reveal_action = menu.addAction(reveal_label)
        reveal_action.setEnabled(len(selected) == 1)
        reveal_action.triggered.connect(self.show_selected_image_in_file_manager)

        copy_path_action = menu.addAction("Copy Path")
        copy_path_action.setEnabled(len(selected) == 1)
        copy_path_action.triggered.connect(self.copy_selected_image_path)

        menu.addSeparator()
        add_collection_menu = menu.addMenu("Add to Collection")
        for collection in self.collection_repository.list():
            action = add_collection_menu.addAction(collection.name)
            action.triggered.connect(
                lambda _checked=False, collection_id=collection.id: self.add_selection_to_collection(collection_id)
            )
        if add_collection_menu.isEmpty():
            empty_action = add_collection_menu.addAction("No collections")
            empty_action.setEnabled(False)
        add_collection_menu.addSeparator()
        new_collection_action = add_collection_menu.addAction("New Collection…")
        new_collection_action.triggered.connect(self.create_collection_from_selection)
        if self.active_collection_id is not None:
            remove_collection_action = menu.addAction("Remove from Collection")
            remove_collection_action.triggered.connect(self.remove_selection_from_active_collection)
        menu.addSeparator()
        compare_action = menu.addAction("Compare…")
        compare_action.setEnabled(len(selected) == 2)
        compare_action.triggered.connect(self.compare_selected_images)
        similar_action = menu.addAction("Find Similar…")
        similar_action.setEnabled(len(selected) == 1)
        similar_action.triggered.connect(self.find_similar_images)
        menu.addSeparator()
        create_action = menu.addAction("Create Experiment…")
        create_action.triggered.connect(self.create_experiment_from_selection)
        menu.addSeparator()
        delete_action = menu.addAction("Move to Trash…")
        delete_action.setEnabled(len(selected) == 1)
        delete_action.triggered.connect(self.move_selected_image_to_trash)
        menu.exec(self.image_list.viewport().mapToGlobal(position))

    def refresh_collections(self) -> None:
        selected_id = None
        current = self.collection_list.currentItem() if hasattr(self, "collection_list") else None
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)
        if not hasattr(self, "collection_list"):
            return
        self.collection_list.clear()
        for collection in self.collection_repository.list():
            count = self.collection_repository.count(collection.id)
            item = QListWidgetItem(f"{collection.name} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, collection.id)
            item.setToolTip(collection.name)
            self.collection_list.addItem(item)
            if collection.id == selected_id:
                self.collection_list.setCurrentItem(item)

    def create_collection(self) -> Collection | None:
        name, accepted = QInputDialog.getText(self, "New Collection", "Collection name:")
        if not accepted:
            return None
        try:
            collection = self.collection_repository.create(name)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to create collection", str(error))
            return None
        self.refresh_collections()
        self.statusBar().showMessage(f'Created collection "{collection.name}"', 3000)
        return collection

    def create_collection_from_selection(self) -> None:
        collection = self.create_collection()
        if collection is not None:
            self.add_selection_to_collection(collection.id)

    def collection_activated(self, item: QListWidgetItem) -> None:
        collection_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(collection_id, int):
            self.open_collection(collection_id)

    def open_collection(self, collection_id: int) -> None:
        collection = self.collection_repository.get(collection_id)
        if collection is None:
            self.refresh_collections()
            return
        paths = self.collection_repository.images(collection_id)
        if self.prompt_view_state is None:
            self.prompt_view_state = self.capture_browser_state()
        self.active_collection_id = collection_id
        self.active_smart_collection_id = None
        self.prompt_view_paths = paths
        self.prompt_view_title = collection.name
        self.prompt_view_label.setText(f'Collection: "{collection.name}" — {len(paths)} image(s)')
        self.prompt_view_bar.setVisible(True)
        base_directory = paths[0].parent if paths else (self.current_directory or Path.home())
        self.load_directory(base_directory, image_paths=paths)
        if not paths:
            self.preview.clear()
            self.preview.setText("This collection is empty.\n\nDrag images onto it or use Add to Collection.")

    def add_selection_to_collection(self, collection_id: int) -> None:
        paths = self.selected_image_paths()
        if not paths:
            return
        added = self.collection_repository.add_images(collection_id, paths)
        self.refresh_collections()
        if self.active_collection_id == collection_id:
            self.open_collection(collection_id)
        self.statusBar().showMessage(f"Added {added} image(s) to collection", 3000)

    def add_dropped_images_to_collection(self, collection_id: int, paths: object) -> None:
        image_paths = [path for path in paths if isinstance(path, Path)] if isinstance(paths, list) else []
        if not image_paths:
            return
        added = self.collection_repository.add_images(collection_id, image_paths)
        self.refresh_collections()
        if self.active_collection_id == collection_id:
            self.open_collection(collection_id)
        self.statusBar().showMessage(f"Added {added} image(s) to collection", 3000)

    def remove_selection_from_active_collection(self) -> None:
        if self.active_collection_id is None:
            return
        paths = self.selected_image_paths()
        removed = self.collection_repository.remove_images(self.active_collection_id, paths)
        collection_id = self.active_collection_id
        self.refresh_collections()
        self.open_collection(collection_id)
        self.statusBar().showMessage(f"Removed {removed} image(s) from collection", 3000)

    def show_collection_context_menu(self, position: QPoint) -> None:
        item = self.collection_list.itemAt(position)
        menu = QMenu(self.collection_list)
        new_action = menu.addAction("New Collection…")
        new_action.triggered.connect(self.create_collection)
        if item is not None:
            collection_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(collection_id, int):
                menu.addSeparator()
                open_action = menu.addAction("Open")
                open_action.triggered.connect(lambda: self.open_collection(collection_id))
                rename_action = menu.addAction("Rename…")
                rename_action.triggered.connect(lambda: self.rename_collection(collection_id))
                delete_action = menu.addAction("Delete Collection…")
                delete_action.triggered.connect(lambda: self.delete_collection(collection_id))
        menu.exec(self.collection_list.viewport().mapToGlobal(position))

    def rename_collection(self, collection_id: int) -> None:
        collection = self.collection_repository.get(collection_id)
        if collection is None:
            return
        name, accepted = QInputDialog.getText(self, "Rename Collection", "Collection name:", text=collection.name)
        if not accepted:
            return
        try:
            self.collection_repository.rename(collection_id, name)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to rename collection", str(error))
            return
        self.refresh_collections()
        if self.active_collection_id == collection_id:
            self.open_collection(collection_id)

    def delete_collection(self, collection_id: int) -> None:
        collection = self.collection_repository.get(collection_id)
        if collection is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Collection?",
            f'Delete collection "{collection.name}"? Image files will not be deleted.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.collection_repository.delete(collection_id)
        if self.active_collection_id == collection_id:
            self.active_collection_id = None
            self.return_from_prompt_view()
        self.refresh_collections()


    def refresh_smart_collections(self) -> None:
        if not hasattr(self, "smart_collection_list"):
            return
        selected_id = None
        current = self.smart_collection_list.currentItem()
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)
        self.smart_collection_list.clear()
        for collection in self.smart_collection_repository.list():
            item = QListWidgetItem(collection.name)
            item.setData(Qt.ItemDataRole.UserRole, collection.id)
            item.setToolTip(
                "All rules must match:\n"
                + "\n".join(
                    f"• {rule.field} {rule.operator.replace('_', ' ')} {rule.value}"
                    for rule in collection.rules
                )
            )
            self.smart_collection_list.addItem(item)
            if collection.id == selected_id:
                self.smart_collection_list.setCurrentItem(item)

    def create_smart_collection(self) -> None:
        dialog = SmartCollectionDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            collection = self.smart_collection_repository.create(
                dialog.collection_name, dialog.rules
            )
        except ValueError as error:
            QMessageBox.warning(self, "Unable to create smart collection", str(error))
            return
        self.refresh_smart_collections()
        self.open_smart_collection(collection.id)

    def edit_smart_collection(self, collection_id: int) -> None:
        collection = self.smart_collection_repository.get(collection_id)
        if collection is None:
            return
        dialog = SmartCollectionDialog(collection, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.smart_collection_repository.update(
                collection_id, dialog.collection_name, dialog.rules
            )
        except ValueError as error:
            QMessageBox.warning(self, "Unable to update smart collection", str(error))
            return
        self.refresh_smart_collections()
        if self.active_smart_collection_id == collection_id:
            self.open_smart_collection(collection_id)

    def delete_smart_collection(self, collection_id: int) -> None:
        collection = self.smart_collection_repository.get(collection_id)
        if collection is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Smart Collection?",
            f'Delete smart collection "{collection.name}"? Image files will not be deleted.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.smart_collection_repository.delete(collection_id)
        if self.active_smart_collection_id == collection_id:
            self.active_smart_collection_id = None
            self.return_from_prompt_view()
        self.refresh_smart_collections()

    def smart_collection_activated(self, item: QListWidgetItem) -> None:
        collection_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(collection_id, int):
            self.open_smart_collection(collection_id)

    def open_smart_collection(self, collection_id: int) -> None:
        collection = self.smart_collection_repository.get(collection_id)
        if collection is None:
            self.refresh_smart_collections()
            return
        if self.prompt_view_state is None:
            self.prompt_view_state = self.capture_browser_state()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            paths = evaluate_indexed_smart_collection(
                collection,
                self.image_index.all_images(),
                self.ratings_database.get,
            )
        finally:
            QApplication.restoreOverrideCursor()
        self.active_collection_id = None
        self.active_smart_collection_id = collection_id
        self.prompt_view_paths = paths
        self.prompt_view_title = collection.name
        self.prompt_view_label.setText(
            f'Smart Collection: "{collection.name}" — {len(paths)} image(s)'
        )
        self.prompt_view_bar.setVisible(True)
        base_directory = paths[0].parent if paths else (self.current_directory or Path.home())
        self.load_directory(base_directory, image_paths=paths)
        if not paths:
            self.preview.clear()
            self.preview.setText("No indexed images currently match this Smart Collection.")

    def show_smart_collection_context_menu(self, position: QPoint) -> None:
        item = self.smart_collection_list.itemAt(position)
        menu = QMenu(self.smart_collection_list)
        new_action = menu.addAction("New Smart Collection…")
        new_action.triggered.connect(self.create_smart_collection)
        if item is not None:
            collection_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(collection_id, int):
                menu.addSeparator()
                open_action = menu.addAction("Open")
                open_action.triggered.connect(lambda: self.open_smart_collection(collection_id))
                edit_action = menu.addAction("Edit Rules…")
                edit_action.triggered.connect(lambda: self.edit_smart_collection(collection_id))
                delete_action = menu.addAction("Delete Smart Collection…")
                delete_action.triggered.connect(lambda: self.delete_smart_collection(collection_id))
        menu.exec(self.smart_collection_list.viewport().mapToGlobal(position))

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
        ExperimentSummaryDialog(self.experiment_service, notebook, aggregate.experiment.id, analysis, self).exec()

    def copy_selected_positive_prompt(self) -> None:
        path = self.selected_image_path()
        if path is None:
            return
        metadata = self.current_metadata if path == self.current_image_path else read_image_metadata(path)
        prompt = extract_summary(metadata).get("positive", "")
        QApplication.clipboard().setText(str(prompt))
        self.statusBar().showMessage("Positive prompt copied", 3000)

    def copy_selected_negative_prompt(self) -> None:
        path = self.selected_image_path()
        if path is None:
            return
        metadata = self.current_metadata if path == self.current_image_path else read_image_metadata(path)
        prompt = extract_summary(metadata).get("negative", "")
        QApplication.clipboard().setText(str(prompt))
        self.statusBar().showMessage("Negative prompt copied", 3000)

    def open_experiment_notebook(self) -> None:
        dialog = ExperimentNotebookDialog(self.experiment_service, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selected_experiment_id is None:
            return
        self.open_existing_experiment(dialog.selected_experiment_id)

    def open_existing_experiment(self, experiment_id: int) -> None:
        try:
            aggregate = self.experiment_service.load_experiment(experiment_id)
            notebook = self.experiment_service.repository.get_notebook(
                aggregate.experiment.notebook_id
            )
            if notebook is None:
                raise RuntimeError("The experiment notebook is no longer available")
            analysed: list[AnalysedImage] = []
            for run in aggregate.runs:
                if run.id is None:
                    continue
                for run_image in aggregate.images_by_run.get(run.id, ()):
                    path = run_image.image_path
                    if path.is_file():
                        metadata = read_image_metadata(path)
                        analysed.append(AnalysedImage(path, metadata, extract_summary(metadata)))
            analysis = analyse_images(analysed)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open experiment", str(exc))
            return
        ExperimentSummaryDialog(
            self.experiment_service, notebook, experiment_id, analysis, self
        ).exec()

    def add_selection_to_experiment(self) -> None:
        paths = self.selected_image_paths()
        if not paths:
            QMessageBox.information(self, "Select images", "Select one or more thumbnails first.")
            return
        choices: list[str] = []
        ids: list[int] = []
        for notebook in self.experiment_service.repository.list_notebooks():
            if notebook.id is None:
                continue
            for experiment in self.experiment_service.repository.list_experiments(notebook.id):
                if experiment.id is not None:
                    choices.append(f"{notebook.title} — {experiment.title}")
                    ids.append(experiment.id)
        if not choices:
            QMessageBox.information(self, "No experiments", "Create an experiment before adding images.")
            return
        choice, accepted = QInputDialog.getItem(
            self, "Add to Experiment", "Experiment:", choices, 0, False
        )
        if not accepted:
            return
        experiment_id = ids[choices.index(choice)]
        try:
            for path in paths:
                run = self.experiment_service.create_run(experiment_id)
                if run.id is not None:
                    self.experiment_service.add_images(run.id, [path])
        except Exception as exc:
            QMessageBox.critical(self, "Could not add images", str(exc))
            return
        self.statusBar().showMessage(
            f"Added {len(paths)} image{'s' if len(paths) != 1 else ''} to experiment", 4000
        )

    def show_keyboard_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "Keyboard Shortcuts",
            "Ctrl+O  Open folder\nSpace  Preview selected image\n"
            "Ctrl+Return  Open in system viewer\nCtrl+E  Experiment Notebook\n"
            "Ctrl+L  Prompt Library\nF5  Refresh\nDelete  Move to Trash",
        )

    def show_about_dialog(self) -> None:
        QMessageBox.about(
            self,
            "About metaView",
            "metaView 0.3.0\n\nGenAI image management, metadata analysis and experimentation.",
        )

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

    def visible_image_paths(self) -> list[Path]:
        """Return image paths in the thumbnail list's current visible order."""
        paths: list[Path] = []
        for row in range(self.image_list.count()):
            item = self.image_list.item(row)
            if item.isHidden():
                continue
            path_value = item.data(PATH_ROLE)
            if isinstance(path_value, str):
                paths.append(Path(path_value))
        return paths

    def preview_image(self, path: Path) -> None:
        """Open the reusable metaView preview window for an image."""
        if not path.is_file():
            QMessageBox.warning(
                self,
                "Image not found",
                f"The image no longer exists:\n\n{path}",
            )
            return

        paths = self.visible_image_paths()
        if path not in paths:
            paths = [path]

        if self.preview_window is not None:
            self.preview_window.close()

        window = PreviewWindow(paths, path, self)
        self.preview_window = window
        window.destroyed.connect(
            lambda _object=None, preview=window: self._clear_preview_window(preview)
        )
        window.show()
        window.raise_()
        window.activateWindow()

    def _clear_preview_window(self, window: PreviewWindow) -> None:
        if self.preview_window is window:
            self.preview_window = None

    def preview_selected_image(self) -> None:
        """Preview the currently selected thumbnail inside metaView."""
        path = self.selected_image_path()
        if path is None:
            QMessageBox.information(
                self,
                "Select an image",
                "Select a thumbnail before opening Preview.",
            )
            return
        self.preview_image(path)

    def open_image(self, path: Path) -> None:
        """Open an image using the operating system's default application."""
        if not path.is_file():
            QMessageBox.warning(
                self,
                "Image not found",
                f"The image no longer exists:\n\n{path}",
            )
            return

        self.current_image_path = path
        opened = QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(path.resolve()))
        )
        if not opened:
            QMessageBox.warning(
                self,
                "Unable to open image",
                "The operating system could not open the selected image.\n\n"
                "Make sure a default application is configured for this "
                "image type.",
            )

    def open_selected_image(self) -> None:
        """Open the currently selected thumbnail in the OS image viewer."""
        path = self.selected_image_path()
        if path is None:
            QMessageBox.information(
                self,
                "Select an image",
                "Select a thumbnail before opening an image.",
            )
            return
        self.open_image(path)

    def preview_thumbnail_from_item(self, item: QListWidgetItem) -> None:
        """Preview the image represented by a double-clicked thumbnail."""
        path_value = item.data(PATH_ROLE)
        if isinstance(path_value, str):
            self.preview_image(Path(path_value))

    def show_selected_image_in_file_manager(self) -> None:
        """Reveal the selected image in the platform file manager."""
        path = self.selected_image_path()
        if path is None:
            return
        if not path.exists():
            QMessageBox.warning(
                self,
                "Image not found",
                f"The image no longer exists:\n\n{path}",
            )
            return

        if sys.platform == "win32":
            opened = QProcess.startDetached(
                "explorer.exe", ["/select,", str(path.resolve())]
            )
        elif sys.platform == "darwin":
            opened = QProcess.startDetached(
                "open", ["-R", str(path.resolve())]
            )
        else:
            opened = self._open_linux_file_manager(path.resolve())

        opened_ok = opened[0] if isinstance(opened, tuple) else bool(opened)
        if not opened_ok:
            QMessageBox.warning(
                self,
                "Unable to open file manager",
                f"The containing folder could not be opened:\n\n{path.parent}",
            )


    @staticmethod
    def _open_linux_file_manager(path: Path) -> bool:
        """Open a real Linux file manager, preferring the active desktop."""
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").casefold()
        session = os.environ.get("DESKTOP_SESSION", "").casefold()
        desktop_hint = f"{desktop} {session}"

        candidates: list[tuple[str, list[str]]] = []

        def add(command: str, arguments: list[str]) -> None:
            if command not in {name for name, _args in candidates}:
                candidates.append((command, arguments))

        if "kde" in desktop_hint or "plasma" in desktop_hint:
            add("dolphin", ["--select", str(path)])
        if "gnome" in desktop_hint or "ubuntu" in desktop_hint:
            add("nautilus", ["--select", str(path)])
        if "xfce" in desktop_hint:
            add("thunar", [str(path.parent)])
        if "cinnamon" in desktop_hint:
            add("nemo", [str(path.parent)])
        if "mate" in desktop_hint:
            add("caja", [str(path.parent)])
        if "lxqt" in desktop_hint:
            add("pcmanfm-qt", [str(path.parent)])
        if "lxde" in desktop_hint:
            add("pcmanfm", [str(path.parent)])

        for command, arguments in (
            ("dolphin", ["--select", str(path)]),
            ("nautilus", ["--select", str(path)]),
            ("nemo", [str(path.parent)]),
            ("thunar", [str(path.parent)]),
            ("caja", [str(path.parent)]),
            ("pcmanfm-qt", [str(path.parent)]),
            ("pcmanfm", [str(path.parent)]),
        ):
            add(command, arguments)

        for command, arguments in candidates:
            if shutil.which(command):
                result = QProcess.startDetached(command, arguments)
                return result[0] if isinstance(result, tuple) else bool(result)

        # Last resort: use the freedesktop portal/handler only when no known
        # graphical file manager is available.
        if shutil.which("xdg-open"):
            result = QProcess.startDetached("xdg-open", [str(path.parent)])
            return result[0] if isinstance(result, tuple) else bool(result)

        return False

    def copy_selected_image_path(self) -> None:
        """Copy the selected image's absolute path to the clipboard."""
        path = self.selected_image_path()
        if path is None:
            return
        QApplication.clipboard().setText(str(path.resolve()))
        self.statusBar().showMessage("Image path copied to clipboard", 3000)

    def move_selected_image_to_trash(self) -> None:
        """Move the selected image to the operating system's trash."""
        path = self.selected_image_path()
        if path is None:
            return
        if not path.is_file():
            QMessageBox.warning(
                self,
                "Image not found",
                f"The image no longer exists:\n\n{path}",
            )
            self.refresh_directory()
            return

        answer = QMessageBox.question(
            self,
            "Move image to Trash?",
            f'Move "{path.name}" to the Trash or Recycle Bin?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        result = QFile.moveToTrash(str(path))
        moved = result[0] if isinstance(result, tuple) else bool(result)
        if not moved:
            QMessageBox.warning(
                self,
                "Unable to move image",
                f"The image could not be moved to Trash:\n\n{path}",
            )
            return

        self.current_image_path = None
        self.current_pixmap = None
        self.current_metadata = {}
        self.preview.clear()
        self.preview.setText("Select an image")
        self.metadata_panel.clear()
        self.open_image_button.setEnabled(False)
        self.find_similar_button.setEnabled(False)
        self.experiment_view_button.setEnabled(False)
        self.statusBar().showMessage(f'Moved "{path.name}" to Trash', 4000)
        self.refresh_directory()

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
        self.collection_repository.close()
        self.smart_collection_repository.close()
        super().closeEvent(event)




