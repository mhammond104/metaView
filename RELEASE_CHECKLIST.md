# metaView v0.3.0 release checklist

## Source validation

- [ ] Confirm the working branch is clean and up to date.
- [ ] Run `python -m compileall -q src tests main.py`.
- [ ] Run `PYTHONPATH=src pytest`.
- [ ] Launch with `python main.py` and complete a basic smoke test.

## Manual smoke test

- [ ] Open a folder containing representative ComfyUI images.
- [ ] Confirm thumbnail loading, filtering, ratings, and metadata tooltips.
- [ ] Confirm double-click and Space open Preview.
- [ ] Test Preview zoom, pan, fit, 100%, navigation, fullscreen, and toolbar reveal.
- [ ] Test Compare, Similarity Search, Experiment View, and Experiment Notebook.
- [ ] Test Copy Path, Copy Prompt, Reveal in File Manager, and Move to Trash.
- [ ] Switch through all seven themes and restart to verify persistence.

## Documentation

- [ ] Replace `screenshots/main_window.png` with a current Catppuccin Macchiato screenshot.
- [ ] Review `README.md`, `CHANGELOG.md`, and `RELEASE_NOTES.md`.
- [ ] Confirm the About dialog and application title show version 0.3.0 naming.

## Build validation

- [ ] Run the Build applications workflow on the release branch.
- [ ] Smoke-test the Windows archive on the GenAI machine.
- [ ] Smoke-test the Linux archive.
- [ ] Smoke-test the macOS archive, if available.

## Publish

- [ ] Merge the release branch to `main`.
- [ ] Create and push the annotated `v0.3.0` tag.
- [ ] Confirm the Release workflow publishes all three platform archives.
- [ ] Check the rendered release notes and downloadable files.
