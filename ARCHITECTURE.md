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

## Global image index

The Prompt Library image index is deliberately separate from prompt-entry
persistence:

- `prompt_library/image_index.py` defines the repository contract, aggregate
  value objects, and `ImageIndexService` used by the application.
- `prompt_library/sqlite_image_index.py` is the SQLite adapter.
- `MetadataWorker` emits the positive prompt together with modification time
  and file size.
- `MainWindow.model_loaded()` sends every completed metadata result to the
  index service before checking the thumbnail generation. This means a scan
  remains useful to the global index even if the user navigates away before it
  completes.
- Opening or refreshing a directory prunes index entries that no longer exist
  in that directory.

The index stores only metadata needed for exact prompt matching. It does not
own thumbnails, ratings, Prompt Library entries, or image metadata parsing.

## Prompt Library UI (v0.2 development)

The Prompt Library user interface lives in `metaview.prompt_library.ui` and
works only with `Prompt`, `PromptRepository`, and `ImageIndexService` objects.
It never executes SQL directly.

`PromptLibraryController` is a small observable application service. It emits
`changed` after add, update, or delete operations, allowing every open Prompt
Library view to refresh without parent-widget refresh chains.

The main thumbnail browser supports a temporary global prompt-results source.
Before entering it, `MainWindow` captures directory, searches, metadata filters,
rating filter, sort order, selection, current image, and scroll position. The
"Return to previous view" action restores that state.

## Metadata parsing and comparison services

Generation metadata processing is split into presentation-independent modules:

- `metaview.metadata_parsing` parses ComfyUI prompt metadata and extracts the
  standard generation summary and LoRA records. It has no Qt dependency.
- `metaview.metadata_normalization` defines canonical prompt, text, and LoRA
  comparison rules.
- `metaview.comparison` produces structured parameter and LoRA comparison
  objects, including image resolution differences. It has no Qt dependency.
- `metaview.metadata` remains the UI-facing metadata facade and retains image
  loading, JSON display, and thumbnail-cache helpers.

Compare View and Experiment View render the same structured comparison result.
Future experimentation-notebook services should consume these modules directly
rather than reproducing parsing or difference-detection logic in Qt widgets.

## Experimentation notebook backend

The experimentation notebook is implemented as a headless domain layer under
`metaview.experiments`. It does not import Qt and can therefore be used by the
future notebook UI, command-line tooling, migrations, and tests.

- `models.py` defines immutable notebooks, experiments, runs, image links, and
  scoped notes.
- `repository.py` defines the persistence contract.
- `sqlite.py` owns the versioned SQLite schema and all SQL.
- `service.py` implements application workflows, including retrospective
  creation of one run per selected image.

Experiment images are referenced by resolved filesystem path and are never
copied into the notebook database. Missing files remain represented so a later
UI can report and relink them. Deleting a notebook cascades through its
experiments, runs, image associations, and notes.


## Experiment creation workflow

Phase 2 introduces the first Qt presentation layer for the experimentation
backend. `metaview.experiments.ui` contains the creation and summary dialogs,
while `metaview.experiments.analysis` remains headless and converts parsed image
metadata into fixed fields, variable fields, missing values, and consistency
warnings.

`MainWindow` owns one `ExperimentService` connected to `experiments.sqlite3`. A
thumbnail selection can be persisted from either the action row or the
thumbnail context menu. Each selected image becomes one ordered run; files are
referenced rather than copied. After creation, the summary dialog displays the
runs as a filmstrip and renders the analysis without querying SQLite or parsing
metadata itself.


## Persistent experiment window

`metaview.experiments.ui.ExperimentWindow` loads experiments by ID through `ExperimentService`. It provides A/B selection across persisted runs, reuses the headless metadata comparison services, and saves run observations and experiment conclusions through the service layer rather than writing to SQLite directly.


## Image Index

The persistent image index is the shared metadata source for library-wide features. Opening a folder discovers every supported image immediately and indexes generation metadata in background workers. Unchanged files reuse cached records; changed or migrated records are reparsed and updated.

The index stores the searchable generation summary used by Prompt Library and Smart Collections, including prompt, model, sampler, scheduler, steps, resolution, and LoRA data. Smart Collections query indexed records rather than reopening image files. Folder watches trigger identity checks and stale records are pruned when a directory is rescanned.
