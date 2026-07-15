
### Usability pass

- Double-click thumbnails to open integrated Preview.
- Added full File/Edit/Image/Experiment/View/Help menu bar.
- Added direct Experiment Notebook access and existing-experiment browser.
- Fixed Preview toolbar anchoring and top-edge reveal.
- Enabled smooth Preview scaling while zooming.
# Changelog

## 0.3.0 - Unreleased

- Added Experiment Notebook foundations and UI integration.
- Added integrated zoomable, pannable Preview with fullscreen navigation and overlay toolbar.
- Added application-wide selectable themes: Catppuccin Macchiato, Gruvbox Dark, Tokyo Night, Dracula, Catppuccin Latte, and Gruvbox Light.
- Restored thumbnail double-click opening and added richer context-menu actions.
- Added cached thumbnail metadata tooltips.


## Unreleased

### Added
- Persistent Experiment Window with selectable A/B images, thumbnail filmstrip, parameter, prompt and LoRA comparison, experiment summary, consistency warnings, editable run notes, and editable experiment conclusions.
- Experiment service operations for updating run notes and conclusions.



### Experimentation notebook — Phase 1

- Added Qt-independent notebook, experiment, run, image-link, and note models.
- Added a versioned SQLite experimentation repository with cascading ownership.
- Added services for creating notebooks, experiments and runs, attaching images,
  and creating retrospective experiments from selected images.
- Added persistence and domain tests, including missing-image references and
  cascade deletion.

## Unreleased

### Added

- Added the first experimentation-notebook workflow: create a persistent experiment from selected thumbnails.
- Added inline notebook creation, ordered runs, an experiment filmstrip, and immediate fixed/variable metadata analysis.
- Added consistency warnings for differing prompts, models, resolutions, and partially missing metadata.

### Changed

- Extracted ComfyUI metadata parsing into a Qt-independent service.
- Added canonical prompt and LoRA normalisation helpers.
- Added reusable structured parameter and LoRA comparison services.
- Refactored Compare View and Experiment View to use the shared comparison logic.

## Unreleased

- Display image resolution in Comparison View and Experiment View, highlighting differences.
- Improve workflow JSON drag-and-drop compatibility on Windows, including File Explorer and Chromium-based targets.

All notable changes to metaView will be documented here.

## [0.2.0]

### Added

- Global prompt library
- Prompt ratings, tags, and notes
- Prompt search, filtering, and sorting
- Persistent global image index
- Exact-prompt image counts
- Cross-directory prompt result browsing
- Temporary prompt view with previous-view-state restoration
- Temporary similarity search results view with previous-view-state restoration

### Changed
- Refactored application into focused, manageable modules
- Replaced legacy Prompt Library backend
- Improved thumbnail action-state handling
- Consolidated temporary resutls views

### Fixed
- Fixed image-rating controls after thumbnail selection
- Fixed 'Open Image' selection handling
- Fixed Experiment View availability with multiple selections
- Fixed metadata panel imports after refactoring



## [0.1.0]

### Added

- Filesystem tree, thumbnail browser, lazy loading, and persistent thumbnail cache.
- Embedded GenAI metadata inspection for ComfyUI-oriented image workflows.
- Search and filtering by filename, prompt, model, sampler, scheduler, and rating.
- Responsive full-image preview.
- Side-by-side image and metadata comparison with linked zoom and pan.
- LoRA comparison with highlighted differences.
- Similarity search by model, LoRAs, seed, prompt, sampler, scheduler, and resolution.
- Persistent prompt library with tags, notes, editing, copying, and source-image links.
- Persistent 0–5 star ratings with filtering and sorting.
- Experiment View for identical-positive-prompt image groups.
- Cross-platform source layout and GitHub Actions workflows.
