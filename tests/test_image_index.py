from __future__ import annotations

from pathlib import Path

from metaview.prompt_library import (
    ImageIndexService,
    IndexedImage,
    Prompt,
    SQLiteImageIndexRepository,
)


def touch(path: Path, content: bytes = b"image") -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def test_upsert_get_and_persist(tmp_path: Path) -> None:
    database = tmp_path / "index.sqlite3"
    image_path = tmp_path / "images" / "one.png"
    modified_ns, file_size = touch(image_path)

    with SQLiteImageIndexRepository(database) as repository:
        image = IndexedImage(
            path=image_path.resolve(),
            positive_prompt="portrait  in\n daylight",
            modified_ns=modified_ns,
            file_size=file_size,
        )
        saved = repository.upsert(image)
        assert saved == image
        assert repository.get(image_path) == image

    with SQLiteImageIndexRepository(database) as repository:
        restored = repository.get(image_path)
        assert restored is not None
        assert restored.positive_prompt == "portrait  in\n daylight"
        assert restored.prompt_key == "portrait in daylight"


def test_upsert_replaces_metadata_for_same_path(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    path = tmp_path / "one.png"
    touch(path)
    repository.upsert(IndexedImage(path, "first", 1, 10))
    repository.upsert(IndexedImage(path, "second", 2, 20))

    saved = repository.get(path)
    assert saved is not None
    assert saved.positive_prompt == "second"
    assert saved.modified_ns == 2
    assert saved.file_size == 20
    assert repository.statistics().image_count == 1
    repository.close()


def test_matching_counts_and_directories(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    service = ImageIndexService(repository)
    first = tmp_path / "a" / "one.png"
    second = tmp_path / "b" / "two.png"
    third = tmp_path / "b" / "three.png"
    for path in (first, second, third):
        touch(path)

    service.index_metadata(first, "same  prompt", 1, 10)
    service.index_metadata(second, "same\nprompt", 2, 20)
    service.index_metadata(third, "different", 3, 30)

    prompt = Prompt(title="Saved", positive_prompt="same prompt")
    assert service.matching_paths(prompt) == [first.resolve(), second.resolve()]
    assert service.count_matching(prompt) == 2
    assert [(item.directory, item.image_count) for item in service.directory_counts(prompt)] == [
        (first.parent.resolve(), 1),
        (second.parent.resolve(), 1),
    ]
    service.close()


def test_exact_match_preserves_case_and_punctuation(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    paths = [tmp_path / f"{index}.png" for index in range(3)]
    for path in paths:
        touch(path)
    repository.upsert(IndexedImage(paths[0], "Portrait", 1, 1))
    repository.upsert(IndexedImage(paths[1], "portrait", 1, 1))
    repository.upsert(IndexedImage(paths[2], "portrait!", 1, 1))

    assert repository.count_matching("Portrait") == 1
    assert repository.count_matching("portrait") == 1
    assert repository.count_matching("portrait!") == 1
    repository.close()


def test_needs_refresh(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    path = tmp_path / "one.png"
    touch(path)
    assert repository.needs_refresh(path, 10, 20)
    repository.upsert(IndexedImage(path, "prompt", 10, 20))
    assert not repository.needs_refresh(path, 10, 20)
    assert repository.needs_refresh(path, 11, 20)
    assert repository.needs_refresh(path, 10, 21)
    repository.close()


def test_prune_directory_only_removes_stale_paths_in_that_directory(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    directory = tmp_path / "first"
    keep = directory / "keep.png"
    stale = directory / "stale.png"
    elsewhere = tmp_path / "second" / "elsewhere.png"
    for path in (keep, stale, elsewhere):
        touch(path)
        repository.upsert(IndexedImage(path, "prompt", 1, 1))

    removed = repository.prune_directory(directory, [keep])
    assert removed == 1
    assert repository.get(keep) is not None
    assert repository.get(stale) is None
    assert repository.get(elsewhere) is not None
    repository.close()


def test_remove_missing_and_remove(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    existing = tmp_path / "existing.png"
    missing = tmp_path / "missing.png"
    touch(existing)
    touch(missing)
    repository.upsert(IndexedImage(existing, "prompt", 1, 1))
    repository.upsert(IndexedImage(missing, "prompt", 1, 1))
    missing.unlink()

    assert repository.remove_missing() == 1
    assert repository.get(missing) is None
    assert repository.remove(existing)
    assert not repository.remove(existing)
    repository.close()


def test_statistics(tmp_path: Path) -> None:
    repository = SQLiteImageIndexRepository(":memory:")
    paths = [
        tmp_path / "a" / "one.png",
        tmp_path / "a" / "two.png",
        tmp_path / "b" / "three.png",
    ]
    for path in paths:
        touch(path)
    repository.upsert(IndexedImage(paths[0], "prompt", 1, 1))
    repository.upsert(IndexedImage(paths[1], "", 1, 1))
    repository.upsert(IndexedImage(paths[2], "other", 1, 1))

    stats = repository.statistics()
    assert stats.image_count == 3
    assert stats.prompted_image_count == 2
    assert stats.directory_count == 2
    repository.close()


def test_schema_version_is_set(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "index.sqlite3"
    repository = SQLiteImageIndexRepository(database)
    repository.close()
    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    connection.close()
