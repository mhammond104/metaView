
### Workflow and UX polish

- Added a richer thumbnail context menu covering Preview, Compare, Collections, Tags, ratings, copy actions, experiments, and file management.
- Added a two-click **Compare With…** workflow with Escape to cancel.
- Added direct drag-and-drop assignment from thumbnails onto user tags.
- Added consistent shortcuts for Preview, Compare, Collections, Tags, Experiments, search, and Library-item rename.
- Added bulk rating for multi-selected images.
- Reorganised the menu bar around File, Edit, Image, Library, Research, View, and Help.
- Expanded the keyboard-shortcut reference and status-bar guidance.

# Changelog

## [Unreleased]

### Added

- Smart Collections with saved AND-based rules for rating, model, sampler, scheduler, positive prompt, and filename.
- Smart Collection creation, editing, deletion, browsing, refresh, and empty-result guidance.
- Background metadata indexing with visible progress and persistent library-wide index status.
- Static Collections for organising images without moving or duplicating files.
- Collection sidebar with image counts, drag-and-drop, and collection browsing.
- Multi-image Add to Collection and Remove from Collection actions.
- User-defined image tags with multi-image assignment, sidebar browsing, rename/delete actions, and thumbnail tooltip display.
- Smart Collection rules based on user tags.

### Changed

- Expanded the image index to store model, sampler, scheduler, steps, resolution, and LoRA summaries.
- Reused cached metadata for unchanged files instead of reparsing them whenever a folder is opened.
- Smart Collections now evaluate indexed metadata and refresh automatically when background indexing completes.

### Fixed

- Prevented Smart Collections from omitting images whose thumbnail metadata had not yet been lazily indexed.
- Added automatic migration and one-time backfill for older prompt-only image-index records.


All notable changes to metaView are documented here.

## [0.3.0] - Unreleased

### Added

- Persistent Experiment Notebook with notebooks, experiments, ordered runs, image links, run notes, and conclusions.
- Existing-experiment browser and direct Experiment Notebook access from the main window and menu bar.
- Persistent Experiment Window with A/B image selection, filmstrip navigation, parameter, prompt, and LoRA comparison, experiment summaries, and consistency warnings.
- Integrated Preview window with smooth zooming, panning, fit-to-window, 100% view, fullscreen navigation, and a floating auto-hide toolbar.
- Full File, Edit, Image, Experiment, View, and Help menus exposing the application's main functions.
- Thumbnail metadata tooltips showing model, sampler and steps, scheduler, resolution, and LoRAs.
- Thumbnail context actions for Preview, external opening, copying paths, revealing files, and moving images to Trash.
- Selectable application themes: Catppuccin Macchiato, Nord, Tokyo Night, Gruvbox Dark, Dracula, Catppuccin Latte, and Gruvbox Light.
- Centralised UI metrics and a compact application-wide visual design system.

### Changed

- Double-clicking a thumbnail now opens the integrated Preview instead of the operating system image viewer.
- Refined the interface with denser controls, clearer visual hierarchy, flatter toolbars, slimmer scrollbars, improved tabs, menus, focus states, and action strips.
- Refactored ComfyUI metadata parsing into Qt-independent services.
- Added canonical prompt and LoRA normalisation helpers.
- Added reusable structured parameter and LoRA comparison services shared by Compare View and Experiment View.
- Improved Linux file-manager integration by launching the active graphical file manager directly where possible.
- Renamed the application presentation from a metadata viewer to a GenAI Image and Experiment Manager.

### Fixed

- Restored and redirected thumbnail double-click handling.
- Fixed Preview toolbar anchoring so it remains top-centred while the image is panned.
- Fixed Preview top-edge toolbar reveal behaviour.
- Enabled smooth full-resolution scaling during Preview zoom.
- Improved workflow JSON drag-and-drop compatibility on Windows, including File Explorer and Chromium-based targets.
- Removed remaining user-facing Catppuccin Mocha references after migration to Macchiato.

## [0.2.1]

### Fixed

- Packaging and release-workflow issues following the v0.2.0 release.
- Application startup and metadata-facade regressions in packaged builds.

## [0.2.0]

### Added

- Global Prompt Library.
- Prompt ratings, tags, notes, search, filtering, and sorting.
- Persistent global image index and exact-prompt image counts.
- Cross-directory prompt result browsing with previous-view restoration.
- Similarity Search results view with previous-view restoration.

### Changed

- Refactored the application into focused modules.
- Replaced the legacy Prompt Library backend.
- Improved thumbnail action-state handling.
- Consolidated temporary results views.

### Fixed

- Image-rating controls after thumbnail selection.
- Open Image selection handling.
- Experiment View availability with multiple selections.
- Metadata-panel imports after refactoring.

## [0.1.0]

### Added

- Filesystem tree, thumbnail browser, lazy loading, and persistent thumbnail cache.
- Embedded GenAI metadata inspection for ComfyUI-oriented image workflows.
- Search and filtering by filename, prompt, model, sampler, scheduler, and rating.
- Responsive full-image display.
- Side-by-side image and metadata comparison with linked zoom and pan.
- LoRA comparison with highlighted differences.
- Similarity Search by model, LoRAs, seed, prompt, sampler, scheduler, and resolution.
- Persistent Prompt Library with tags, notes, editing, copying, and source-image links.
- Persistent 0–5 star ratings with filtering and sorting.
- Experiment View for identical-positive-prompt image groups.
- Cross-platform source layout and GitHub Actions workflows.

### Fixed

- Prevented nanosecond file timestamps and large file sizes from overflowing Qt's 32-bit signal arguments during background indexing.
- Ensured metadata-worker failures still advance indexing progress and cannot leave Smart Collections permanently incomplete.
