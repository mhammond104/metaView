from pathlib import Path


def source(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "src" / "metaview" / name).read_text(encoding="utf-8")


def test_thumbnail_context_menu_exposes_everyday_workflows() -> None:
    text = source("main_window.py")
    for label in (
        'menu.addAction("Preview")',
        'menu.addAction("Compare Selected…")',
        'menu.addAction("Compare With…")',
        'menu.addMenu("Add to Collection")',
        'menu.addAction("Manage Tags…")',
        'menu.addAction("Add to Experiment…")',
        'menu.addMenu("Set Rating")',
        'menu.addMenu("Copy")',
    ):
        assert label in text


def test_shortcuts_are_centralised_and_non_conflicting() -> None:
    text = source("main_window.py")
    assert 'self.preview_action.setShortcuts([QKeySequence("Space"), QKeySequence("Return")])' in text
    assert 'self.compare_action.setShortcut("Ctrl+M")' in text
    assert 'self.add_to_collection_action.setShortcut("Ctrl+Alt+C")' in text
    assert 'self.manage_tags_action.setShortcut("Ctrl+T")' in text
    assert 'self.add_to_experiment_action.setShortcut("Ctrl+Alt+E")' in text
    assert 'copy_negative_action.setShortcut("Ctrl+Alt+P")' in text
    assert 'self.focus_search_action.setShortcut("Ctrl+F")' in text
    assert 'self.rename_current_action.setShortcut("F2")' in text


def test_tag_sidebar_accepts_image_drops() -> None:
    widgets = source("widgets.py")
    window = source("main_window.py")
    assert "class TagListWidget(QListWidget):" in widgets
    assert "imagesDropped = Signal(int, object)" in widgets
    assert "self.tag_list = TagListWidget()" in window
    assert "self.tag_list.imagesDropped.connect(self.add_dropped_images_to_tag)" in window


def test_compare_with_is_a_cancellable_two_click_mode() -> None:
    text = source("main_window.py")
    assert "def start_compare_with_selected(self) -> None:" in text
    assert "def thumbnail_clicked(self, item: QListWidgetItem) -> None:" in text
    assert "Compare With cancelled" in text
