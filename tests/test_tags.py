from pathlib import Path

import pytest

from metaview.tags import TagRepository


def test_tag_crud_and_assignments(tmp_path: Path) -> None:
    repository = TagRepository(tmp_path / "library.sqlite3")
    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.touch()
    second.touch()

    tag = repository.create("Portfolio")
    assert repository.assign(tag.id, [first, second]) == 2
    assert repository.assign(tag.id, [first]) == 0
    assert repository.count(tag.id) == 2
    assert repository.names_for_path(first) == ("Portfolio",)
    assert repository.paths(tag.id) == [first.resolve(), second.resolve()]

    renamed = repository.rename(tag.id, "Best")
    assert renamed.name == "Best"
    assert repository.names_for_path(first) == ("Best",)
    assert repository.unassign(tag.id, [second]) == 1
    assert repository.count(tag.id) == 1
    assert repository.delete(tag.id)
    assert repository.names_for_path(first) == ()
    repository.close()


def test_tag_names_are_unique_case_insensitively(tmp_path: Path) -> None:
    repository = TagRepository(tmp_path / "library.sqlite3")
    repository.create("Portrait")
    with pytest.raises(ValueError):
        repository.create("portrait")
    repository.close()
