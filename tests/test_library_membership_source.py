from pathlib import Path


def test_browsing_and_library_indexing_are_explicitly_separated() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "metaview" / "main_window.py").read_text(encoding="utf-8")
    assert 'QAction("Browse Folder…", self)' in source
    assert 'QAction("Add Folder to Library…", self)' in source
    assert "self.library_folder_repository.contains_folder(directory)" in source
    assert "if generation == self.index_scan_generation and self.index_scan_persist:" in source
    assert "self.library_indexed_images()" in source


def test_smart_collections_use_only_library_indexed_images() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "metaview" / "main_window.py").read_text(encoding="utf-8")
    assert "self.library_indexed_images()," in source
    assert "if self.library_folder_repository.contains_path(image.path)" in source
