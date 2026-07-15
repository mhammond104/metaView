from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from .tags import TagRepository


class ManageTagsDialog(QDialog):
    """Assign or remove user tags across one or more selected images."""

    def __init__(self, repository: TagRepository, paths: list[Path], parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.paths = [path.resolve() for path in paths]
        self._initial_states: dict[int, Qt.CheckState] = {}
        self.setWindowTitle("Manage Tags")
        self.resize(420, 420)

        self.tag_list = QListWidget()
        self.tag_list.itemChanged.connect(self._item_changed)

        add_button = QPushButton("New Tag…")
        add_button.clicked.connect(self.create_tag)
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(add_button)
        buttons_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons_row)
        layout.addWidget(self.tag_list, 1)
        layout.addWidget(buttons)
        self.reload()

    def reload(self) -> None:
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        self._initial_states.clear()
        for tag in self.repository.list():
            present = sum(tag.id in self.repository.tag_ids_for_path(path) for path in self.paths)
            state = (
                Qt.CheckState.Unchecked
                if present == 0
                else Qt.CheckState.Checked
                if present == len(self.paths)
                else Qt.CheckState.PartiallyChecked
            )
            item = QListWidgetItem(tag.name)
            item.setData(Qt.ItemDataRole.UserRole, tag.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(state)
            self._initial_states[tag.id] = state
            self.tag_list.addItem(item)
        self.tag_list.blockSignals(False)

    def _item_changed(self, item: QListWidgetItem) -> None:
        # A user click on a partial state should resolve to checked, not jump to unchecked.
        tag_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(tag_id, int) and item.checkState() == Qt.CheckState.PartiallyChecked:
            item.setCheckState(Qt.CheckState.Checked)

    def create_tag(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Tag", "Tag name:")
        if not accepted:
            return
        try:
            tag = self.repository.create(name)
            self.repository.assign(tag.id, self.paths)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to create tag", str(error))
            return
        self.reload()

    def apply_changes(self) -> tuple[int, int]:
        added = 0
        removed = 0
        for row in range(self.tag_list.count()):
            item = self.tag_list.item(row)
            tag_id = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(tag_id, int):
                continue
            initial = self._initial_states.get(tag_id, Qt.CheckState.Unchecked)
            current = item.checkState()
            if current == Qt.CheckState.Checked and initial != Qt.CheckState.Checked:
                added += self.repository.assign(tag_id, self.paths)
            elif current == Qt.CheckState.Unchecked and initial != Qt.CheckState.Unchecked:
                removed += self.repository.unassign(tag_id, self.paths)
        return added, removed
