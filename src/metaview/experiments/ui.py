"""Qt user interface for creating and reviewing persistent experiments."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..comparison import compare_loras, compare_parameters
from ..dialogs import CompareImageView
from ..metadata import extract_summary, read_image_metadata
from .analysis import ExperimentAnalysis
from .models import ExperimentAggregate, ExperimentRun, Notebook
from .service import ExperimentService

PATH_ROLE = Qt.ItemDataRole.UserRole
RUN_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class CreateExperimentDialog(QDialog):
    def __init__(self, notebooks: Sequence[Notebook], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Experiment")
        self.resize(520, 330)
        self.notebook_combo = QComboBox()
        self.notebook_combo.addItem("Create a new notebook…", None)
        for notebook in notebooks:
            self.notebook_combo.addItem(notebook.title, notebook.id)
        self.new_notebook_title = QLineEdit()
        self.new_notebook_title.setPlaceholderText("e.g. Krea 2 realism testing")
        self.experiment_title = QLineEdit()
        self.experiment_title.setPlaceholderText("e.g. Euler/Beta steps comparison")
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("What are you testing?")
        self.description.setMaximumHeight(110)
        form = QFormLayout()
        form.addRow("Notebook:", self.notebook_combo)
        form.addRow("New notebook name:", self.new_notebook_title)
        form.addRow("Experiment name:", self.experiment_title)
        form.addRow("Description:", self.description)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        self.notebook_combo.currentIndexChanged.connect(self._update_notebook_field)
        self.experiment_title.textChanged.connect(self._update_buttons)
        self.new_notebook_title.textChanged.connect(self._update_buttons)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self._update_notebook_field()

    def _update_notebook_field(self) -> None:
        creating = self.notebook_combo.currentData() is None
        self.new_notebook_title.setEnabled(creating)
        self._update_buttons()

    def _update_buttons(self) -> None:
        valid_notebook = self.notebook_combo.currentData() is not None or bool(self.new_notebook_title.text().strip())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid_notebook and bool(self.experiment_title.text().strip()))

    def _accept_if_valid(self) -> None:
        self._update_buttons()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            self.accept()

    @property
    def notebook_id(self) -> int | None:
        value = self.notebook_combo.currentData()
        return int(value) if value is not None else None

    @property
    def notebook_title(self) -> str:
        return self.new_notebook_title.text().strip()

    @property
    def title(self) -> str:
        return self.experiment_title.text().strip()

    @property
    def experiment_description(self) -> str:
        return self.description.toPlainText().strip()


class ExperimentWindow(QDialog):
    """Persistent experiment workspace with A/B comparison and editable notes."""

    def __init__(
        self,
        service: ExperimentService,
        notebook: Notebook,
        experiment_id: int,
        analysis: ExperimentAnalysis,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.notebook = notebook
        self.experiment_id = experiment_id
        self.analysis = analysis
        self.aggregate = self.service.load_experiment(experiment_id)
        self._paths: list[tuple[ExperimentRun, Path]] = []
        self._dirty = False
        self._build_path_list()

        self.setWindowTitle(f"Experiment — {self.aggregate.experiment.title}")
        self.resize(1500, 980)

        self.heading = QLabel()
        self.heading.setTextFormat(Qt.TextFormat.RichText)
        self._update_heading()

        self.selector_a = QComboBox()
        self.selector_b = QComboBox()
        for run, path in self._paths:
            label = f"{run.title} — {path.name}"
            self.selector_a.addItem(label, str(path))
            self.selector_b.addItem(label, str(path))
        if self.selector_b.count() > 1:
            self.selector_b.setCurrentIndex(1)
        self.selector_a.currentIndexChanged.connect(self._selection_changed)
        self.selector_b.currentIndexChanged.connect(self._selection_changed)

        initial_a = self._selected_path(self.selector_a)
        initial_b = self._selected_path(self.selector_b)
        placeholder = Path("")
        self.view_a = CompareImageView(initial_a or placeholder)
        self.view_b = CompareImageView(initial_b or initial_a or placeholder)
        self.label_a = QLabel("<b>Image A</b>")
        self.label_b = QLabel("<b>Image B</b>")

        image_splitter = QSplitter(Qt.Orientation.Horizontal)
        image_splitter.addWidget(self._image_column(self.label_a, self.selector_a, self.view_a))
        image_splitter.addWidget(self._image_column(self.label_b, self.selector_b, self.view_b))
        image_splitter.setSizes([750, 750])
        image_splitter.splitterMoved.connect(lambda _p, _i: QTimer.singleShot(0, self._fit_both))

        self.parameter_table = QTableWidget(0, 3)
        self.parameter_table.setHorizontalHeaderLabels(["Field", "Image A", "Image B"])
        self.parameter_table.verticalHeader().setVisible(False)
        self.parameter_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.parameter_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.parameter_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.parameter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.parameter_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.prompt_a = QPlainTextEdit()
        self.prompt_b = QPlainTextEdit()
        for editor in (self.prompt_a, self.prompt_b):
            editor.setReadOnly(True)
        prompts = QSplitter(Qt.Orientation.Horizontal)
        prompts.addWidget(self._text_column("Positive prompt A", self.prompt_a))
        prompts.addWidget(self._text_column("Positive prompt B", self.prompt_b))

        self.lora_table = QTableWidget(0, 7)
        self.lora_table.setHorizontalHeaderLabels([
            "LoRA", "A model", "A clip", "B model", "B clip", "Used by A", "Used by B"
        ])
        self.lora_table.verticalHeader().setVisible(False)
        self.lora_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lora_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            self.lora_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        self.fixed_table = self._analysis_table(analysis.fixed, fixed=True)
        self.variable_table = self._analysis_table(analysis.variable, fixed=False)
        overview = QSplitter(Qt.Orientation.Horizontal)
        overview.addWidget(self._group("Fixed parameters", self.fixed_table))
        overview.addWidget(self._group("Variable parameters", self.variable_table))

        self.issues = QListWidget()
        for warning in analysis.warnings or ("No obvious consistency issues detected",):
            self.issues.addItem(("⚠ " if analysis.warnings else "") + warning)

        self.run_notes = QPlainTextEdit()
        self.run_notes.setPlaceholderText("Notes for the selected Image B run")
        self.run_notes.textChanged.connect(self._mark_dirty)
        self.conclusion = QPlainTextEdit(self.aggregate.experiment.conclusion)
        self.conclusion.setPlaceholderText("Experiment conclusion")
        self.conclusion.textChanged.connect(self._mark_dirty)
        notes_splitter = QSplitter(Qt.Orientation.Horizontal)
        notes_splitter.addWidget(self._text_column("Selected run notes", self.run_notes))
        notes_splitter.addWidget(self._text_column("Experiment conclusion", self.conclusion))

        tabs = QTabWidget()
        tabs.addTab(self.parameter_table, "A/B parameters")
        tabs.addTab(prompts, "Prompts")
        tabs.addTab(self.lora_table, "LoRAs")
        tabs.addTab(overview, "Experiment summary")
        tabs.addTab(self._group("Potential issues", self.issues), "Issues")
        tabs.addTab(notes_splitter, "Notes & conclusion")

        comparison_splitter = QSplitter(Qt.Orientation.Vertical)
        comparison_splitter.addWidget(image_splitter)
        comparison_splitter.addWidget(tabs)
        comparison_splitter.setSizes([590, 310])

        self.filmstrip = QListWidget()
        self.filmstrip.setViewMode(QListWidget.ViewMode.IconMode)
        self.filmstrip.setFlow(QListWidget.Flow.LeftToRight)
        self.filmstrip.setWrapping(False)
        self.filmstrip.setIconSize(QSize(120, 120))
        self.filmstrip.setGridSize(QSize(150, 155))
        self.filmstrip.setFixedHeight(180)
        self.filmstrip.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.filmstrip.currentItemChanged.connect(self._filmstrip_changed)
        self._populate_filmstrip()

        fit_button = QPushButton("Fit Both")
        fit_button.clicked.connect(self._fit_both)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.close)
        controls = QHBoxLayout()
        controls.addWidget(fit_button)
        controls.addStretch(1)
        controls.addWidget(save_button)
        controls.addWidget(close_buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(comparison_splitter, 1)
        layout.addLayout(controls)
        layout.addWidget(QLabel("<b>Experiment filmstrip</b> — click a thumbnail to select Image B"))
        layout.addWidget(self.filmstrip)

        self._selection_changed()
        QTimer.singleShot(0, self._fit_both)

    def _build_path_list(self) -> None:
        for run in self.aggregate.runs:
            images = self.aggregate.images_by_run.get(run.id, ())
            for image in images:
                self._paths.append((run, image.image_path))

    def _update_heading(self) -> None:
        experiment = self.aggregate.experiment
        description = f"<br>{experiment.description}" if experiment.description else ""
        self.heading.setText(f"<h2>{experiment.title}</h2><b>Notebook:</b> {self.notebook.title}{description}")

    @staticmethod
    def _image_column(label: QLabel, selector: QComboBox, view: CompareImageView) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(selector)
        layout.addWidget(view, 1)
        return widget

    @staticmethod
    def _text_column(title: str, editor: QPlainTextEdit) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        layout.addWidget(editor)
        return widget

    @staticmethod
    def _group(title: str, child: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(child)
        return group

    @staticmethod
    def _analysis_table(fields, *, fixed: bool) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Parameter", "Value" if fixed else "Values"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for field in fields:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(field.name))
            values = field.distinct_values
            display = values[0] if fixed and values else " → ".join(value or "(missing)" for value in values)
            table.setItem(row, 1, QTableWidgetItem(display))
        return table

    def _populate_filmstrip(self) -> None:
        for index, (run, path) in enumerate(self._paths):
            item = QListWidgetItem(f"{run.title}\n{path.name}")
            item.setData(PATH_ROLE, str(path))
            item.setData(RUN_ID_ROLE, run.id)
            item.setToolTip(str(path))
            if path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(
                        self.filmstrip.iconSize(), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )))
            self.filmstrip.addItem(item)
            if index == self.selector_b.currentIndex():
                self.filmstrip.setCurrentItem(item)

    @staticmethod
    def _selected_path(combo: QComboBox) -> Path | None:
        value = combo.currentData()
        return Path(value) if isinstance(value, str) and value else None

    def _selected_run(self) -> ExperimentRun | None:
        index = self.selector_b.currentIndex()
        if 0 <= index < len(self._paths):
            return self._paths[index][0]
        return None

    def _filmstrip_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        value = current.data(PATH_ROLE)
        if isinstance(value, str):
            index = self.selector_b.findData(value)
            if index >= 0:
                self.selector_b.setCurrentIndex(index)

    def _selection_changed(self) -> None:
        path_a = self._selected_path(self.selector_a)
        path_b = self._selected_path(self.selector_b)
        if path_a is None or path_b is None:
            return
        self.view_a.set_image(path_a)
        self.view_b.set_image(path_b)
        self.label_a.setText(f"<b>Image A</b> — {path_a.name}")
        self.label_b.setText(f"<b>Image B</b> — {path_b.name}")
        metadata_a = read_image_metadata(path_a)
        metadata_b = read_image_metadata(path_b)
        summary_a = extract_summary(metadata_a)
        summary_b = extract_summary(metadata_b)
        self.prompt_a.setPlainText(summary_a.get("positive", ""))
        self.prompt_b.setPlainText(summary_b.get("positive", ""))
        self._populate_parameters(path_a, summary_a, path_b, summary_b)
        self._populate_loras(metadata_a, metadata_b)
        run = self._selected_run()
        self.run_notes.blockSignals(True)
        self.run_notes.setPlainText(run.notes if run else "")
        self.run_notes.blockSignals(False)
        if 0 <= self.selector_b.currentIndex() < self.filmstrip.count():
            self.filmstrip.blockSignals(True)
            self.filmstrip.setCurrentRow(self.selector_b.currentIndex())
            self.filmstrip.blockSignals(False)
        QTimer.singleShot(0, self._fit_both)

    def _populate_parameters(self, path_a: Path, summary_a, path_b: Path, summary_b) -> None:
        fields = compare_parameters(path_a, summary_a, path_b, summary_b)
        self.parameter_table.setRowCount(len(fields))
        difference = QBrush(QColor(58, 79, 102))
        foreground = QBrush(QColor(255, 255, 255))
        for row, field in enumerate(fields):
            for column, value in enumerate((field.name, field.value_a or "—", field.value_b or "—")):
                item = QTableWidgetItem(str(value))
                if column in (1, 2) and field.differs:
                    item.setBackground(difference)
                    item.setForeground(foreground)
                self.parameter_table.setItem(row, column, item)
        self.parameter_table.resizeRowsToContents()

    def _populate_loras(self, metadata_a, metadata_b) -> None:
        rows = compare_loras(metadata_a, metadata_b)
        self.lora_table.setRowCount(len(rows))
        difference = QBrush(QColor(58, 79, 102))
        missing = QBrush(QColor(92, 52, 52))
        foreground = QBrush(QColor(255, 255, 255))
        for row, comparison in enumerate(rows):
            a, b = comparison.value_a, comparison.value_b
            values = (
                comparison.display_name,
                a.model_strength if a else "—", a.clip_strength if a else "—",
                b.model_strength if b else "—", b.clip_strength if b else "—",
                "Yes" if a else "No", "Yes" if b else "No",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if comparison.differs:
                    item.setBackground(difference if (a and b) else missing)
                    item.setForeground(foreground)
                self.lora_table.setItem(row, column, item)

    def _fit_both(self) -> None:
        self.view_a.fit_to_view()
        self.view_b.fit_to_view()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def save(self) -> None:
        run = self._selected_run()
        if run is not None and run.notes != self.run_notes.toPlainText().strip():
            saved = self.service.update_run_notes(run.id, self.run_notes.toPlainText())
            index = self.selector_b.currentIndex()
            self._paths[index] = (saved, self._paths[index][1])
        conclusion = self.conclusion.toPlainText()
        if conclusion.strip() != self.aggregate.experiment.conclusion:
            experiment = self.service.update_experiment_conclusion(self.experiment_id, conclusion)
            self.aggregate = self.service.load_experiment(experiment.id)
        self._dirty = False
        QMessageBox.information(self, "Experiment saved", "Run notes and conclusion have been saved.")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._dirty:
            answer = QMessageBox.question(
                self, "Save changes?", "Save changes to this experiment before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                self.save()
        event.accept()


# Backward-compatible name used by the Phase 2 main-window integration.

class ExperimentNotebookDialog(QDialog):
    """Browse notebooks and open an existing experiment."""

    def __init__(self, service: ExperimentService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.selected_experiment_id: int | None = None
        self.setWindowTitle("Experiment Notebook")
        self.resize(760, 520)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Notebook / Experiment", "Status", "Updated"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._open_selected())

        open_button = QPushButton("Open Experiment")
        open_button.clicked.connect(self._open_selected)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(open_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select an experiment to open:"))
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        self._populate()

    def _populate(self) -> None:
        self.tree.clear()
        for notebook in self.service.repository.list_notebooks(include_archived=True):
            notebook_item = QTreeWidgetItem([
                notebook.title,
                notebook.status.value.title(),
                notebook.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            ])
            notebook_item.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(notebook_item)
            if notebook.id is None:
                continue
            for experiment in self.service.repository.list_experiments(notebook.id):
                child = QTreeWidgetItem([
                    experiment.title,
                    experiment.status.value.title(),
                    experiment.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, experiment.id)
                notebook_item.addChild(child)
            notebook_item.setExpanded(True)
        self.tree.resizeColumnToContents(0)

    def _open_selected(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value is None:
            item.setExpanded(not item.isExpanded())
            return
        self.selected_experiment_id = int(value)
        self.accept()


ExperimentSummaryDialog = ExperimentWindow
