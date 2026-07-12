"""Application services for experimentation notebooks."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import Experiment, ExperimentAggregate, ExperimentRun, Notebook, RunImage
from .repository import ExperimentNotFoundError, ExperimentRepository


class ExperimentService:
    def __init__(self, repository: ExperimentRepository) -> None:
        self.repository = repository

    def create_notebook(self, title: str, description: str = "") -> Notebook:
        return self.repository.add_notebook(Notebook(title=title, description=description))

    def create_experiment(self, notebook_id: int, title: str, *, description: str = "", hypothesis: str = "", method: str = "") -> Experiment:
        if self.repository.get_notebook(notebook_id) is None:
            raise ExperimentNotFoundError(f"Notebook {notebook_id} was not found")
        position = len(self.repository.list_experiments(notebook_id))
        return self.repository.add_experiment(Experiment(notebook_id=notebook_id, title=title, description=description, hypothesis=hypothesis, method=method, position=position))

    def create_run(self, experiment_id: int, title: str | None = None, *, notes: str = "") -> ExperimentRun:
        if self.repository.get_experiment(experiment_id) is None:
            raise ExperimentNotFoundError(f"Experiment {experiment_id} was not found")
        existing = self.repository.list_runs(experiment_id)
        position = len(existing)
        return self.repository.add_run(ExperimentRun(experiment_id=experiment_id, title=title or f"Run {position + 1}", notes=notes, position=position))

    def add_images(self, run_id: int, image_paths: Iterable[Path]) -> list[RunImage]:
        if self.repository.get_run(run_id) is None:
            raise ExperimentNotFoundError(f"Run {run_id} was not found")
        existing = {image.image_path for image in self.repository.list_run_images(run_id)}
        position = len(existing)
        added: list[RunImage] = []
        for path in image_paths:
            resolved = Path(path).resolve()
            if resolved in existing:
                continue
            saved = self.repository.add_run_image(RunImage(run_id=run_id, image_path=resolved, position=position))
            added.append(saved)
            existing.add(resolved)
            position += 1
        return added

    def create_experiment_from_images(self, notebook_id: int, title: str, image_paths: Iterable[Path], *, description: str = "") -> ExperimentAggregate:
        paths = [Path(path).resolve() for path in image_paths]
        if not paths:
            raise ValueError("At least one image is required")
        experiment = self.create_experiment(notebook_id, title, description=description)
        runs: list[ExperimentRun] = []
        images_by_run: dict[int, tuple[RunImage, ...]] = {}
        for index, path in enumerate(paths, start=1):
            run = self.create_run(experiment.id, f"Run {index}")  # type: ignore[arg-type]
            image = self.add_images(run.id, [path])[0]  # type: ignore[arg-type]
            runs.append(run)
            images_by_run[run.id] = (image,)  # type: ignore[index]
        return ExperimentAggregate(experiment=experiment, runs=tuple(runs), images_by_run=images_by_run)

    def load_experiment(self, experiment_id: int) -> ExperimentAggregate:
        experiment = self.repository.get_experiment(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(f"Experiment {experiment_id} was not found")
        runs = self.repository.list_runs(experiment_id)
        return ExperimentAggregate(
            experiment=experiment,
            runs=tuple(runs),
            images_by_run={run.id: tuple(self.repository.list_run_images(run.id)) for run in runs if run.id is not None},
        )

    def close(self) -> None:
        self.repository.close()
