"""Repository contract for experimentation notebooks."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Experiment, ExperimentNote, ExperimentRun, Notebook, RunImage


class ExperimentNotFoundError(LookupError):
    pass


class ExperimentRepository(ABC):
    @abstractmethod
    def add_notebook(self, notebook: Notebook) -> Notebook: ...

    @abstractmethod
    def update_notebook(self, notebook: Notebook) -> Notebook: ...

    @abstractmethod
    def get_notebook(self, notebook_id: int) -> Notebook | None: ...

    @abstractmethod
    def list_notebooks(self, *, include_archived: bool = False) -> list[Notebook]: ...

    @abstractmethod
    def delete_notebook(self, notebook_id: int) -> bool: ...

    @abstractmethod
    def add_experiment(self, experiment: Experiment) -> Experiment: ...

    @abstractmethod
    def update_experiment(self, experiment: Experiment) -> Experiment: ...

    @abstractmethod
    def get_experiment(self, experiment_id: int) -> Experiment | None: ...

    @abstractmethod
    def list_experiments(self, notebook_id: int) -> list[Experiment]: ...

    @abstractmethod
    def delete_experiment(self, experiment_id: int) -> bool: ...

    @abstractmethod
    def add_run(self, run: ExperimentRun) -> ExperimentRun: ...

    @abstractmethod
    def update_run(self, run: ExperimentRun) -> ExperimentRun: ...

    @abstractmethod
    def get_run(self, run_id: int) -> ExperimentRun | None: ...

    @abstractmethod
    def list_runs(self, experiment_id: int) -> list[ExperimentRun]: ...

    @abstractmethod
    def delete_run(self, run_id: int) -> bool: ...

    @abstractmethod
    def add_run_image(self, image: RunImage) -> RunImage: ...

    @abstractmethod
    def list_run_images(self, run_id: int) -> list[RunImage]: ...

    @abstractmethod
    def remove_run_image(self, run_image_id: int) -> bool: ...

    @abstractmethod
    def add_note(self, note: ExperimentNote) -> ExperimentNote: ...

    @abstractmethod
    def list_notes(self, *, notebook_id: int | None = None, experiment_id: int | None = None, run_id: int | None = None, run_image_id: int | None = None) -> list[ExperimentNote]: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> "ExperimentRepository":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
