from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from metaview.prompt_library import IndexedImage, Prompt, normalize_prompt


def test_normalize_prompt_collapses_formatting_but_preserves_case_and_punctuation() -> None:
    assert normalize_prompt("  A portrait,\n\tof a woman  ") == "A portrait, of a woman"
    assert normalize_prompt("A portrait") != normalize_prompt("a portrait")
    assert normalize_prompt("portrait") != normalize_prompt("portrait,")


def test_normalize_prompt_rejects_non_strings() -> None:
    with pytest.raises(TypeError, match="prompt must be a string"):
        normalize_prompt(None)  # type: ignore[arg-type]


def test_prompt_normalises_title_tags_and_match_key() -> None:
    prompt = Prompt(
        title="  Natural light portrait  ",
        positive_prompt="portrait  of\na woman",
        rating=4,
        tags=(" Portrait ", "realism", "portrait", "REALISM", ""),
    )

    assert prompt.title == "Natural light portrait"
    assert prompt.prompt_key == "portrait of a woman"
    assert prompt.tags == ("Portrait", "realism")
    assert prompt.is_rated is True
    assert prompt.is_favourite is True


def test_prompt_validates_required_fields_and_rating() -> None:
    with pytest.raises(ValueError, match="title cannot be empty"):
        Prompt(title=" ", positive_prompt="test")
    with pytest.raises(ValueError, match="positive_prompt cannot be empty"):
        Prompt(title="Test", positive_prompt=" \n ")
    with pytest.raises(ValueError, match="between 0 and 5"):
        Prompt(title="Test", positive_prompt="test", rating=6)
    with pytest.raises(TypeError, match="rating must be an integer"):
        Prompt(title="Test", positive_prompt="test", rating=True)  # type: ignore[arg-type]


def test_prompt_timestamps_must_be_aware_and_ordered() -> None:
    aware = datetime(2026, 7, 11, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        Prompt(
            title="Test",
            positive_prompt="test",
            created_at=datetime(2026, 7, 11),
            updated_at=aware,
        )
    with pytest.raises(ValueError, match="cannot be earlier"):
        Prompt(
            title="Test",
            positive_prompt="test",
            created_at=aware,
            updated_at=aware - timedelta(seconds=1),
        )


def test_prompt_is_immutable_and_with_updates_returns_new_instance() -> None:
    created = datetime(2026, 7, 11, tzinfo=UTC)
    prompt = Prompt(
        id=1,
        title="Original",
        positive_prompt="test",
        created_at=created,
        updated_at=created,
    )

    with pytest.raises(FrozenInstanceError):
        prompt.title = "Changed"  # type: ignore[misc]

    updated = prompt.with_updates(title="Changed", rating=5)
    assert prompt.title == "Original"
    assert updated.title == "Changed"
    assert updated.rating == 5
    assert updated.updated_at >= prompt.updated_at
    assert updated.created_at == prompt.created_at


def test_indexed_image_derives_directory_and_exact_prompt_key() -> None:
    image = IndexedImage(
        path=Path("/images/portraits/output.png"),
        positive_prompt="portrait\n of  a woman",
        modified_ns=123,
        file_size=456,
    )

    assert image.directory == Path("/images/portraits")
    assert image.prompt_key == "portrait of a woman"
    assert image.has_prompt is True
    assert image.matches(" portrait of a woman ") is True
    assert image.matches("Portrait of a woman") is False


def test_indexed_image_matches_prompt_object() -> None:
    prompt = Prompt(title="Portrait", positive_prompt="portrait of a woman")
    image = IndexedImage(
        path=Path("image.png"),
        positive_prompt="portrait  of a woman",
        modified_ns=0,
        file_size=0,
    )
    assert image.matches(prompt) is True


def test_indexed_image_validates_file_metadata() -> None:
    with pytest.raises(ValueError, match="modified_ns cannot be negative"):
        IndexedImage(
            path=Path("image.png"),
            positive_prompt="test",
            modified_ns=-1,
            file_size=0,
        )
    with pytest.raises(ValueError, match="file_size cannot be negative"):
        IndexedImage(
            path=Path("image.png"),
            positive_prompt="test",
            modified_ns=0,
            file_size=-1,
        )
