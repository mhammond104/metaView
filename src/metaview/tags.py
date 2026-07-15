from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ImageTag:
    id: int
    name: str
    created_at: datetime
    updated_at: datetime


class TagRepository:
    """SQLite-backed user tags stored independently of image metadata."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS image_tags (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS image_tag_assignments (
                    tag_id INTEGER NOT NULL REFERENCES image_tags(id) ON DELETE CASCADE,
                    image_path TEXT NOT NULL,
                    assigned_at TEXT NOT NULL,
                    PRIMARY KEY(tag_id, image_path)
                );
                CREATE INDEX IF NOT EXISTS idx_image_tag_assignments_path
                    ON image_tag_assignments(image_path);
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _tag(row: sqlite3.Row) -> ImageTag:
        return ImageTag(
            id=int(row["id"]),
            name=str(row["name"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def create(self, name: str) -> ImageTag:
        clean = name.strip()
        if not clean:
            raise ValueError("Tag name cannot be empty")
        now = self._now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO image_tags(name,created_at,updated_at) VALUES(?,?,?)",
                    (clean, now.isoformat(), now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A tag named "{clean}" already exists') from exc
        return ImageTag(int(cursor.lastrowid), clean, now, now)

    def rename(self, tag_id: int, name: str) -> ImageTag:
        clean = name.strip()
        if not clean:
            raise ValueError("Tag name cannot be empty")
        now = self._now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "UPDATE image_tags SET name=?,updated_at=? WHERE id=?",
                    (clean, now.isoformat(), tag_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A tag named "{clean}" already exists') from exc
        if cursor.rowcount == 0:
            raise LookupError(f"Tag {tag_id} was not found")
        tag = self.get(tag_id)
        assert tag is not None
        return tag

    def delete(self, tag_id: int) -> bool:
        with self._connection:
            cursor = self._connection.execute("DELETE FROM image_tags WHERE id=?", (tag_id,))
        return cursor.rowcount > 0

    def get(self, tag_id: int) -> ImageTag | None:
        row = self._connection.execute("SELECT * FROM image_tags WHERE id=?", (tag_id,)).fetchone()
        return self._tag(row) if row else None

    def list(self) -> list[ImageTag]:
        rows = self._connection.execute("SELECT * FROM image_tags ORDER BY name COLLATE NOCASE,id")
        return [self._tag(row) for row in rows]

    def count(self, tag_id: int) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM image_tag_assignments WHERE tag_id=?", (tag_id,)
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def _path(path: Path) -> str:
        return str(path.expanduser().resolve())

    def assign(self, tag_id: int, paths: Iterable[Path]) -> int:
        now = self._now().isoformat()
        added = 0
        with self._connection:
            for path in paths:
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO image_tag_assignments(tag_id,image_path,assigned_at) VALUES(?,?,?)",
                    (tag_id, self._path(path), now),
                )
                added += cursor.rowcount
        return added

    def unassign(self, tag_id: int, paths: Iterable[Path]) -> int:
        removed = 0
        with self._connection:
            for path in paths:
                cursor = self._connection.execute(
                    "DELETE FROM image_tag_assignments WHERE tag_id=? AND image_path=?",
                    (tag_id, self._path(path)),
                )
                removed += cursor.rowcount
        return removed

    def tags_for_path(self, path: Path) -> list[ImageTag]:
        rows = self._connection.execute(
            """
            SELECT t.* FROM image_tags t
            JOIN image_tag_assignments a ON a.tag_id=t.id
            WHERE a.image_path=? ORDER BY t.name COLLATE NOCASE,t.id
            """,
            (self._path(path),),
        )
        return [self._tag(row) for row in rows]

    def tag_ids_for_path(self, path: Path) -> set[int]:
        rows = self._connection.execute(
            "SELECT tag_id FROM image_tag_assignments WHERE image_path=?",
            (self._path(path),),
        )
        return {int(row["tag_id"]) for row in rows}

    def paths(self, tag_id: int, *, existing_only: bool = True) -> list[Path]:
        rows = self._connection.execute(
            "SELECT image_path FROM image_tag_assignments WHERE tag_id=? ORDER BY assigned_at,rowid",
            (tag_id,),
        )
        paths = [Path(str(row["image_path"])) for row in rows]
        return [path for path in paths if path.is_file()] if existing_only else paths

    def names_for_path(self, path: Path) -> tuple[str, ...]:
        return tuple(tag.name for tag in self.tags_for_path(path))

    def close(self) -> None:
        self._connection.close()
