from pathlib import Path

import pytest

from metaview.experiments import (
    Experiment,
    ExperimentNote,
    ExperimentRun,
    Notebook,
    NotebookStatus,
    NoteScope,
    RunImage,
    SQLiteExperimentRepository,
)


@pytest.fixture
def repository():
    repo = SQLiteExperimentRepository(":memory:")
    yield repo
    repo.close()


def test_schema_version_is_created(repository):
    assert repository._connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_notebook_crud_and_archive_filter(repository):
    first = repository.add_notebook(Notebook(title="B notebook"))
    second = repository.add_notebook(Notebook(title="A notebook"))
    archived = repository.update_notebook(second.with_updates(status=NotebookStatus.ARCHIVED))

    assert repository.get_notebook(first.id) == first
    assert repository.list_notebooks() == [first]
    assert repository.list_notebooks(include_archived=True) == [archived, first]
    assert repository.delete_notebook(first.id) is True
    assert repository.delete_notebook(first.id) is False


def test_complete_hierarchy_round_trip_and_order(repository, tmp_path: Path):
    notebook = repository.add_notebook(Notebook(title="Notebook"))
    later = repository.add_experiment(Experiment(notebook_id=notebook.id, title="Later", position=2))
    earlier = repository.add_experiment(Experiment(notebook_id=notebook.id, title="Earlier", position=0))
    run_b = repository.add_run(ExperimentRun(experiment_id=earlier.id, title="B", position=1))
    run_a = repository.add_run(ExperimentRun(experiment_id=earlier.id, title="A", position=0))
    image_b = repository.add_run_image(RunImage(run_id=run_a.id, image_path=tmp_path / "b.png", position=1))
    image_a = repository.add_run_image(RunImage(run_id=run_a.id, image_path=tmp_path / "a.png", position=0))

    assert repository.list_experiments(notebook.id) == [earlier, later]
    assert repository.list_runs(earlier.id) == [run_a, run_b]
    assert repository.list_run_images(run_a.id) == [image_a, image_b]


def test_cascade_delete_removes_children(repository, tmp_path: Path):
    notebook = repository.add_notebook(Notebook(title="Notebook"))
    experiment = repository.add_experiment(Experiment(notebook_id=notebook.id, title="Experiment"))
    run = repository.add_run(ExperimentRun(experiment_id=experiment.id, title="Run"))
    image = repository.add_run_image(RunImage(run_id=run.id, image_path=tmp_path / "image.png"))
    repository.add_note(ExperimentNote(scope=NoteScope.IMAGE, run_image_id=image.id, content="Note"))

    assert repository.delete_notebook(notebook.id)
    assert repository.get_experiment(experiment.id) is None
    assert repository.get_run(run.id) is None
    assert repository.list_run_images(run.id) == []
    assert repository._connection.execute("SELECT COUNT(*) FROM experiment_notes").fetchone()[0] == 0


def test_notes_are_loaded_for_one_owner(repository):
    notebook = repository.add_notebook(Notebook(title="Notebook"))
    note = repository.add_note(ExperimentNote(scope=NoteScope.NOTEBOOK, notebook_id=notebook.id, content="First note"))
    assert repository.list_notes(notebook_id=notebook.id) == [note]
    with pytest.raises(ValueError):
        repository.list_notes()
    with pytest.raises(ValueError):
        repository.list_notes(notebook_id=notebook.id, experiment_id=1)


def test_duplicate_image_in_same_run_is_rejected(repository, tmp_path: Path):
    notebook = repository.add_notebook(Notebook(title="Notebook"))
    experiment = repository.add_experiment(Experiment(notebook_id=notebook.id, title="Experiment"))
    run = repository.add_run(ExperimentRun(experiment_id=experiment.id, title="Run"))
    image = RunImage(run_id=run.id, image_path=tmp_path / "image.png")
    repository.add_run_image(image)
    with pytest.raises(Exception):
        repository.add_run_image(image)
