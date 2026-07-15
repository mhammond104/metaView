from pathlib import Path


def test_smart_collection_open_uses_authoritative_index() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "main_window.py"
    ).read_text(encoding="utf-8")
    assert "self.image_index.all_images()" in source
    assert "evaluate_indexed_smart_collection(" in source
    assert "No indexed images currently match this Smart Collection." in source
