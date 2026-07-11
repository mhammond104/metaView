"""One-time import from the basic Prompt Library shipped in metaView v0.1.0."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Prompt
from .repository import DuplicatePromptError, PromptRepository


def import_legacy_prompt_library(
    legacy_database: Path,
    repository: PromptRepository,
) -> int:
    """Import compatible v0.1.0 entries when the new library is empty.

    The legacy schema permitted negative-only entries, while the v0.2 domain
    model requires a positive prompt. Those entries are deliberately skipped.
    Existing exact prompts are also skipped, making this operation idempotent.
    """

    if repository.statistics().prompt_count or not legacy_database.is_file():
        return 0

    connection = sqlite3.connect(legacy_database)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prompts'"
        ).fetchone()
        if table is None:
            return 0
        rows = connection.execute("SELECT * FROM prompts ORDER BY id").fetchall()
    finally:
        connection.close()

    imported = 0
    for row in rows:
        positive = str(row["positive_prompt"] or "")
        if not positive.strip():
            continue
        source_value = str(row["source_image"] or "").strip()
        tags = tuple(
            value.strip()
            for value in str(row["tags"] or "").split(",")
            if value.strip()
        )
        try:
            repository.add(
                Prompt(
                    title=str(row["title"] or "Untitled prompt"),
                    positive_prompt=positive,
                    negative_prompt=str(row["negative_prompt"] or ""),
                    notes=str(row["description"] or ""),
                    tags=tags,
                    source_image=Path(source_value) if source_value else None,
                )
            )
        except (DuplicatePromptError, ValueError):
            continue
        imported += 1
    return imported
