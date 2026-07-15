from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable



def read_image_metadata(path: Path):
    from .metadata import read_image_metadata as _read_image_metadata
    return _read_image_metadata(path)


def extract_summary(metadata):
    from .metadata import extract_summary as _extract_summary
    return _extract_summary(metadata)


@dataclass(frozen=True, slots=True)
class SmartCollectionRule:
    field: str
    operator: str
    value: str

    def __post_init__(self) -> None:
        if self.field not in {"rating", "model", "sampler", "scheduler", "prompt", "filename", "tag"}:
            raise ValueError(f"Unsupported smart collection field: {self.field}")
        if self.operator not in {"is", "contains", "not_contains", "gte", "lte"}:
            raise ValueError(f"Unsupported smart collection operator: {self.operator}")
        if not self.value.strip():
            raise ValueError("Smart collection rule values cannot be empty")


@dataclass(frozen=True, slots=True)
class SmartCollection:
    id: int
    name: str
    rules: tuple[SmartCollectionRule, ...]
    created_at: datetime
    updated_at: datetime


class SmartCollectionRepository:
    """Persist simple AND-based smart collections in the collections database."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS smart_collections (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    rules_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _decode_rules(value: str) -> tuple[SmartCollectionRule, ...]:
        raw = json.loads(value)
        return tuple(SmartCollectionRule(**item) for item in raw)

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> SmartCollection:
        return SmartCollection(
            id=int(row["id"]),
            name=str(row["name"]),
            rules=cls._decode_rules(str(row["rules_json"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _encode_rules(rules: Iterable[SmartCollectionRule]) -> str:
        values = [
            {"field": rule.field, "operator": rule.operator, "value": rule.value.strip()}
            for rule in rules
        ]
        if not values:
            raise ValueError("A smart collection needs at least one rule")
        return json.dumps(values, separators=(",", ":"))

    def create(self, name: str, rules: Iterable[SmartCollectionRule]) -> SmartCollection:
        clean = name.strip()
        if not clean:
            raise ValueError("Smart collection name cannot be empty")
        encoded = self._encode_rules(rules)
        now = self._now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO smart_collections(name,rules_json,created_at,updated_at) VALUES(?,?,?,?)",
                    (clean, encoded, now.isoformat(), now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A smart collection named "{clean}" already exists') from exc
        return SmartCollection(int(cursor.lastrowid), clean, self._decode_rules(encoded), now, now)

    def update(self, collection_id: int, name: str, rules: Iterable[SmartCollectionRule]) -> SmartCollection:
        clean = name.strip()
        if not clean:
            raise ValueError("Smart collection name cannot be empty")
        encoded = self._encode_rules(rules)
        now = self._now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "UPDATE smart_collections SET name=?,rules_json=?,updated_at=? WHERE id=?",
                    (clean, encoded, now.isoformat(), collection_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A smart collection named "{clean}" already exists') from exc
        if cursor.rowcount == 0:
            raise LookupError(f"Smart collection {collection_id} was not found")
        result = self.get(collection_id)
        assert result is not None
        return result

    def delete(self, collection_id: int) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM smart_collections WHERE id=?", (collection_id,)
            )
        return cursor.rowcount > 0

    def get(self, collection_id: int) -> SmartCollection | None:
        row = self._connection.execute(
            "SELECT * FROM smart_collections WHERE id=?", (collection_id,)
        ).fetchone()
        return self._from_row(row) if row else None

    def list(self) -> list[SmartCollection]:
        rows = self._connection.execute(
            "SELECT * FROM smart_collections ORDER BY name COLLATE NOCASE,id"
        )
        return [self._from_row(row) for row in rows]

    def close(self) -> None:
        self._connection.close()


def matches_rule(
    path: Path,
    rule: SmartCollectionRule,
    summary: dict[str, str],
    rating: int,
    tags: tuple[str, ...] = (),
) -> bool:
    if rule.field == "rating":
        try:
            expected = int(rule.value)
        except ValueError:
            return False
        if rule.operator == "gte":
            return rating >= expected
        if rule.operator == "lte":
            return rating <= expected
        return rating == expected

    if rule.field == "tag":
        expected_folded = rule.value.strip().casefold()
        folded_tags = tuple(tag.casefold() for tag in tags)
        if rule.operator == "is":
            return expected_folded in folded_tags
        if rule.operator == "not_contains":
            return all(expected_folded not in tag for tag in folded_tags)
        return any(expected_folded in tag for tag in folded_tags)

    actual = {
        "filename": path.name,
        "model": summary.get("model", ""),
        "sampler": summary.get("sampler", ""),
        "scheduler": summary.get("scheduler", ""),
        "prompt": summary.get("positive", ""),
    }.get(rule.field, "")
    actual_folded = str(actual).casefold()
    expected_folded = rule.value.strip().casefold()
    if rule.operator == "is":
        return actual_folded == expected_folded
    if rule.operator == "not_contains":
        return expected_folded not in actual_folded
    return expected_folded in actual_folded


def evaluate_smart_collection(
    collection: SmartCollection,
    paths: Iterable[Path],
    rating_for_path: Callable[[Path], int],
) -> list[Path]:
    matches: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            summary = extract_summary(read_image_metadata(path))
        except Exception:
            summary = {}
        rating = rating_for_path(path)
        if all(matches_rule(path, rule, summary, rating) for rule in collection.rules):
            matches.append(path.resolve())
    return matches


def evaluate_indexed_smart_collection(
    collection: SmartCollection,
    images: Iterable[object],
    rating_for_path: Callable[[Path], int],
    tags_for_path: Callable[[Path], tuple[str, ...]] | None = None,
) -> list[Path]:
    """Evaluate a Smart Collection from cached index metadata only."""
    matches: list[Path] = []
    for image in images:
        path = getattr(image, "path", None)
        if not isinstance(path, Path) or not path.is_file():
            continue
        summary = {
            "model": str(getattr(image, "model", "")),
            "sampler": str(getattr(image, "sampler", "")),
            "scheduler": str(getattr(image, "scheduler", "")),
            "positive": str(getattr(image, "positive_prompt", "")),
        }
        rating = rating_for_path(path)
        tags = tags_for_path(path) if tags_for_path is not None else ()
        if all(matches_rule(path, rule, summary, rating, tags) for rule in collection.rules):
            matches.append(path.resolve())
    return matches
