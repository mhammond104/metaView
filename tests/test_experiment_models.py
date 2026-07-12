from datetime import datetime
from pathlib import Path

import pytest

from metaview.experiments import (
    Experiment,
    ExperimentNote,
    Notebook,
    NoteScope,
    RunImage,
)


def test_notebook_trims_and_validates_title():
    notebook = Notebook(title="  Portrait tests  ", description=" notes ")
    assert notebook.title == "Portrait tests"
    assert notebook.description == "notes"
    with pytest.raises(ValueError):
        Notebook(title="   ")


def test_models_require_timezone_aware_dates():
    with pytest.raises(ValueError):
        Notebook(title="Tests", created_at=datetime.now())


def test_run_image_keeps_missing_path_reference(tmp_path: Path):
    missing = tmp_path / "missing.png"
    image = RunImage(run_id=1, image_path=missing)
    assert image.image_path == missing.resolve()
    assert image.is_available is False


def test_note_requires_owner_matching_scope():
    with pytest.raises(ValueError):
        ExperimentNote(scope=NoteScope.RUN, content="Observation")
    note = ExperimentNote(scope=NoteScope.EXPERIMENT, experiment_id=2, content="Useful")
    assert note.experiment_id == 2


def test_experiment_rejects_negative_position():
    with pytest.raises(ValueError):
        Experiment(notebook_id=1, title="Test", position=-1)
