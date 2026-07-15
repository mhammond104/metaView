from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Collection:
    id: int
    name: str
    created_at: datetime
    updated_at: datetime
    colour: str = ""
    icon: str = ""


class CollectionRepository:
    """SQLite-backed static image collections.

    Collections store references only; image files remain on disk.
    """

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
                CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    colour TEXT NOT NULL DEFAULT '',
                    icon TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collection_images (
                    collection_id INTEGER NOT NULL
                        REFERENCES collections(id) ON DELETE CASCADE,
                    image_path TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(collection_id, image_path)
                );
                CREATE INDEX IF NOT EXISTS idx_collection_images_path
                    ON collection_images(image_path);
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _collection(row: sqlite3.Row) -> Collection:
        return Collection(
            id=int(row["id"]),
            name=str(row["name"]),
            colour=str(row["colour"]),
            icon=str(row["icon"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def create(self, name: str) -> Collection:
        clean = name.strip()
        if not clean:
            raise ValueError("Collection name cannot be empty")
        now = self._now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO collections(name,created_at,updated_at) VALUES(?,?,?)",
                    (clean, now.isoformat(), now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A collection named "{clean}" already exists') from exc
        return Collection(int(cursor.lastrowid), clean, now, now)

    def rename(self, collection_id: int, name: str) -> Collection:
        clean = name.strip()
        if not clean:
            raise ValueError("Collection name cannot be empty")
        now = self._now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "UPDATE collections SET name=?,updated_at=? WHERE id=?",
                    (clean, now.isoformat(), collection_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A collection named "{clean}" already exists') from exc
        if cursor.rowcount == 0:
            raise LookupError(f"Collection {collection_id} was not found")
        collection = self.get(collection_id)
        assert collection is not None
        return collection

    def delete(self, collection_id: int) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM collections WHERE id=?", (collection_id,)
            )
        return cursor.rowcount > 0

    def get(self, collection_id: int) -> Collection | None:
        row = self._connection.execute(
            "SELECT * FROM collections WHERE id=?", (collection_id,)
        ).fetchone()
        return self._collection(row) if row else None

    def list(self) -> list[Collection]:
        rows = self._connection.execute(
            "SELECT * FROM collections ORDER BY name COLLATE NOCASE,id"
        )
        return [self._collection(row) for row in rows]

    def add_images(self, collection_id: int, paths: list[Path]) -> int:
        now = self._now().isoformat()
        added = 0
        with self._connection:
            for path in paths:
                resolved = str(path.expanduser().resolve())
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO collection_images(collection_id,image_path,added_at) VALUES(?,?,?)",
                    (collection_id, resolved, now),
                )
                added += cursor.rowcount
            self._connection.execute(
                "UPDATE collections SET updated_at=? WHERE id=?", (now, collection_id)
            )
        return added

    def remove_images(self, collection_id: int, paths: list[Path]) -> int:
        removed = 0
        with self._connection:
            for path in paths:
                cursor = self._connection.execute(
                    "DELETE FROM collection_images WHERE collection_id=? AND image_path=?",
                    (collection_id, str(path.expanduser().resolve())),
                )
                removed += cursor.rowcount
        return removed

    def images(self, collection_id: int, *, existing_only: bool = True) -> list[Path]:
        rows = self._connection.execute(
            "SELECT image_path FROM collection_images WHERE collection_id=? ORDER BY added_at,rowid",
            (collection_id,),
        )
        paths = [Path(str(row["image_path"])) for row in rows]
        return [path for path in paths if path.is_file()] if existing_only else paths

    def count(self, collection_id: int) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM collection_images WHERE collection_id=?",
            (collection_id,),
        ).fetchone()
        return int(row["count"])

    def close(self) -> None:
        self._connection.close()
