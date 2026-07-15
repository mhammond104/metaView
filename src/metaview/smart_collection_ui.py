from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QVBoxLayout,
)

from .smart_collections import SmartCollection, SmartCollectionRule


FIELDS = [
    ("Rating", "rating"),
    ("Model", "model"),
    ("Sampler", "sampler"),
    ("Scheduler", "scheduler"),
    ("Positive prompt", "prompt"),
    ("Filename", "filename"),
    ("User tag", "tag"),
]

TEXT_OPERATORS = [
    ("contains", "contains"),
    ("is exactly", "is"),
    ("does not contain", "not_contains"),
]
RATING_OPERATORS = [
    ("is at least", "gte"),
    ("is exactly", "is"),
    ("is at most", "lte"),
]


class SmartCollectionDialog(QDialog):
    """Small rule editor for the first AND-only smart collection format."""

    def __init__(self, collection: SmartCollection | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Smart Collection" if collection else "New Smart Collection")
        self.resize(620, 330)

        self.name_edit = QLineEdit(collection.name if collection else "")
        form = QFormLayout()
        form.addRow("Name:", self.name_edit)

        self.rule_table = QTableWidget(4, 3)
        self.rule_table.setHorizontalHeaderLabels(["Field", "Condition", "Value"])
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.verticalHeader().setVisible(False)
        self.rule_table.setAlternatingRowColors(True)

        for row in range(self.rule_table.rowCount()):
            field_combo = QComboBox()
            field_combo.addItem("— unused —", "")
            for label, value in FIELDS:
                field_combo.addItem(label, value)
            operator_combo = QComboBox()
            value_edit = QLineEdit()
            self.rule_table.setCellWidget(row, 0, field_combo)
            self.rule_table.setCellWidget(row, 1, operator_combo)
            self.rule_table.setCellWidget(row, 2, value_edit)
            field_combo.currentIndexChanged.connect(
                lambda _index, r=row: self._update_operators(r)
            )
            self._update_operators(row)

        if collection:
            for row, rule in enumerate(collection.rules[: self.rule_table.rowCount()]):
                field_combo = self.rule_table.cellWidget(row, 0)
                operator_combo = self.rule_table.cellWidget(row, 1)
                value_edit = self.rule_table.cellWidget(row, 2)
                field_combo.setCurrentIndex(field_combo.findData(rule.field))
                self._update_operators(row)
                operator_combo.setCurrentIndex(operator_combo.findData(rule.operator))
                value_edit.setText(rule.value)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("All configured rules must match:"))
        layout.addWidget(self.rule_table)
        layout.addWidget(buttons)

    def _update_operators(self, row: int) -> None:
        field_combo = self.rule_table.cellWidget(row, 0)
        operator_combo = self.rule_table.cellWidget(row, 1)
        current = operator_combo.currentData()
        operator_combo.clear()
        field = field_combo.currentData()
        operators = RATING_OPERATORS if field == "rating" else TEXT_OPERATORS
        if not field:
            operator_combo.addItem("—", "")
            operator_combo.setEnabled(False)
            return
        operator_combo.setEnabled(True)
        for label, value in operators:
            operator_combo.addItem(label, value)
        index = operator_combo.findData(current)
        if index >= 0:
            operator_combo.setCurrentIndex(index)

    @property
    def collection_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def rules(self) -> tuple[SmartCollectionRule, ...]:
        rules: list[SmartCollectionRule] = []
        for row in range(self.rule_table.rowCount()):
            field_combo = self.rule_table.cellWidget(row, 0)
            operator_combo = self.rule_table.cellWidget(row, 1)
            value_edit = self.rule_table.cellWidget(row, 2)
            field = str(field_combo.currentData() or "")
            value = value_edit.text().strip()
            if not field and not value:
                continue
            if not field or not value:
                raise ValueError("Each smart collection rule needs a field and a value")
            rules.append(
                SmartCollectionRule(
                    field=field,
                    operator=str(operator_combo.currentData()),
                    value=value,
                )
            )
        if not rules:
            raise ValueError("Add at least one smart collection rule")
        return tuple(rules)
