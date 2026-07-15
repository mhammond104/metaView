from pathlib import Path
from datetime import datetime, timezone

import pytest

from metaview.smart_collections import (
    SmartCollection,
    SmartCollectionRepository,
    SmartCollectionRule,
    evaluate_smart_collection,
    evaluate_indexed_smart_collection,
    matches_rule,
)


def test_smart_collection_repository_lifecycle(tmp_path: Path) -> None:
    repository = SmartCollectionRepository(tmp_path / "collections.sqlite3")
    rules = (
        SmartCollectionRule("rating", "gte", "4"),
        SmartCollectionRule("model", "contains", "krea"),
    )
    created = repository.create("Best Krea", rules)
    assert repository.get(created.id) == created
    assert repository.list() == [created]

    updated = repository.update(
        created.id,
        "Best portraits",
        (SmartCollectionRule("prompt", "contains", "portrait"),),
    )
    assert updated.name == "Best portraits"
    assert updated.rules[0].field == "prompt"
    assert repository.delete(created.id)
    assert repository.list() == []
    repository.close()


def test_smart_collection_requires_name_rules_and_unique_name(tmp_path: Path) -> None:
    repository = SmartCollectionRepository(tmp_path / "collections.sqlite3")
    rule = SmartCollectionRule("filename", "contains", "test")
    repository.create("Tests", (rule,))
    with pytest.raises(ValueError):
        repository.create("tests", (rule,))
    with pytest.raises(ValueError):
        repository.create("Empty", ())
    repository.close()


def test_rule_matching() -> None:
    path = Path("/images/Portrait_01.png")
    summary = {
        "model": "Krea2 FP8",
        "sampler": "euler",
        "scheduler": "beta",
        "positive": "studio portrait with detailed hair",
    }
    assert matches_rule(path, SmartCollectionRule("rating", "gte", "4"), summary, 5)
    assert matches_rule(path, SmartCollectionRule("model", "contains", "krea"), summary, 0)
    assert matches_rule(path, SmartCollectionRule("filename", "contains", "portrait"), summary, 0)
    assert not matches_rule(path, SmartCollectionRule("prompt", "not_contains", "hair"), summary, 0)


def test_evaluation_uses_all_rules(monkeypatch, tmp_path: Path) -> None:
    matching = tmp_path / "portrait.png"
    rejected = tmp_path / "landscape.png"
    matching.write_bytes(b"x")
    rejected.write_bytes(b"x")

    monkeypatch.setattr(
        "metaview.smart_collections.read_image_metadata",
        lambda path: {"fake": path.name},
    )
    monkeypatch.setattr(
        "metaview.smart_collections.extract_summary",
        lambda metadata: {
            "model": "Krea2" if metadata["fake"].startswith("portrait") else "Other",
            "sampler": "euler",
            "scheduler": "beta",
            "positive": "portrait",
        },
    )
    repository = SmartCollectionRepository(tmp_path / "collections.sqlite3")
    collection = repository.create(
        "Rated Krea",
        (
            SmartCollectionRule("model", "is", "Krea2"),
            SmartCollectionRule("rating", "gte", "4"),
        ),
    )
    results = evaluate_smart_collection(
        collection,
        [matching, rejected],
        lambda path: 5 if path == matching else 5,
    )
    assert results == [matching.resolve()]
    repository.close()


def test_indexed_evaluation_uses_cached_metadata(tmp_path: Path) -> None:
    from types import SimpleNamespace
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    collection = SmartCollection(
        id=1,
        name="Karras",
        rules=(SmartCollectionRule("scheduler", "is", "karras"),),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    images = [
        SimpleNamespace(path=first, model="Krea2", sampler="euler", scheduler="karras", positive_prompt="portrait"),
        SimpleNamespace(path=second, model="Krea2", sampler="euler", scheduler="beta", positive_prompt="portrait"),
    ]
    assert evaluate_indexed_smart_collection(collection, images, lambda _path: 0) == [first.resolve()]
