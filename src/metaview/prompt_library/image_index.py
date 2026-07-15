"""Application-facing contract and service for the global image index."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import IndexedImage, Prompt


@dataclass(frozen=True, slots=True)
class DirectoryImageCount:
    """Number of exact-prompt matches in one directory."""

    directory: Path
    image_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.directory, Path):
            raise TypeError("directory must be a pathlib.Path")
        if self.image_count < 0:
            raise ValueError("image_count cannot be negative")


@dataclass(frozen=True, slots=True)
class ImageIndexStatistics:
    """Aggregate information about the persistent image index."""

    image_count: int
    prompted_image_count: int
    directory_count: int


class ImageIndexRepository(ABC):
    """Persistence API for metadata needed by global prompt matching."""

    @abstractmethod
    def upsert(self, image: IndexedImage) -> IndexedImage:
        """Insert or replace one indexed image."""

    @abstractmethod
    def get(self, path: Path) -> IndexedImage | None:
        """Return one indexed image, or ``None`` when absent."""

    @abstractmethod
    def remove(self, path: Path) -> bool:
        """Remove one path and return whether it existed."""

    @abstractmethod
    def prune_directory(
        self,
        directory: Path,
        existing_paths: Iterable[Path],
    ) -> int:
        """Remove stale records for a scanned directory."""

    @abstractmethod
    def remove_missing(self) -> int:
        """Remove records whose files no longer exist."""

    @abstractmethod
    def all_images(self) -> list[IndexedImage]:
        """Return every indexed image in stable path order."""

    @abstractmethod
    def matching_images(self, prompt: Prompt | str) -> list[IndexedImage]:
        """Return images whose normalised prompt exactly matches."""

    @abstractmethod
    def count_matching(self, prompt: Prompt | str) -> int:
        """Return the number of exact-prompt matches."""

    @abstractmethod
    def directory_counts(
        self,
        prompt: Prompt | str,
    ) -> list[DirectoryImageCount]:
        """Return exact-prompt counts grouped by directory."""

    @abstractmethod
    def needs_refresh(
        self,
        path: Path,
        modified_ns: int,
        file_size: int,
    ) -> bool:
        """Return whether a path is absent or its file identity changed."""

    @abstractmethod
    def statistics(self) -> ImageIndexStatistics:
        """Return aggregate index statistics."""

    @abstractmethod
    def close(self) -> None:
        """Release repository resources."""

    def __enter__(self) -> "ImageIndexRepository":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


class ImageIndexService:
    """High-level operations used by metadata scanning and Prompt Library UI."""

    def __init__(self, repository: ImageIndexRepository) -> None:
        self.repository = repository

    def index_metadata(
        self,
        path: Path,
        positive_prompt: str,
        modified_ns: int,
        file_size: int,
        *,
        model: str = "",
        sampler: str = "",
        scheduler: str = "",
        steps: str = "",
        resolution: str = "",
        loras_json: str = "[]",
    ) -> IndexedImage:
        image = IndexedImage(
            path=path.resolve(),
            positive_prompt=positive_prompt,
            modified_ns=modified_ns,
            file_size=file_size,
            model=model,
            sampler=sampler,
            scheduler=scheduler,
            steps=steps,
            resolution=resolution,
            loras_json=loras_json,
        )
        return self.repository.upsert(image)

    def prune_directory(
        self,
        directory: Path,
        existing_paths: Iterable[Path],
    ) -> int:
        return self.repository.prune_directory(
            directory.resolve(),
            (path.resolve() for path in existing_paths),
        )

    def get(self, path: Path) -> IndexedImage | None:
        return self.repository.get(path)

    def needs_refresh(self, path: Path, modified_ns: int, file_size: int) -> bool:
        return self.repository.needs_refresh(path, modified_ns, file_size)

    def all_images(self) -> list[IndexedImage]:
        return self.repository.all_images()

    def all_paths(self) -> list[Path]:
        return [image.path for image in self.repository.all_images()]

    def matching_paths(self, prompt: Prompt | str) -> list[Path]:
        return [image.path for image in self.repository.matching_images(prompt)]

    def count_matching(self, prompt: Prompt | str) -> int:
        return self.repository.count_matching(prompt)

    def directory_counts(
        self,
        prompt: Prompt | str,
    ) -> list[DirectoryImageCount]:
        return self.repository.directory_counts(prompt)

    def remove_missing(self) -> int:
        return self.repository.remove_missing()

    def statistics(self) -> ImageIndexStatistics:
        return self.repository.statistics()

    def close(self) -> None:
        self.repository.close()
