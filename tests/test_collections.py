from pathlib import Path

import pytest

from metaview.collections import CollectionRepository


def test_collection_lifecycle_and_membership(tmp_path: Path) -> None:
    repository = CollectionRepository(tmp_path / "collections.sqlite3")
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    image_a.write_bytes(b"a")
    image_b.write_bytes(b"b")

    collection = repository.create("Portraits")
    assert repository.count(collection.id) == 0
    assert repository.add_images(collection.id, [image_a, image_b]) == 2
    assert repository.add_images(collection.id, [image_a]) == 0
    assert repository.count(collection.id) == 2
    assert repository.images(collection.id) == [image_a.resolve(), image_b.resolve()]

    renamed = repository.rename(collection.id, "Portfolio")
    assert renamed.name == "Portfolio"
    assert [item.name for item in repository.list()] == ["Portfolio"]

    assert repository.remove_images(collection.id, [image_a]) == 1
    assert repository.images(collection.id) == [image_b.resolve()]
    assert repository.delete(collection.id)
    assert repository.list() == []
    repository.close()


def test_collection_names_are_unique_case_insensitively(tmp_path: Path) -> None:
    repository = CollectionRepository(tmp_path / "collections.sqlite3")
    repository.create("Portraits")
    with pytest.raises(ValueError):
        repository.create("portraits")
    repository.close()


def test_missing_files_are_hidden_but_references_remain(tmp_path: Path) -> None:
    repository = CollectionRepository(tmp_path / "collections.sqlite3")
    collection = repository.create("Test")
    missing = tmp_path / "missing.png"
    repository.add_images(collection.id, [missing])
    assert repository.images(collection.id) == []
    assert repository.images(collection.id, existing_only=False) == [missing.resolve()]
    assert repository.count(collection.id) == 1
    repository.close()
