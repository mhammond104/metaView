"""SQLite implementation of the Prompt Library repository."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Prompt
from .normalization import normalize_prompt
from .repository import (
    DuplicatePromptError,
    PromptLibraryStatistics,
    PromptNotFoundError,
    PromptRepository,
    PromptSearch,
    PromptSort,
    TagSummary,
)

_SCHEMA_VERSION = 1


class SQLitePromptRepository(PromptRepository):
    """Persist Prompt Library entries in a local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if str(database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(database_path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        current_version = int(
            self._connection.execute("PRAGMA user_version").fetchone()[0]
        )
        if current_version > _SCHEMA_VERSION:
            raise RuntimeError(
                "The Prompt Library database was created by a newer version "
                "of metaView."
            )
        if current_version < 1:
            with self._connection:
                self._connection.executescript(
                    """
                    CREATE TABLE prompts (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        positive_prompt TEXT NOT NULL,
                        prompt_key TEXT NOT NULL UNIQUE,
                        negative_prompt TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        rating INTEGER NOT NULL DEFAULT 0
                            CHECK (rating BETWEEN 0 AND 5),
                        source_image TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX idx_prompts_title
                        ON prompts(title COLLATE NOCASE);
                    CREATE INDEX idx_prompts_rating
                        ON prompts(rating);
                    CREATE INDEX idx_prompts_created
                        ON prompts(created_at);

                    CREATE TABLE tags (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL COLLATE NOCASE UNIQUE
                    );

                    CREATE TABLE prompt_tags (
                        prompt_id INTEGER NOT NULL
                            REFERENCES prompts(id) ON DELETE CASCADE,
                        tag_id INTEGER NOT NULL
                            REFERENCES tags(id) ON DELETE CASCADE,
                        PRIMARY KEY (prompt_id, tag_id)
                    );

                    CREATE INDEX idx_prompt_tags_tag
                        ON prompt_tags(tag_id, prompt_id);
                    """
                )
                self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def add(self, prompt: Prompt) -> Prompt:
        if prompt.id is not None:
            raise ValueError("A new prompt must not already have an ID.")
        existing = self.find_exact(prompt.positive_prompt)
        if existing is not None:
            raise DuplicatePromptError(existing)

        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO prompts(
                        title, positive_prompt, prompt_key, negative_prompt,
                        notes, rating, source_image, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._prompt_values(prompt),
                )
                prompt_id = int(cursor.lastrowid)
                self._replace_tags(prompt_id, prompt.tags)
        except sqlite3.IntegrityError as error:
            existing = self.find_exact(prompt.positive_prompt)
            if existing is not None:
                raise DuplicatePromptError(existing) from error
            raise
        return replace(prompt, id=prompt_id)

    def update(self, prompt: Prompt) -> Prompt:
        if prompt.id is None:
            raise ValueError("An updated prompt must have an ID.")
        if self.get(prompt.id) is None:
            raise PromptNotFoundError(prompt.id)

        duplicate = self._find_exact_excluding(
            prompt.positive_prompt,
            prompt.id,
        )
        if duplicate is not None:
            raise DuplicatePromptError(duplicate)

        try:
            with self._connection:
                self._connection.execute(
                    """
                    UPDATE prompts SET
                        title=?, positive_prompt=?, prompt_key=?,
                        negative_prompt=?, notes=?, rating=?, source_image=?,
                        created_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (*self._prompt_values(prompt), prompt.id),
                )
                self._replace_tags(prompt.id, prompt.tags)
        except sqlite3.IntegrityError as error:
            duplicate = self._find_exact_excluding(
                prompt.positive_prompt,
                prompt.id,
            )
            if duplicate is not None:
                raise DuplicatePromptError(duplicate) from error
            raise
        saved = self.get(prompt.id)
        if saved is None:
            raise PromptNotFoundError(prompt.id)
        return saved

    def delete(self, prompt_id: int) -> None:
        self._validate_prompt_id(prompt_id)
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM prompts WHERE id=?",
                (prompt_id,),
            )
            if cursor.rowcount == 0:
                raise PromptNotFoundError(prompt_id)
            self._delete_unused_tags()

    def get(self, prompt_id: int) -> Prompt | None:
        self._validate_prompt_id(prompt_id)
        row = self._connection.execute(
            "SELECT * FROM prompts WHERE id=?",
            (prompt_id,),
        ).fetchone()
        return self._row_to_prompt(row) if row is not None else None

    def find_exact(self, positive_prompt: str) -> Prompt | None:
        key = normalize_prompt(positive_prompt)
        if not key:
            return None
        row = self._connection.execute(
            "SELECT * FROM prompts WHERE prompt_key=?",
            (key,),
        ).fetchone()
        return self._row_to_prompt(row) if row is not None else None

    def _find_exact_excluding(
        self,
        positive_prompt: str,
        prompt_id: int,
    ) -> Prompt | None:
        row = self._connection.execute(
            "SELECT * FROM prompts WHERE prompt_key=? AND id<>? LIMIT 1",
            (normalize_prompt(positive_prompt), prompt_id),
        ).fetchone()
        return self._row_to_prompt(row) if row is not None else None

    def search(self, query: PromptSearch | None = None) -> list[Prompt]:
        query = query or PromptSearch()
        joins: list[str] = []
        clauses: list[str] = []
        parameters: list[object] = []

        terms = [term.casefold() for term in query.text.split() if term.strip()]
        for term in terms:
            like = f"%{term}%"
            clauses.append(
                """
                (
                    lower(p.title) LIKE ?
                    OR lower(p.positive_prompt) LIKE ?
                    OR lower(p.negative_prompt) LIKE ?
                    OR lower(p.notes) LIKE ?
                    OR EXISTS(
                        SELECT 1 FROM prompt_tags pts
                        JOIN tags ts ON ts.id=pts.tag_id
                        WHERE pts.prompt_id=p.id
                          AND lower(ts.name) LIKE ?
                    )
                )
                """
            )
            parameters.extend([like] * 5)

        if query.minimum_rating:
            clauses.append("p.rating>=?")
            parameters.append(query.minimum_rating)
        if query.unrated_only:
            clauses.append("p.rating=0")
        if query.favourites_only:
            clauses.append("p.rating>=4")
        if query.untagged_only:
            clauses.append(
                "NOT EXISTS(SELECT 1 FROM prompt_tags pu WHERE pu.prompt_id=p.id)"
            )

        for index, tag in enumerate(query.tags):
            alias_pt = f"pt{index}"
            alias_t = f"t{index}"
            joins.append(
                f"JOIN prompt_tags {alias_pt} ON {alias_pt}.prompt_id=p.id "
                f"JOIN tags {alias_t} ON {alias_t}.id={alias_pt}.tag_id"
            )
            if query.match_all_tags:
                clauses.append(f"{alias_t}.name=? COLLATE NOCASE")
                parameters.append(tag)

        if query.tags and not query.match_all_tags:
            placeholders = ",".join("?" for _ in query.tags)
            clauses.append(
                "EXISTS(SELECT 1 FROM prompt_tags pta "
                "JOIN tags ta ON ta.id=pta.tag_id "
                f"WHERE pta.prompt_id=p.id AND ta.name IN ({placeholders}) "
                "COLLATE NOCASE)"
            )
            parameters.extend(query.tags)

        order_by = {
            PromptSort.TITLE: "p.title COLLATE NOCASE ASC",
            PromptSort.RATING_DESC: (
                "p.rating DESC, p.title COLLATE NOCASE ASC"
            ),
            PromptSort.CREATED_DESC: (
                "p.created_at DESC, p.title COLLATE NOCASE ASC"
            ),
            PromptSort.UPDATED_DESC: (
                "p.updated_at DESC, p.title COLLATE NOCASE ASC"
            ),
        }[query.sort]

        sql = "SELECT DISTINCT p.* FROM prompts p"
        if joins:
            sql += " " + " ".join(joins)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order_by}"

        rows = self._connection.execute(sql, parameters).fetchall()
        return [self._row_to_prompt(row) for row in rows]

    def all_tags(self) -> list[TagSummary]:
        rows = self._connection.execute(
            """
            SELECT t.name, COUNT(pt.prompt_id) AS prompt_count
            FROM tags t
            LEFT JOIN prompt_tags pt ON pt.tag_id=t.id
            GROUP BY t.id
            ORDER BY t.name COLLATE NOCASE ASC
            """
        ).fetchall()
        return [
            TagSummary(
                name=str(row["name"]),
                prompt_count=int(row["prompt_count"]),
            )
            for row in rows
        ]

    def statistics(self) -> PromptLibraryStatistics:
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS prompt_count,
                SUM(CASE WHEN rating>0 THEN 1 ELSE 0 END) AS rated_count,
                SUM(CASE WHEN rating>=4 THEN 1 ELSE 0 END) AS favourite_count,
                SUM(CASE WHEN NOT EXISTS(
                    SELECT 1 FROM prompt_tags ps WHERE ps.prompt_id=prompts.id
                ) THEN 1 ELSE 0 END) AS untagged_count
            FROM prompts
            """
        ).fetchone()
        tag_count = int(
            self._connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        )
        return PromptLibraryStatistics(
            prompt_count=int(row["prompt_count"] or 0),
            rated_count=int(row["rated_count"] or 0),
            favourite_count=int(row["favourite_count"] or 0),
            untagged_count=int(row["untagged_count"] or 0),
            tag_count=tag_count,
        )

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _validate_prompt_id(prompt_id: int) -> None:
        if not isinstance(prompt_id, int) or isinstance(prompt_id, bool):
            raise TypeError("prompt_id must be an integer")
        if prompt_id < 1:
            raise ValueError("prompt_id must be positive")

    @staticmethod
    def _prompt_values(prompt: Prompt) -> tuple[object, ...]:
        return (
            prompt.title,
            prompt.positive_prompt,
            prompt.prompt_key,
            prompt.negative_prompt,
            prompt.notes,
            prompt.rating,
            str(prompt.source_image) if prompt.source_image is not None else None,
            prompt.created_at.isoformat(),
            prompt.updated_at.isoformat(),
        )

    def _replace_tags(self, prompt_id: int, tags: tuple[str, ...]) -> None:
        self._connection.execute(
            "DELETE FROM prompt_tags WHERE prompt_id=?",
            (prompt_id,),
        )
        for tag in tags:
            self._connection.execute(
                "INSERT OR IGNORE INTO tags(name) VALUES (?)",
                (tag,),
            )
            tag_id = int(
                self._connection.execute(
                    "SELECT id FROM tags WHERE name=? COLLATE NOCASE",
                    (tag,),
                ).fetchone()[0]
            )
            self._connection.execute(
                "INSERT INTO prompt_tags(prompt_id, tag_id) VALUES (?, ?)",
                (prompt_id, tag_id),
            )
        self._delete_unused_tags()

    def _delete_unused_tags(self) -> None:
        self._connection.execute(
            "DELETE FROM tags WHERE id NOT IN "
            "(SELECT DISTINCT tag_id FROM prompt_tags)"
        )

    def _row_to_prompt(self, row: sqlite3.Row) -> Prompt:
        tags = self._connection.execute(
            """
            SELECT t.name FROM tags t
            JOIN prompt_tags pt ON pt.tag_id=t.id
            WHERE pt.prompt_id=?
            ORDER BY t.name COLLATE NOCASE
            """,
            (int(row["id"]),),
        ).fetchall()
        source = row["source_image"]
        return Prompt(
            id=int(row["id"]),
            title=str(row["title"]),
            positive_prompt=str(row["positive_prompt"]),
            negative_prompt=str(row["negative_prompt"]),
            notes=str(row["notes"]),
            rating=int(row["rating"]),
            tags=tuple(str(tag["name"]) for tag in tags),
            source_image=Path(str(source)) if source else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
