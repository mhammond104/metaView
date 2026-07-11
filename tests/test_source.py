from pathlib import Path
import ast


def test_all_python_sources_parse() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = list((root / "src").rglob("*.py")) + [root / "main.py"]
    assert sources
    for source in sources:
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


def test_required_assets_exist() -> None:
    assets = Path(__file__).resolve().parents[1] / "src" / "metaview" / "assets"
    assert (assets / "metaview.png").is_file()
    assert (assets / "metaview.ico").is_file()


def test_refactored_modules_exist() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "metaview"
    expected = {
        "application.py",
        "constants.py",
        "dialogs.py",
        "main.py",
        "main_window.py",
        "metadata.py",
        "theme.py",
        "widgets.py",
        "workers.py",
    }
    assert expected <= {path.name for path in package.glob("*.py")}


def test_main_module_is_a_small_compatibility_entry_point() -> None:
    main_module = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "main.py"
    )
    source = main_module.read_text(encoding="utf-8")
    assert "from .application import main" in source
    assert len(source.splitlines()) < 20


def test_prompt_library_domain_package_exists() -> None:
    package = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "prompt_library"
    )
    assert (package / "__init__.py").is_file()
    assert (package / "models.py").is_file()
    assert (package / "normalization.py").is_file()


def test_main_window_has_no_obsolete_prompt_buttons() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "main_window.py"
    ).read_text(encoding="utf-8")
    assert 'QPushButton("Save Prompt")' not in source
    assert 'QPushButton("Prompt Library")' not in source
    assert 'QAction("Save prompt"' not in source
    assert "itemSelectionChanged.connect(self.thumbnail_selection_changed)" in source



def test_top_toolbar_has_no_duplicate_similarity_or_experiment_actions() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "metaview" / "main_window.py").read_text(encoding="utf-8")
    assert 'QAction("Find similar"' not in source
    assert 'QAction("Experiment view"' not in source
    assert 'self.find_similar_button = QPushButton("Find Similar")' in source
    assert 'self.experiment_view_button = QPushButton("Experiment View")' in source


def test_rating_and_open_actions_resolve_current_thumbnail_at_click_time() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "metaview" / "main_window.py").read_text(encoding="utf-8")
    assert "def selected_image_path(self) -> Path | None:" in source
    assert "path = self.selected_image_path()" in source
    assert "self.ratings_database.set(path, value)" in source
    assert "QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))" in source


def test_metadata_panel_imports_all_metadata_helpers_it_uses() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "widgets.py"
    ).read_text(encoding="utf-8")
    assert "extract_loras" in source.split("class ImageDragListWidget", 1)[0]
    assert "parse_json_value" in source.split("class ImageDragListWidget", 1)[0]
