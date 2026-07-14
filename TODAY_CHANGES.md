# Usability improvements applied

This source tree is based on `feature/experimentation-notebook` and includes the following work:

- Restored double-clicking a thumbnail to open it in the operating system's default image viewer.
- Refactored image opening through a reusable `open_image(path)` method.
- Expanded the thumbnail context menu with:
  - Open Image
  - Show in Explorer / Show in Finder / Show in File Manager
  - Copy Path
  - Move to Trash
- Added missing-file checks and user-facing error messages.
- Added thumbnail hover tooltips containing:
  - Model
  - Sampler and step count
  - Scheduler
  - Resolution
  - LoRA names and strengths (up to eight entries, with overflow count)
- Tooltip metadata is populated by the existing background metadata worker; hovering performs no file reads.

## Validation performed

- `src/metaview/main_window.py` and `src/metaview/workers.py` pass Python bytecode compilation.
- The full pytest suite could not be collected in the packaging environment because PySide6 is not installed there. Run the normal tests in the project's virtual environment before committing.

## Suggested commands on the ThinkPad

```bash
source .venv/bin/activate
PYTHONPATH=src pytest
PYTHONPATH=src python main.py
```

## Built-in Preview window

- Added a reusable `src/metaview/preview.py` component.
- Right-click **Preview** opens the selected image internally.
- Press **Space** to preview the current thumbnail.
- Mouse wheel zooms around the pointer; click-drag pans.
- Double-click toggles fit-to-window and 100%.
- Left/Right and Home/End navigate the current visible thumbnail results.
- **F** fits, **1** selects 100%, **F11** toggles fullscreen, and Escape exits fullscreen or closes Preview.
- The status bar shows path, result position, and zoom percentage.

## Preview toolbar refinement

- Added a compact floating toolbar overlay which does not resize the image.
- Added Previous, Next, Fit, 100%, Zoom Out, Zoom In, Fullscreen and Close controls.
- Added `T` to show or hide the toolbar.
- The toolbar remains visible by default in windowed mode.
- In fullscreen, the toolbar hides after two seconds of inactivity and reappears when the pointer moves near the top edge.
- Pressing `T` in fullscreen pins the toolbar visible or hidden for the remainder of that fullscreen session.
- Rotation was deliberately omitted from the preview workflow.
