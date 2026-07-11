from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from metaview.prompt_library import (
    DuplicatePromptError,
    Prompt,
    PromptNotFoundError,
    PromptSearch,
    PromptSort,
    SQLitePromptRepository,
)


def make_prompt(
    title: str,
    positive: str,
    *,
    rating: int = 0,
    tags: tuple[str, ...] = (),
    created_offset: int = 0,
) -> Prompt:
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
        seconds=created_offset
    )
    return Prompt(
        title=title,
        positive_prompt=positive,
        negative_prompt=f"negative {title}",
        notes=f"notes {title}",
        rating=rating,
        tags=tags,
        source_image=Path(f"/images/{title}.png"),
        created_at=created,
        updated_at=created,
    )


@pytest.fixture
def repository(tmp_path: Path):
    repo = SQLitePromptRepository(tmp_path / "library.sqlite3")
    yield repo
    repo.close()


def test_add_and_get_round_trip(repository: SQLitePromptRepository) -> None:
    original = make_prompt(
        "Portrait",
        "portrait  of\na woman",
        rating=5,
        tags=("Portrait", "Krea2"),
    )

    saved = repository.add(original)

    assert saved.id == 1
    assert repository.get(saved.id) == saved
    assert repository.find_exact(" portrait of a woman ") == saved


def test_repository_persists_after_reopen(tmp_path: Path) -> None:
    database = tmp_path / "library.sqlite3"
    first = SQLitePromptRepository(database)
    saved = first.add(make_prompt("Landscape", "mountain lake"))
    first.close()

    second = SQLitePromptRepository(database)
    try:
        assert second.get(saved.id) == saved
    finally:
        second.close()


def test_duplicate_exact_prompt_is_rejected(
    repository: SQLitePromptRepository,
) -> None:
    existing = repository.add(make_prompt("First", "same prompt"))

    with pytest.raises(DuplicatePromptError) as error:
        repository.add(make_prompt("Second", " same   prompt "))

    assert error.value.existing == existing


def test_case_and_punctuation_remain_significant(
    repository: SQLitePromptRepository,
) -> None:
    lower = repository.add(make_prompt("Lower", "portrait"))
    upper = repository.add(make_prompt("Upper", "Portrait"))
    punctuated = repository.add(make_prompt("Punctuated", "portrait!"))

    assert repository.find_exact("portrait") == lower
    assert repository.find_exact("Portrait") == upper
    assert repository.find_exact("portrait!") == punctuated


def test_update_replaces_values_and_tags(
    repository: SQLitePromptRepository,
) -> None:
    saved = repository.add(
        make_prompt("Old", "old prompt", tags=("old", "shared"))
    )
    updated = saved.with_updates(
        title="New",
        positive_prompt="new prompt",
        rating=4,
        tags=("new", "shared"),
    )

    result = repository.update(updated)

    assert result == updated
    assert repository.find_exact("old prompt") is None
    assert repository.find_exact("new prompt") == updated
    assert [(tag.name, tag.prompt_count) for tag in repository.all_tags()] == [
        ("new", 1),
        ("shared", 1),
    ]


def test_update_rejects_duplicate_prompt(
    repository: SQLitePromptRepository,
) -> None:
    first = repository.add(make_prompt("First", "first"))
    second = repository.add(make_prompt("Second", "second"))

    with pytest.raises(DuplicatePromptError) as error:
        repository.update(second.with_updates(positive_prompt=" first "))

    assert error.value.existing == first


def test_update_and_delete_require_existing_prompt(
    repository: SQLitePromptRepository,
) -> None:
    missing = make_prompt("Missing", "missing").with_updates(id=999)

    with pytest.raises(PromptNotFoundError):
        repository.update(missing)
    with pytest.raises(PromptNotFoundError):
        repository.delete(999)


def test_delete_removes_unused_tags(
    repository: SQLitePromptRepository,
) -> None:
    first = repository.add(make_prompt("First", "first", tags=("one", "shared")))
    repository.add(make_prompt("Second", "second", tags=("shared",)))

    repository.delete(first.id)

    assert repository.get(first.id) is None
    assert [(tag.name, tag.prompt_count) for tag in repository.all_tags()] == [
        ("shared", 1)
    ]


def test_searches_text_across_fields_and_tags(
    repository: SQLitePromptRepository,
) -> None:
    portrait = repository.add(
        make_prompt("Natural portrait", "woman by window", tags=("Krea2",))
    )
    repository.add(make_prompt("Landscape", "mountain lake", tags=("Flux",)))

    assert repository.search(PromptSearch(text="window")) == [portrait]
    assert repository.search(PromptSearch(text="natural")) == [portrait]
    assert repository.search(PromptSearch(text="krea")) == [portrait]


def test_search_filters_tags_and_ratings(
    repository: SQLitePromptRepository,
) -> None:
    both = repository.add(
        make_prompt(
            "Both",
            "both",
            rating=5,
            tags=("portrait", "studio"),
        )
    )
    portrait = repository.add(
        make_prompt("Portrait", "portrait", rating=3, tags=("portrait",))
    )
    repository.add(make_prompt("None", "none", rating=0))

    assert repository.search(PromptSearch(tags=("portrait", "studio"))) == [both]
    assert repository.search(
        PromptSearch(tags=("portrait", "studio"), match_all_tags=False)
    ) == [both, portrait]
    assert repository.search(PromptSearch(minimum_rating=4)) == [both]
    assert repository.search(PromptSearch(favourites_only=True)) == [both]
    assert [p.title for p in repository.search(PromptSearch(unrated_only=True))] == [
        "None"
    ]
    assert [p.title for p in repository.search(PromptSearch(untagged_only=True))] == [
        "None"
    ]


def test_search_sort_orders(repository: SQLitePromptRepository) -> None:
    repository.add(make_prompt("Zulu", "z", rating=1, created_offset=1))
    repository.add(make_prompt("Alpha", "a", rating=5, created_offset=2))

    assert [p.title for p in repository.search(PromptSearch(sort=PromptSort.TITLE))] == [
        "Alpha",
        "Zulu",
    ]
    assert [
        p.title for p in repository.search(PromptSearch(sort=PromptSort.RATING_DESC))
    ] == ["Alpha", "Zulu"]
    assert [
        p.title for p in repository.search(PromptSearch(sort=PromptSort.CREATED_DESC))
    ] == ["Alpha", "Zulu"]


def test_all_tags_are_case_insensitive(repository: SQLitePromptRepository) -> None:
    repository.add(make_prompt("First", "first", tags=("Portrait",)))
    repository.add(make_prompt("Second", "second", tags=("portrait",)))

    assert repository.all_tags()[0].prompt_count == 2
    assert repository.all_tags()[0].name == "Portrait"


def test_statistics(repository: SQLitePromptRepository) -> None:
    repository.add(make_prompt("One", "one", rating=5, tags=("portrait",)))
    repository.add(make_prompt("Two", "two", rating=2))
    repository.add(make_prompt("Three", "three"))

    statistics = repository.statistics()

    assert statistics.prompt_count == 3
    assert statistics.rated_count == 2
    assert statistics.favourite_count == 1
    assert statistics.untagged_count == 2
    assert statistics.tag_count == 1


def test_database_schema_version(repository: SQLitePromptRepository) -> None:
    version = repository._connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
