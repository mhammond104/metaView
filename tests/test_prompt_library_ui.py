from pathlib import Path

from metaview.prompt_library import (
    ImageIndexService,
    Prompt,
    PromptLibraryController,
    SQLiteImageIndexRepository,
    SQLitePromptRepository,
    import_legacy_prompt_library,
)


def test_controller_emits_for_add_update_and_delete(tmp_path: Path) -> None:
    prompt_repository = SQLitePromptRepository(tmp_path / "prompts.sqlite3")
    image_index = ImageIndexService(
        SQLiteImageIndexRepository(tmp_path / "images.sqlite3")
    )
    controller = PromptLibraryController(prompt_repository, image_index)
    changes: list[str] = []
    controller.changed.connect(lambda: changes.append("changed"))

    saved = controller.add(Prompt(title="Portrait", positive_prompt="a portrait"))
    controller.update(saved.with_updates(rating=5))
    assert saved.id is not None
    controller.delete(saved.id)

    assert changes == ["changed", "changed", "changed"]
    prompt_repository.close()
    image_index.close()


def test_legacy_import_maps_supported_fields(tmp_path: Path) -> None:
    import sqlite3

    legacy = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(legacy)
    connection.execute(
        """
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            tags TEXT,
            positive_prompt TEXT,
            negative_prompt TEXT,
            source_image TEXT,
            model TEXT,
            loras_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO prompts VALUES (
            1, 'Natural portrait', 'Useful notes', 'portrait, light',
            'a natural portrait', 'blurry', '/tmp/example.png', '', '[]', '', ''
        )
        """
    )
    connection.commit()
    connection.close()

    repository = SQLitePromptRepository(tmp_path / "new.sqlite3")
    assert import_legacy_prompt_library(legacy, repository) == 1
    imported = repository.find_exact("a natural portrait")
    assert imported is not None
    assert imported.title == "Natural portrait"
    assert imported.notes == "Useful notes"
    assert imported.tags == ("light", "portrait")
    assert imported.source_image == Path("/tmp/example.png")
    assert import_legacy_prompt_library(legacy, repository) == 0
    repository.close()
