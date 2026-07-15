"""Persistent registration of folders that belong to the managed library."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LibraryFolder:
    id: int
    path: Path
    created_at: datetime


class LibraryFolderRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS library_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def _normalise(path: Path) -> Path:
        return path.expanduser().resolve()

    def add(self, path: Path) -> LibraryFolder:
        resolved = self._normalise(path)
        if not resolved.is_dir():
            raise ValueError("library folder must exist")
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            "INSERT OR IGNORE INTO library_folders(path, created_at) VALUES (?, ?)",
            (str(resolved), now),
        )
        self.connection.commit()
        folder = self.get_by_path(resolved)
        if folder is None:
            raise RuntimeError("unable to register library folder")
        return folder

    def remove(self, folder_id: int) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM library_folders WHERE id = ?", (folder_id,)
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def list(self) -> list[LibraryFolder]:
        rows = self.connection.execute(
            "SELECT id, path, created_at FROM library_folders ORDER BY path COLLATE NOCASE"
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, folder_id: int) -> LibraryFolder | None:
        row = self.connection.execute(
            "SELECT id, path, created_at FROM library_folders WHERE id = ?",
            (folder_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_by_path(self, path: Path) -> LibraryFolder | None:
        resolved = self._normalise(path)
        row = self.connection.execute(
            "SELECT id, path, created_at FROM library_folders WHERE path = ?",
            (str(resolved),),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def contains_folder(self, path: Path) -> bool:
        return self.get_by_path(path) is not None

    def contains_path(self, path: Path) -> bool:
        resolved = self._normalise(path)
        for folder in self.list():
            try:
                resolved.relative_to(folder.path)
                return True
            except ValueError:
                continue
        return False

    def paths(self) -> tuple[Path, ...]:
        return tuple(folder.path for folder in self.list())

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LibraryFolder:
        return LibraryFolder(
            id=int(row["id"]),
            path=Path(str(row["path"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
