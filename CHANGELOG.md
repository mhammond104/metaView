## Unreleased

- Added the initial Prompt Library domain package with typed prompt and image-index models.

# Changelog

All notable changes to metaView will be documented here.

## [0.1.0] - 2026-07-11

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

### v0.2 development

- Added a persistent global image index behind an application service and
  repository interface.
- Indexed positive prompts, image paths, directories, modification times and
  file sizes during normal metadata scans.
- Added exact-prompt counts, matching paths, per-directory counts, stale-file
  pruning and index statistics.

## Unreleased (v0.2.0 development)

- Replaced the legacy Prompt Library UI with a repository-backed global library.
- Added prompt star ratings, user-defined tags, notes, search and filtering.
- Added exact-prompt image counts and per-directory counts.
- Added global prompt-result browsing with restoration of the previous view.
- Added one-time import of compatible v0.1.0 Prompt Library entries.
