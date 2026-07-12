"""Domain models for persistent experimentation notebooks."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _text(value: str, name: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{name} cannot be empty")
    return result


def _id(value: int | None, name: str = "id") -> int | None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
        raise ValueError(f"{name} must be a positive integer or None")
    return value


def _required_id(value: int | None, name: str) -> int:
    result = _id(value, name)
    if result is None:
        raise ValueError(f"{name} is required")
    return result


def _position(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("position must be an integer")
    if value < 0:
        raise ValueError("position cannot be negative")
    return value


class NotebookStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ExperimentStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class RunImageRole(StrEnum):
    CANDIDATE = "candidate"
    CONTROL = "control"
    REFERENCE = "reference"
    REPRESENTATIVE = "representative"
    REJECTED = "rejected"


class NoteScope(StrEnum):
    NOTEBOOK = "notebook"
    EXPERIMENT = "experiment"
    RUN = "run"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class Notebook:
    title: str
    description: str = ""
    status: NotebookStatus = NotebookStatus.ACTIVE
    id: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _id(self.id))
        object.__setattr__(self, "title", _text(self.title, "title", required=True))
        object.__setattr__(self, "description", _text(self.description, "description"))
        if not isinstance(self.status, NotebookStatus):
            object.__setattr__(self, "status", NotebookStatus(self.status))
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

    def with_updates(self, **changes: object) -> "Notebook":
        changes.setdefault("updated_at", utc_now())
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class Experiment:
    notebook_id: int
    title: str
    description: str = ""
    hypothesis: str = ""
    method: str = ""
    conclusion: str = ""
    status: ExperimentStatus = ExperimentStatus.PLANNED
    position: int = 0
    control_run_id: int | None = None
    id: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_id(self.notebook_id, "notebook_id")
        object.__setattr__(self, "id", _id(self.id))
        object.__setattr__(self, "control_run_id", _id(self.control_run_id, "control_run_id"))
        object.__setattr__(self, "title", _text(self.title, "title", required=True))
        for name in ("description", "hypothesis", "method", "conclusion"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.status, ExperimentStatus):
            object.__setattr__(self, "status", ExperimentStatus(self.status))
        _position(self.position)
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

    def with_updates(self, **changes: object) -> "Experiment":
        changes.setdefault("updated_at", utc_now())
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    experiment_id: int
    title: str
    notes: str = ""
    position: int = 0
    id: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_id(self.experiment_id, "experiment_id")
        object.__setattr__(self, "id", _id(self.id))
        object.__setattr__(self, "title", _text(self.title, "title", required=True))
        object.__setattr__(self, "notes", _text(self.notes, "notes"))
        _position(self.position)
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

    def with_updates(self, **changes: object) -> "ExperimentRun":
        changes.setdefault("updated_at", utc_now())
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class RunImage:
    run_id: int
    image_path: Path
    role: RunImageRole = RunImageRole.CANDIDATE
    notes: str = ""
    position: int = 0
    rating: int = 0
    id: int | None = None
    added_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_id(self.run_id, "run_id")
        object.__setattr__(self, "id", _id(self.id))
        if not isinstance(self.image_path, Path):
            raise TypeError("image_path must be a pathlib.Path")
        object.__setattr__(self, "image_path", self.image_path.resolve())
        if not isinstance(self.role, RunImageRole):
            object.__setattr__(self, "role", RunImageRole(self.role))
        object.__setattr__(self, "notes", _text(self.notes, "notes"))
        _position(self.position)
        if not isinstance(self.rating, int) or isinstance(self.rating, bool):
            raise TypeError("rating must be an integer")
        if not 0 <= self.rating <= 5:
            raise ValueError("rating must be between 0 and 5")
        _aware(self.added_at, "added_at")

    @property
    def is_available(self) -> bool:
        return self.image_path.is_file()


@dataclass(frozen=True, slots=True)
class ExperimentNote:
    scope: NoteScope
    content: str
    notebook_id: int | None = None
    experiment_id: int | None = None
    run_id: int | None = None
    run_image_id: int | None = None
    id: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _id(self.id))
        for name in ("notebook_id", "experiment_id", "run_id", "run_image_id"):
            object.__setattr__(self, name, _id(getattr(self, name), name))
        if not isinstance(self.scope, NoteScope):
            object.__setattr__(self, "scope", NoteScope(self.scope))
        object.__setattr__(self, "content", _text(self.content, "content", required=True))
        expected = {
            NoteScope.NOTEBOOK: "notebook_id",
            NoteScope.EXPERIMENT: "experiment_id",
            NoteScope.RUN: "run_id",
            NoteScope.IMAGE: "run_image_id",
        }[self.scope]
        owners = ("notebook_id", "experiment_id", "run_id", "run_image_id")
        populated = [name for name in owners if getattr(self, name) is not None]
        if populated != [expected]:
            raise ValueError(
                f"{self.scope.value} notes must specify only {expected}"
            )
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")


@dataclass(frozen=True, slots=True)
class ExperimentAggregate:
    experiment: Experiment
    runs: tuple[ExperimentRun, ...]
    images_by_run: dict[int, tuple[RunImage, ...]]
