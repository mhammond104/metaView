"""Public Prompt Library domain and persistence API."""

from .image_index import (
    DirectoryImageCount,
    ImageIndexRepository,
    ImageIndexService,
    ImageIndexStatistics,
)
from .models import IndexedImage, Prompt, utc_now
from .normalization import normalize_prompt
from .repository import (
    DuplicatePromptError,
    PromptLibraryError,
    PromptLibraryStatistics,
    PromptNotFoundError,
    PromptRepository,
    PromptSearch,
    PromptSort,
    TagSummary,
)
from .sqlite import SQLitePromptRepository
from .sqlite_image_index import SQLiteImageIndexRepository

__all__ = [
    "DirectoryImageCount",
    "DuplicatePromptError",
    "ImageIndexRepository",
    "ImageIndexService",
    "ImageIndexStatistics",
    "IndexedImage",
    "Prompt",
    "PromptLibraryError",
    "PromptLibraryStatistics",
    "PromptNotFoundError",
    "PromptRepository",
    "PromptSearch",
    "PromptSort",
    "SQLiteImageIndexRepository",
    "SQLitePromptRepository",
    "TagSummary",
    "normalize_prompt",
    "utc_now",
]
from .ui import (
    PromptEditorDialog,
    PromptLibraryController,
    PromptLibraryDialog,
    StarRatingWidget,
)

__all__ += [
    "PromptEditorDialog",
    "PromptLibraryController",
    "PromptLibraryDialog",
    "StarRatingWidget",
]
from .legacy import import_legacy_prompt_library

__all__ += ["import_legacy_prompt_library"]
