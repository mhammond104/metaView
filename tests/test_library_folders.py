from pathlib import Path

from metaview.library_folders import LibraryFolderRepository


def test_add_list_remove_and_membership(tmp_path: Path) -> None:
    root = tmp_path / "library"
    child = root / "nested"
    child.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    repository = LibraryFolderRepository(":memory:")
    saved = repository.add(root)

    assert repository.contains_folder(root)
    assert repository.contains_path(root / "image.png")
    assert repository.contains_path(child / "image.png")
    assert not repository.contains_path(outside / "image.png")
    assert repository.paths() == (root.resolve(),)
    assert repository.list()[0].id == saved.id

    assert repository.remove(saved.id)
    assert not repository.contains_folder(root)
    repository.close()


def test_add_is_idempotent(tmp_path: Path) -> None:
    folder = tmp_path / "library"
    folder.mkdir()
    repository = LibraryFolderRepository(":memory:")
    first = repository.add(folder)
    second = repository.add(folder)
    assert first.id == second.id
    assert len(repository.list()) == 1
    repository.close()
