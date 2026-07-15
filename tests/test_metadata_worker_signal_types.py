from pathlib import Path


def test_metadata_worker_uses_object_signal_fields_for_large_file_values() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "workers.py"
    ).read_text(encoding="utf-8")
    assert "loaded = Signal(str, str, str, str, str, object, int, object, object)" in source
    assert "failed = Signal(str, str, int)" in source


def test_main_window_handles_metadata_worker_failures() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "metaview"
        / "main_window.py"
    ).read_text(encoding="utf-8")
    assert "metadata_worker.signals.failed.connect(self.model_failed)" in source
    assert "def model_failed(" in source
    assert "self.index_scan_completed + 1" in source
