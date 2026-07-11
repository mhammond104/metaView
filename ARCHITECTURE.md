# metaView architecture

The v0.2 development branch begins with a behaviour-preserving refactor of the
v0.1.0 application. The original 3,543-line `src/metaview/main.py` has been
split into modules with explicit responsibilities.

## Modules

- `metaview.constants` — application constants, Qt data roles and asset paths.
- `metaview.metadata` — image metadata reading, ComfyUI summary extraction,
  LoRA extraction and display formatting.
- `metaview.workers` — background thumbnail and metadata worker tasks.
- `metaview.widgets` — reusable browser and metadata-panel widgets.
- `metaview.dialogs` — comparison, experiment, similarity, rating and the
  existing v0.1.0 prompt-library dialogs/databases.
- `metaview.main_window` — top-level browser orchestration and application
  state.
- `metaview.theme` — dark theme and splash rendering.
- `metaview.application` — QApplication construction and startup.
- `metaview.main` — backward-compatible entry point used by package scripts.

## Refactor policy

This commit is intended to preserve v0.1.0 behaviour. New Prompt Library
functionality should be implemented in subsequent commits, after the refactor
has been tested on all target platforms.

The next structural step should be to move the existing prompt-library classes
from `dialogs.py` into a dedicated `metaview.prompt_library` package as they
are replaced by the v0.2 implementation.

## Prompt Library domain package

`src/metaview/prompt_library/` contains the behaviour-independent domain layer
for v0.2. `Prompt` and `IndexedImage` are immutable, typed dataclasses, while
`normalize_prompt()` defines exact-prompt matching consistently for future
storage, indexing and UI modules. This package deliberately has no Qt or SQLite
dependency.

## Prompt Library backend

The Prompt Library persistence layer is isolated under
`metaview.prompt_library`:

- `models.py` defines immutable domain objects.
- `normalization.py` defines exact-prompt key generation.
- `repository.py` defines the persistence contract, search objects, summaries,
  statistics and repository-specific exceptions.
- `sqlite.py` implements that contract with a versioned SQLite schema.

Application widgets and dialogs should depend on `PromptRepository`, not on
SQLite or SQL statements. A single repository instance will later be created by
the application and passed to Prompt Library UI components.
