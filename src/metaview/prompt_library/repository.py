"""Persistence contract for the metaView Prompt Library."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import Prompt


class PromptLibraryError(RuntimeError):
    """Base class for Prompt Library persistence errors."""


class DuplicatePromptError(PromptLibraryError):
    """Raised when a repository already contains an exact prompt."""

    def __init__(self, existing: Prompt) -> None:
        self.existing = existing
        super().__init__(
            f'This exact prompt is already saved as "{existing.title}".'
        )


class PromptNotFoundError(PromptLibraryError):
    """Raised when a requested persisted prompt does not exist."""

    def __init__(self, prompt_id: int) -> None:
        self.prompt_id = prompt_id
        super().__init__(f"Prompt {prompt_id} does not exist.")


class PromptSort(str, Enum):
    """Supported repository sort orders."""

    TITLE = "title"
    RATING_DESC = "rating_desc"
    CREATED_DESC = "created_desc"
    UPDATED_DESC = "updated_desc"


@dataclass(frozen=True, slots=True)
class PromptSearch:
    """Filtering and ordering options for a prompt query."""

    text: str = ""
    tags: tuple[str, ...] = ()
    minimum_rating: int = 0
    unrated_only: bool = False
    untagged_only: bool = False
    favourites_only: bool = False
    match_all_tags: bool = True
    sort: PromptSort = PromptSort.RATING_DESC

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.minimum_rating, int) or isinstance(
            self.minimum_rating, bool
        ):
            raise TypeError("minimum_rating must be an integer")
        if not 0 <= self.minimum_rating <= 5:
            raise ValueError("minimum_rating must be between 0 and 5")
        if not isinstance(self.sort, PromptSort):
            raise TypeError("sort must be a PromptSort")

        normalised_tags: dict[str, str] = {}
        for tag in self.tags:
            if not isinstance(tag, str):
                raise TypeError("tags must contain only strings")
            cleaned = tag.strip()
            if cleaned:
                normalised_tags.setdefault(cleaned.casefold(), cleaned)
        object.__setattr__(
            self,
            "tags",
            tuple(sorted(normalised_tags.values(), key=str.casefold)),
        )


@dataclass(frozen=True, slots=True)
class TagSummary:
    """A user-defined tag and the number of prompts using it."""

    name: str
    prompt_count: int


@dataclass(frozen=True, slots=True)
class PromptLibraryStatistics:
    """Aggregate information about a Prompt Library."""

    prompt_count: int
    rated_count: int
    favourite_count: int
    untagged_count: int
    tag_count: int


class PromptRepository(ABC):
    """Abstract persistence API used by Prompt Library services and UI."""

    @abstractmethod
    def add(self, prompt: Prompt) -> Prompt:
        """Persist a new prompt and return it with its assigned ID."""

    @abstractmethod
    def update(self, prompt: Prompt) -> Prompt:
        """Persist changes to an existing prompt and return the saved value."""

    @abstractmethod
    def delete(self, prompt_id: int) -> None:
        """Delete one prompt."""

    @abstractmethod
    def get(self, prompt_id: int) -> Prompt | None:
        """Return one prompt, or ``None`` when it does not exist."""

    @abstractmethod
    def find_exact(self, positive_prompt: str) -> Prompt | None:
        """Return the entry whose normalised positive prompt exactly matches."""

    @abstractmethod
    def search(self, query: PromptSearch | None = None) -> list[Prompt]:
        """Return prompts satisfying a query."""

    @abstractmethod
    def all_tags(self) -> list[TagSummary]:
        """Return all tags and prompt counts."""

    @abstractmethod
    def statistics(self) -> PromptLibraryStatistics:
        """Return aggregate library statistics."""

    @abstractmethod
    def close(self) -> None:
        """Release repository resources."""

    def __enter__(self) -> "PromptRepository":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
