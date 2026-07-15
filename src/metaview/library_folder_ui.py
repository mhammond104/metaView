"""Dialogs for managing explicit library membership."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from .library_folders import LibraryFolderRepository


class ManageLibraryFoldersDialog(QDialog):
    changed = Signal()
    openRequested = Signal(object)

    def __init__(self, repository: LibraryFolderRepository, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("Manage Library Folders")
        self.resize(680, 420)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._open_selected)

        add_button = QPushButton("Add Folder…")
        add_button.clicked.connect(self._add)
        remove_button = QPushButton("Remove from Library")
        remove_button.clicked.connect(self._remove)
        rescan_button = QPushButton("Open and Rescan")
        rescan_button.clicked.connect(self._open_selected)

        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addWidget(rescan_button)
        button_row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Only registered folders contribute images to All Images and Smart Collections. "
            "Removing a folder never deletes its files."
        ))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(button_row)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.list_widget.clear()
        for folder in self.repository.list():
            item = QListWidgetItem(str(folder.path))
            item.setData(Qt.ItemDataRole.UserRole, folder.id)
            self.list_widget.addItem(item)

    def _add(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Add Folder to Library")
        if not selected:
            return
        try:
            self.repository.add(Path(selected))
        except ValueError as error:
            QMessageBox.warning(self, "Unable to add folder", str(error))
            return
        self.refresh()
        self.changed.emit()

    def _remove(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        folder_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(folder_id, int):
            return
        answer = QMessageBox.question(
            self,
            "Remove folder from library?",
            "The folder will no longer contribute to All Images or Smart Collections. "
            "No files will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.repository.remove(folder_id)
            self.refresh()
            self.changed.emit()

    def _open_selected(self, _item=None) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        folder_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(folder_id, int):
            return
        folder = self.repository.get(folder_id)
        if folder is not None:
            self.openRequested.emit(folder.path)
