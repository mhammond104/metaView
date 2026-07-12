"""Qt user interface for creating and reviewing experiments."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .analysis import ExperimentAnalysis
from .models import ExperimentAggregate, Notebook


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


class ExperimentSummaryDialog(QDialog):
    def __init__(self, notebook: Notebook, aggregate: ExperimentAggregate, analysis: ExperimentAnalysis, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Experiment — {aggregate.experiment.title}")
        self.resize(980, 720)
        heading = QLabel(f"<h2>{aggregate.experiment.title}</h2><b>Notebook:</b> {notebook.title}")
        if aggregate.experiment.description:
            heading.setText(heading.text() + f"<br>{aggregate.experiment.description}")
        filmstrip = QListWidget()
        filmstrip.setViewMode(QListWidget.ViewMode.IconMode)
        filmstrip.setIconSize(QSize(150, 120))
        filmstrip.setGridSize(QSize(175, 155))
        filmstrip.setMovement(QListWidget.Movement.Static)
        filmstrip.setMaximumHeight(180)
        for run in aggregate.runs:
            images = aggregate.images_by_run.get(run.id, ())
            path = images[0].image_path if images else None
            item = QListWidgetItem(run.title)
            if path and path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(150, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
            if path:
                item.setToolTip(str(path))
            filmstrip.addItem(item)

        tables = QHBoxLayout()
        tables.addWidget(self._field_group("Fixed parameters", analysis.fixed, fixed=True), 1)
        tables.addWidget(self._field_group("Variable parameters", analysis.variable, fixed=False), 1)

        issues = QListWidget()
        if analysis.warnings:
            for warning in analysis.warnings:
                issues.addItem(f"⚠ {warning}")
        else:
            issues.addItem("No obvious consistency issues detected")
        issues.setMaximumHeight(130)
        issue_group = QGroupBox("Potential issues")
        issue_layout = QVBoxLayout(issue_group)
        issue_layout.addWidget(issues)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(filmstrip)
        layout.addLayout(tables, 1)
        layout.addWidget(issue_group)
        layout.addWidget(buttons)

    @staticmethod
    def _field_group(title: str, fields, *, fixed: bool) -> QGroupBox:
        group = QGroupBox(title)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Parameter", "Value" if fixed else "Values"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for field in fields:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(field.name))
            values = field.distinct_values
            display = values[0] if fixed and values else " → ".join(value or "(missing)" for value in values)
            table.setItem(row, 1, QTableWidgetItem(display))
        layout = QVBoxLayout(group)
        layout.addWidget(table)
        return group
