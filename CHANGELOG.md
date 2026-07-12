# Changelog



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

