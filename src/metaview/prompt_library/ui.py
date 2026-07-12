"""Qt user interface for the metaView Prompt Library."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .image_index import ImageIndexService
from .models import Prompt
from .repository import (
    DuplicatePromptError,
    PromptNotFoundError,
    PromptRepository,
    PromptSearch,
    PromptSort,
)


class PromptLibraryController(QObject):
    """Coordinates repository changes and exposes one refresh signal to UI."""

    changed = Signal()

    def __init__(
        self,
        repository: PromptRepository,
        image_index: ImageIndexService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.image_index = image_index

    def add(self, prompt: Prompt) -> Prompt:
        saved = self.repository.add(prompt)
        self.changed.emit()
        return saved

    def update(self, prompt: Prompt) -> Prompt:
        saved = self.repository.update(prompt)
        self.changed.emit()
        return saved

    def delete(self, prompt_id: int) -> None:
        self.repository.delete(prompt_id)
        self.changed.emit()


class StarRatingWidget(QWidget):
    """Small clickable zero-to-five-star editor."""

    rating_changed = Signal(int)

    def __init__(self, rating: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rating = 0
        self._buttons: list[QToolButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        for value in range(1, 6):
            button = QToolButton()
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{value} star{'s' if value != 1 else ''}")
            button.clicked.connect(
                lambda _checked=False, selected=value: self.set_rating(
                    0 if self._rating == selected else selected
                )
            )
            self._buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)
        self.set_rating(rating, emit=False)

    def rating(self) -> int:
        return self._rating

    def set_rating(self, rating: int, *, emit: bool = True) -> None:
        value = max(0, min(5, int(rating)))
        if self._rating == value and self._buttons:
            self._refresh()
            return
        self._rating = value
        self._refresh()
        if emit:
            self.rating_changed.emit(value)

    def _refresh(self) -> None:
        for index, button in enumerate(self._buttons, start=1):
            button.setText("★" if index <= self._rating else "☆")
            button.setStyleSheet("font-size: 19px;")


class PromptEditorDialog(QDialog):
    """Create or edit a repository-backed Prompt object."""

    def __init__(
        self,
        controller: PromptLibraryController,
        *,
        prompt: Prompt | None = None,
        positive_prompt: str = "",
        negative_prompt: str = "",
        source_image: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.original_prompt = prompt
        self.source_image = prompt.source_image if prompt else source_image
        self.saved_prompt: Prompt | None = None

        self.setWindowTitle(
            "Edit Library Prompt" if prompt else "Add Prompt to Library"
        )
        self.resize(780, 690)

        initial_positive = prompt.positive_prompt if prompt else positive_prompt
        initial_negative = prompt.negative_prompt if prompt else negative_prompt

        self.title_edit = QLineEdit(
            prompt.title if prompt else self._default_title(initial_positive)
        )
        self.title_edit.setPlaceholderText("A memorable prompt title")

        self.positive_edit = QPlainTextEdit(initial_positive)
        self.negative_edit = QPlainTextEdit(initial_negative)
        self.tags_edit = QLineEdit(
            ", ".join(prompt.tags) if prompt else ""
        )
        self.tags_edit.setPlaceholderText(
            "Comma-separated tags, e.g. portrait, natural-light, krea2"
        )
        self.rating_widget = StarRatingWidget(prompt.rating if prompt else 0)
        self.notes_edit = QPlainTextEdit(prompt.notes if prompt else "")
        self.notes_edit.setPlaceholderText(
            "Optional notes about usage, strengths or limitations"
        )

        source_label = QLabel(str(self.source_image) if self.source_image else "None")
        source_label.setWordWrap(True)
        source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        form = QFormLayout()
        form.addRow("Title:", self.title_edit)
        form.addRow("Positive prompt:", self.positive_edit)
        form.addRow("Negative prompt:", self.negative_edit)
        form.addRow("Rating:", self.rating_widget)
        form.addRow("Tags:", self.tags_edit)
        form.addRow("Notes:", self.notes_edit)
        form.addRow("Source image:", source_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form, 1)
        layout.addWidget(buttons)

    @staticmethod
    def _default_title(positive_prompt: str) -> str:
        compact = " ".join(positive_prompt.split())
        return compact[:80]

    def _tags(self) -> tuple[str, ...]:
        return tuple(
            value.strip()
            for value in self.tags_edit.text().split(",")
            if value.strip()
        )

    def _build_prompt(self) -> Prompt:
        values = {
            "title": self.title_edit.text(),
            "positive_prompt": self.positive_edit.toPlainText(),
            "negative_prompt": self.negative_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
            "rating": self.rating_widget.rating(),
            "tags": self._tags(),
            "source_image": self.source_image,
        }
        if self.original_prompt is None:
            return Prompt(**values)
        return self.original_prompt.with_updates(**values)

    def save(self) -> None:
        try:
            candidate = self._build_prompt()
            if self.original_prompt is None:
                self.saved_prompt = self.controller.add(candidate)
            else:
                self.saved_prompt = self.controller.update(candidate)
        except DuplicatePromptError as error:
            answer = QMessageBox.question(
                self,
                "Prompt already in library",
                f'This exact positive prompt is already saved as '
                f'"{error.existing.title}".\n\nOpen the existing entry?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                existing_dialog = PromptEditorDialog(
                    self.controller,
                    prompt=error.existing,
                    parent=self.parentWidget(),
                )
                existing_dialog.exec()
                self.reject()
            return
        except (TypeError, ValueError) as error:
            QMessageBox.information(self, "Unable to save prompt", str(error))
            return
        self.accept()


class PromptLibraryDialog(QDialog):
    """Three-pane global Prompt Library browser."""

    browse_requested = Signal(object)

    def __init__(
        self,
        controller: PromptLibraryController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.repository = controller.repository
        self.image_index = controller.image_index
        self.prompts_by_id: dict[int, Prompt] = {}
        self.active_tag: str | None = None
        self.special_filter: str = "all"

        self.setWindowTitle("Prompt Library")
        self.resize(1220, 780)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search titles, prompts, notes or tags…"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh_prompts)

        self.rating_combo = QComboBox()
        self.rating_combo.addItem("All ratings", 0)
        self.rating_combo.addItem("★★★★★ only", 5)
        self.rating_combo.addItem("★★★★ and above", 4)
        self.rating_combo.addItem("★★★ and above", 3)
        self.rating_combo.addItem("★★ and above", 2)
        self.rating_combo.addItem("★ and above", 1)
        self.rating_combo.currentIndexChanged.connect(self.refresh_prompts)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Highest rated", "rating")
        self.sort_combo.addItem("Most images", "images_desc")
        self.sort_combo.addItem("Fewest images", "images_asc")
        self.sort_combo.addItem("Recently added", "created")
        self.sort_combo.addItem("Recently edited", "updated")
        self.sort_combo.addItem("Alphabetical", "title")
        self.sort_combo.currentIndexChanged.connect(self.refresh_prompts)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.search_edit, 1)
        top_layout.addWidget(QLabel("Rating:"))
        top_layout.addWidget(self.rating_combo)
        top_layout.addWidget(QLabel("Sort:"))
        top_layout.addWidget(self.sort_combo)

        self.sidebar = QListWidget()
        self.sidebar.setMinimumWidth(210)
        self.sidebar.currentItemChanged.connect(self.sidebar_changed)

        self.prompt_list = QListWidget()
        self.prompt_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.prompt_list.currentItemChanged.connect(self.selection_changed)
        self.prompt_list.itemDoubleClicked.connect(self.browse_selected)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 19px; font-weight: 600;")
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.detail_rating = StarRatingWidget()
        self.detail_rating.rating_changed.connect(self.rating_changed)
        self.positive_view = QPlainTextEdit()
        self.negative_view = QPlainTextEdit()
        self.notes_view = QPlainTextEdit()
        for editor in (
            self.positive_view,
            self.negative_view,
            self.notes_view,
        ):
            editor.setReadOnly(True)

        self.view_button = QPushButton("View Matching Images")
        self.view_button.clicked.connect(self.browse_selected)
        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        self.copy_button = QPushButton("Copy Positive Prompt")
        self.copy_button.clicked.connect(self.copy_positive_prompt)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.addWidget(self.title_label)
        details_layout.addWidget(self.detail_rating)
        details_layout.addWidget(self.summary_label)
        details_layout.addWidget(QLabel("Positive prompt"))
        details_layout.addWidget(self.positive_view, 2)
        details_layout.addWidget(QLabel("Negative prompt"))
        details_layout.addWidget(self.negative_view, 1)
        details_layout.addWidget(QLabel("Notes"))
        details_layout.addWidget(self.notes_view, 1)

        actions = QHBoxLayout()
        actions.addWidget(self.view_button)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        details_layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.prompt_list)
        splitter.addWidget(details)
        splitter.setSizes([220, 400, 600])

        layout = QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(splitter, 1)

        self.controller.changed.connect(self.repository_changed)
        self.refresh_sidebar()
        self.refresh_prompts()

    def repository_changed(self) -> None:
        current = self.current_prompt()
        selected_id = current.id if current else None
        self.refresh_sidebar()
        self.refresh_prompts(selected_id=selected_id)

    def refresh_sidebar(self) -> None:
        selected_data = None
        current = self.sidebar.currentItem()
        if current is not None:
            selected_data = current.data(Qt.ItemDataRole.UserRole)

        statistics = self.repository.statistics()
        self.sidebar.blockSignals(True)
        self.sidebar.clear()

        items = [
            (f"All prompts  ({statistics.prompt_count})", ("special", "all")),
            (
                f"Favourites  ({statistics.favourite_count})",
                ("special", "favourites"),
            ),
            (
                f"Unrated  ({statistics.prompt_count - statistics.rated_count})",
                ("special", "unrated"),
            ),
            (
                f"Untagged  ({statistics.untagged_count})",
                ("special", "untagged"),
            ),
        ]
        for text, data in items:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.sidebar.addItem(item)
            if data == selected_data:
                self.sidebar.setCurrentItem(item)

        tags = self.repository.all_tags()
        if tags:
            heading = QListWidgetItem("Tags")
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            self.sidebar.addItem(heading)
        for tag in tags:
            data = ("tag", tag.name)
            item = QListWidgetItem(f"{tag.name}  ({tag.prompt_count})")
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.sidebar.addItem(item)
            if data == selected_data:
                self.sidebar.setCurrentItem(item)

        if self.sidebar.currentItem() is None and self.sidebar.count():
            self.sidebar.setCurrentRow(0)
        self.sidebar.blockSignals(False)

    def sidebar_changed(self, current, _previous) -> None:
        self.active_tag = None
        self.special_filter = "all"
        data = current.data(Qt.ItemDataRole.UserRole) if current else None
        if isinstance(data, tuple) and len(data) == 2:
            kind, value = data
            if kind == "tag":
                self.active_tag = str(value)
            elif kind == "special":
                self.special_filter = str(value)
        self.refresh_prompts()

    def _search_query(self) -> PromptSearch:
        sort_value = str(self.sort_combo.currentData() or "rating")
        repository_sort = {
            "title": PromptSort.TITLE,
            "created": PromptSort.CREATED_DESC,
            "updated": PromptSort.UPDATED_DESC,
        }.get(sort_value, PromptSort.RATING_DESC)
        return PromptSearch(
            text=self.search_edit.text(),
            tags=(self.active_tag,) if self.active_tag else (),
            minimum_rating=int(self.rating_combo.currentData() or 0),
            favourites_only=self.special_filter == "favourites",
            unrated_only=self.special_filter == "unrated",
            untagged_only=self.special_filter == "untagged",
            sort=repository_sort,
        )

    def refresh_prompts(self, *_args, selected_id: int | None = None) -> None:
        prompts = self.repository.search(self._search_query())
        sort_value = str(self.sort_combo.currentData() or "rating")
        if sort_value == "images_desc":
            prompts.sort(
                key=lambda prompt: (
                    -self.image_index.count_matching(prompt),
                    prompt.title.casefold(),
                )
            )
        elif sort_value == "images_asc":
            prompts.sort(
                key=lambda prompt: (
                    self.image_index.count_matching(prompt),
                    prompt.title.casefold(),
                )
            )

        self.prompts_by_id = {
            prompt.id: prompt
            for prompt in prompts
            if prompt.id is not None
        }
        self.prompt_list.blockSignals(True)
        self.prompt_list.clear()
        selected_item = None
        for prompt in prompts:
            count = self.image_index.count_matching(prompt)
            tags = ", ".join(prompt.tags) or "untagged"
            item = QListWidgetItem(
                f"{'★' * prompt.rating}{'☆' * (5 - prompt.rating)}  "
                f"{prompt.title}\n{tags} — {count} matching "
                f"image{'s' if count != 1 else ''}"
            )
            item.setData(Qt.ItemDataRole.UserRole, prompt.id)
            item.setToolTip(prompt.positive_prompt)
            self.prompt_list.addItem(item)
            if prompt.id == selected_id:
                selected_item = item
        self.prompt_list.blockSignals(False)

        if selected_item is not None:
            self.prompt_list.setCurrentItem(selected_item)
        elif self.prompt_list.count():
            self.prompt_list.setCurrentRow(0)
        else:
            self.clear_details()

    def current_prompt(self) -> Prompt | None:
        item = self.prompt_list.currentItem()
        if item is None:
            return None
        prompt_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(prompt_id, int):
            return None
        return self.prompts_by_id.get(prompt_id)

    def selection_changed(self, _current, _previous) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            self.clear_details()
            return
        count = self.image_index.count_matching(prompt)
        directory_counts = self.image_index.directory_counts(prompt)
        directory_text = "\n".join(
            f"{entry.directory}: {entry.image_count}"
            for entry in directory_counts
        )
        self.title_label.setText(prompt.title)
        self.detail_rating.set_rating(prompt.rating, emit=False)
        self.summary_label.setText(
            f"Tags: {', '.join(prompt.tags) or 'none'}\n"
            f"Matching images: {count}"
            + (f"\n\nDirectories:\n{directory_text}" if directory_text else "")
        )
        self.positive_view.setPlainText(prompt.positive_prompt)
        self.negative_view.setPlainText(prompt.negative_prompt)
        self.notes_view.setPlainText(prompt.notes)
        self._set_actions_enabled(True, can_view=count > 0)

    def clear_details(self) -> None:
        self.title_label.clear()
        self.summary_label.clear()
        self.detail_rating.set_rating(0, emit=False)
        self.positive_view.clear()
        self.negative_view.clear()
        self.notes_view.clear()
        self._set_actions_enabled(False, can_view=False)

    def _set_actions_enabled(self, enabled: bool, *, can_view: bool) -> None:
        self.view_button.setEnabled(enabled and can_view)
        self.copy_button.setEnabled(enabled)
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.detail_rating.setEnabled(enabled)

    def rating_changed(self, rating: int) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            return
        try:
            self.controller.update(prompt.with_updates(rating=rating))
        except (ValueError, PromptNotFoundError) as error:
            QMessageBox.warning(self, "Unable to update rating", str(error))

    def browse_selected(self, *_args) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            return
        paths = self.image_index.matching_paths(prompt)
        if not paths:
            QMessageBox.information(
                self,
                "No matching images",
                "No indexed image currently uses this exact positive prompt.",
            )
            return
        self.browse_requested.emit(prompt)
        self.accept()

    def edit_selected(self) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            return
        PromptEditorDialog(
            self.controller,
            prompt=prompt,
            parent=self,
        ).exec()

    def delete_selected(self) -> None:
        prompt = self.current_prompt()
        if prompt is None or prompt.id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete prompt",
            f'Delete "{prompt.title}" from the Prompt Library?',
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.delete(prompt.id)
        except PromptNotFoundError as error:
            QMessageBox.warning(self, "Unable to delete prompt", str(error))

    def copy_positive_prompt(self) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(prompt.positive_prompt)
