from pathlib import Path

import pytest

from metaview.experiments import (
    ExperimentNotFoundError,
    ExperimentService,
    SQLiteExperimentRepository,
)


@pytest.fixture
def service():
    repository = SQLiteExperimentRepository(":memory:")
    value = ExperimentService(repository)
    yield value
    value.close()


def test_create_experiment_from_images_creates_one_ordered_run_per_image(service, tmp_path: Path):
    notebook = service.create_notebook("Sampler tests")
    paths = [tmp_path / "one.png", tmp_path / "two.png"]

    aggregate = service.create_experiment_from_images(notebook.id, "Euler versus RES", paths)

    assert aggregate.experiment.title == "Euler versus RES"
    assert [run.title for run in aggregate.runs] == ["Run 1", "Run 2"]
    assert [run.position for run in aggregate.runs] == [0, 1]
    assert [images[0].image_path for images in aggregate.images_by_run.values()] == [path.resolve() for path in paths]
    assert service.load_experiment(aggregate.experiment.id) == aggregate


def test_add_images_ignores_duplicates_and_preserves_positions(service, tmp_path: Path):
    notebook = service.create_notebook("Tests")
    experiment = service.create_experiment(notebook.id, "Experiment")
    run = service.create_run(experiment.id)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"

    initial = service.add_images(run.id, [first, first])
    additional = service.add_images(run.id, [first, second])

    assert len(initial) == 1
    assert len(additional) == 1
    assert additional[0].position == 1


def test_service_rejects_missing_parents_and_empty_selection(service):
    with pytest.raises(ExperimentNotFoundError):
        service.create_experiment(999, "Missing")
    notebook = service.create_notebook("Tests")
    with pytest.raises(ValueError):
        service.create_experiment_from_images(notebook.id, "Empty", [])
