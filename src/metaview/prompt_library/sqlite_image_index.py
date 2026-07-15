"""SQLite adapter for the global image metadata index."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .image_index import (
    DirectoryImageCount,
    ImageIndexRepository,
    ImageIndexStatistics,
)
from .models import IndexedImage, Prompt
from .normalization import normalize_prompt

_SCHEMA_VERSION = 3


class SQLiteImageIndexRepository(ImageIndexRepository):
    """Persist the global image index in a local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if str(database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(database_path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = int(
            self._connection.execute("PRAGMA user_version").fetchone()[0]
        )
        if version > _SCHEMA_VERSION:
            raise RuntimeError(
                "The image index was created by a newer version of metaView."
            )
        if version < 1:
            with self._connection:
                self._connection.executescript(
                    """
                    CREATE TABLE indexed_images (
                        path TEXT PRIMARY KEY,
                        directory TEXT NOT NULL,
                        positive_prompt TEXT NOT NULL DEFAULT '',
                        prompt_key TEXT NOT NULL DEFAULT '',
                        model TEXT NOT NULL DEFAULT '',
                        sampler TEXT NOT NULL DEFAULT '',
                        scheduler TEXT NOT NULL DEFAULT '',
                        steps TEXT NOT NULL DEFAULT '',
                        resolution TEXT NOT NULL DEFAULT '',
                        loras_json TEXT NOT NULL DEFAULT '[]',
                        metadata_version INTEGER NOT NULL DEFAULT 1,
                        modified_ns INTEGER NOT NULL,
                        file_size INTEGER NOT NULL,
                        indexed_at TEXT NOT NULL
                    );

                    CREATE INDEX idx_indexed_images_prompt
                        ON indexed_images(prompt_key);
                    CREATE INDEX idx_indexed_images_directory
                        ON indexed_images(directory);
                    """
                )
                self._connection.execute("PRAGMA user_version = 1")
        if version < 2:
            columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(indexed_images)")
            }
            additions = {
                "model": "TEXT NOT NULL DEFAULT ''",
                "sampler": "TEXT NOT NULL DEFAULT ''",
                "scheduler": "TEXT NOT NULL DEFAULT ''",
                "steps": "TEXT NOT NULL DEFAULT ''",
                "resolution": "TEXT NOT NULL DEFAULT ''",
                "loras_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            with self._connection:
                for name, definition in additions.items():
                    if name not in columns:
                        self._connection.execute(
                            f"ALTER TABLE indexed_images ADD COLUMN {name} {definition}"
                        )
                self._connection.execute("PRAGMA user_version = 2")
        if version < 3:
            columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(indexed_images)")
            }
            with self._connection:
                if "metadata_version" not in columns:
                    self._connection.execute(
                        "ALTER TABLE indexed_images ADD COLUMN metadata_version INTEGER NOT NULL DEFAULT 0"
                    )
                self._connection.execute("PRAGMA user_version = 3")

    def upsert(self, image: IndexedImage) -> IndexedImage:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO indexed_images(
                    path, directory, positive_prompt, prompt_key,
                    model, sampler, scheduler, steps, resolution, loras_json, metadata_version,
                    modified_ns, file_size, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    directory=excluded.directory,
                    positive_prompt=excluded.positive_prompt,
                    prompt_key=excluded.prompt_key,
                    model=excluded.model,
                    sampler=excluded.sampler,
                    scheduler=excluded.scheduler,
                    steps=excluded.steps,
                    resolution=excluded.resolution,
                    loras_json=excluded.loras_json,
                    metadata_version=excluded.metadata_version,
                    modified_ns=excluded.modified_ns,
                    file_size=excluded.file_size,
                    indexed_at=excluded.indexed_at
                """,
                (
                    str(image.path),
                    str(image.directory),
                    image.positive_prompt,
                    image.prompt_key,
                    image.model,
                    image.sampler,
                    image.scheduler,
                    image.steps,
                    image.resolution,
                    image.loras_json,
                    image.modified_ns,
                    image.file_size,
                    image.indexed_at.isoformat(),
                ),
            )
        saved = self.get(image.path)
        if saved is None:  # pragma: no cover - defensive database check
            raise RuntimeError("The indexed image was not saved.")
        return saved

    def get(self, path: Path) -> IndexedImage | None:
        row = self._connection.execute(
            "SELECT * FROM indexed_images WHERE path=?",
            (str(path.resolve()),),
        ).fetchone()
        return self._row_to_image(row) if row is not None else None

    def remove(self, path: Path) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM indexed_images WHERE path=?",
                (str(path.resolve()),),
            )
        return cursor.rowcount > 0

    def prune_directory(
        self,
        directory: Path,
        existing_paths: Iterable[Path],
    ) -> int:
        directory_key = str(directory.resolve())
        existing = {str(path.resolve()) for path in existing_paths}
        rows = self._connection.execute(
            "SELECT path FROM indexed_images WHERE directory=?",
            (directory_key,),
        ).fetchall()
        stale = [
            str(row["path"])
            for row in rows
            if str(row["path"]) not in existing
        ]
        if stale:
            with self._connection:
                self._connection.executemany(
                    "DELETE FROM indexed_images WHERE path=?",
                    [(path,) for path in stale],
                )
        return len(stale)

    def remove_missing(self) -> int:
        rows = self._connection.execute(
            "SELECT path FROM indexed_images"
        ).fetchall()
        missing = [
            str(row["path"])
            for row in rows
            if not Path(str(row["path"])).is_file()
        ]
        if missing:
            with self._connection:
                self._connection.executemany(
                    "DELETE FROM indexed_images WHERE path=?",
                    [(path,) for path in missing],
                )
        return len(missing)

    def all_images(self) -> list[IndexedImage]:
        rows = self._connection.execute(
            "SELECT * FROM indexed_images ORDER BY path COLLATE NOCASE"
        ).fetchall()
        return [self._row_to_image(row) for row in rows]

    def matching_images(self, prompt: Prompt | str) -> list[IndexedImage]:
        key = self._prompt_key(prompt)
        if not key:
            return []
        rows = self._connection.execute(
            """
            SELECT * FROM indexed_images
            WHERE prompt_key=?
            ORDER BY directory COLLATE NOCASE, path COLLATE NOCASE
            """,
            (key,),
        ).fetchall()
        return [self._row_to_image(row) for row in rows]

    def count_matching(self, prompt: Prompt | str) -> int:
        key = self._prompt_key(prompt)
        if not key:
            return 0
        row = self._connection.execute(
            "SELECT COUNT(*) FROM indexed_images WHERE prompt_key=?",
            (key,),
        ).fetchone()
        return int(row[0])

    def directory_counts(
        self,
        prompt: Prompt | str,
    ) -> list[DirectoryImageCount]:
        key = self._prompt_key(prompt)
        if not key:
            return []
        rows = self._connection.execute(
            """
            SELECT directory, COUNT(*) AS image_count
            FROM indexed_images
            WHERE prompt_key=?
            GROUP BY directory
            ORDER BY directory COLLATE NOCASE
            """,
            (key,),
        ).fetchall()
        return [
            DirectoryImageCount(
                directory=Path(str(row["directory"])),
                image_count=int(row["image_count"]),
            )
            for row in rows
        ]

    def needs_refresh(
        self,
        path: Path,
        modified_ns: int,
        file_size: int,
    ) -> bool:
        row = self._connection.execute(
            """
            SELECT modified_ns, file_size, metadata_version
            FROM indexed_images WHERE path=?
            """,
            (str(path.resolve()),),
        ).fetchone()
        return (
            row is None
            or int(row["metadata_version"]) < 1
            or int(row["modified_ns"]) != modified_ns
            or int(row["file_size"]) != file_size
        )

    def statistics(self) -> ImageIndexStatistics:
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS image_count,
                SUM(CASE WHEN prompt_key<>'' THEN 1 ELSE 0 END)
                    AS prompted_image_count,
                COUNT(DISTINCT directory) AS directory_count
            FROM indexed_images
            """
        ).fetchone()
        return ImageIndexStatistics(
            image_count=int(row["image_count"] or 0),
            prompted_image_count=int(row["prompted_image_count"] or 0),
            directory_count=int(row["directory_count"] or 0),
        )

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _prompt_key(prompt: Prompt | str) -> str:
        return prompt.prompt_key if isinstance(prompt, Prompt) else normalize_prompt(prompt)

    @staticmethod
    def _row_to_image(row: sqlite3.Row) -> IndexedImage:
        return IndexedImage(
            path=Path(str(row["path"])),
            positive_prompt=str(row["positive_prompt"]),
            modified_ns=int(row["modified_ns"]),
            file_size=int(row["file_size"]),
            model=str(row["model"]),
            sampler=str(row["sampler"]),
            scheduler=str(row["scheduler"]),
            steps=str(row["steps"]),
            resolution=str(row["resolution"]),
            loras_json=str(row["loras_json"]),
            indexed_at=datetime.fromisoformat(str(row["indexed_at"])),
        )
