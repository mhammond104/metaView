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
