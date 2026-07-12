from pathlib import Path

from PySide6.QtCore import QUrl

from metaview.widgets import workflow_drag_mime_data


def test_comparison_and_experiment_views_use_shared_parameter_service() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "metaview" / "dialogs.py"
    ).read_text(encoding="utf-8")

    assert source.count("compare_parameters(") >= 2
    assert "format_resolution(path)" in source


def test_workflow_drag_payload_contains_local_file_url(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow example.json"
    workflow.write_text("{}", encoding="utf-8")

    mime_data = workflow_drag_mime_data(workflow)

    assert mime_data.hasUrls()
    assert mime_data.urls() == [QUrl.fromLocalFile(str(workflow.resolve()))]
    assert mime_data.text() == str(workflow.resolve())
