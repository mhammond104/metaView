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
