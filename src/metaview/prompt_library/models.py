"""Domain models used by the metaView Prompt Library."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .normalization import normalize_prompt


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _normalise_tags(values: Iterable[str]) -> tuple[str, ...]:
    """Return unique, trimmed tags sorted case-insensitively.

    Tags compare case-insensitively for de-duplication, while the spelling of
    the first occurrence is retained for display.
    """

    by_key: dict[str, str] = {}
    for raw_value in values:
        if not isinstance(raw_value, str):
            raise TypeError("tags must contain only strings")
        value = raw_value.strip()
        if value:
            by_key.setdefault(value.casefold(), value)
    return tuple(sorted(by_key.values(), key=str.casefold))


@dataclass(frozen=True, slots=True)
class Prompt:
    """A curated Prompt Library entry.

    ``id`` is ``None`` until the entry has been persisted. A rating of zero
    means that the prompt is unrated.
    """

    title: str
    positive_prompt: str
    negative_prompt: str = ""
    notes: str = ""
    rating: int = 0
    tags: tuple[str, ...] = field(default_factory=tuple)
    id: int | None = None
    source_image: Path | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    prompt_key: str = field(init=False)

    def __post_init__(self) -> None:
        if self.id is not None and self.id < 1:
            raise ValueError("id must be a positive integer or None")
        if not isinstance(self.title, str):
            raise TypeError("title must be a string")
        title = self.title.strip()
        if not title:
            raise ValueError("title cannot be empty")
        if not isinstance(self.positive_prompt, str):
            raise TypeError("positive_prompt must be a string")
        prompt_key = normalize_prompt(self.positive_prompt)
        if not prompt_key:
            raise ValueError("positive_prompt cannot be empty")
        if not isinstance(self.negative_prompt, str):
            raise TypeError("negative_prompt must be a string")
        if not isinstance(self.notes, str):
            raise TypeError("notes must be a string")
        if not isinstance(self.rating, int) or isinstance(self.rating, bool):
            raise TypeError("rating must be an integer")
        if not 0 <= self.rating <= 5:
            raise ValueError("rating must be between 0 and 5")
        if self.source_image is not None and not isinstance(self.source_image, Path):
            raise TypeError("source_image must be a pathlib.Path or None")

        created_at = _require_aware_datetime(self.created_at, "created_at")
        updated_at = _require_aware_datetime(self.updated_at, "updated_at")
        if updated_at < created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "tags", _normalise_tags(self.tags))
        object.__setattr__(self, "prompt_key", prompt_key)

    @property
    def is_rated(self) -> bool:
        return self.rating > 0

    @property
    def is_favourite(self) -> bool:
        return self.rating >= 4

    def with_updates(self, **changes: object) -> "Prompt":
        """Return a new Prompt with selected fields replaced.

        ``updated_at`` is refreshed automatically unless supplied explicitly.
        """

        from dataclasses import replace

        changes.setdefault("updated_at", utc_now())
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class IndexedImage:
    """Metadata required to match an indexed image to library prompts."""

    path: Path
    positive_prompt: str
    modified_ns: int
    file_size: int
    model: str = ""
    sampler: str = ""
    scheduler: str = ""
    steps: str = ""
    resolution: str = ""
    loras_json: str = "[]"
    indexed_at: datetime = field(default_factory=utc_now)
    prompt_key: str = field(init=False)
    directory: Path = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("path must be a pathlib.Path")
        if not isinstance(self.positive_prompt, str):
            raise TypeError("positive_prompt must be a string")
        for field_name in ("model", "sampler", "scheduler", "steps", "resolution", "loras_json"):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} must be a string")
        if not isinstance(self.modified_ns, int) or isinstance(self.modified_ns, bool):
            raise TypeError("modified_ns must be an integer")
        if self.modified_ns < 0:
            raise ValueError("modified_ns cannot be negative")
        if not isinstance(self.file_size, int) or isinstance(self.file_size, bool):
            raise TypeError("file_size must be an integer")
        if self.file_size < 0:
            raise ValueError("file_size cannot be negative")
        _require_aware_datetime(self.indexed_at, "indexed_at")

        object.__setattr__(self, "directory", self.path.parent)
        object.__setattr__(
            self,
            "prompt_key",
            normalize_prompt(self.positive_prompt),
        )

    @property
    def has_prompt(self) -> bool:
        return bool(self.prompt_key)

    def matches(self, prompt: Prompt | str) -> bool:
        """Return whether this image exactly matches a prompt or prompt text."""

        key = prompt.prompt_key if isinstance(prompt, Prompt) else normalize_prompt(prompt)
        return self.prompt_key == key
