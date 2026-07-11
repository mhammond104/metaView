# metaView GenAI Metadata Viewer

**metaView** is a cross-platform desktop application for browsing AI-generated images, inspecting embedded generation metadata, comparing generations, and organising successful prompts.

It is designed primarily around ComfyUI-style metadata, with an emphasis on understanding experiments rather than merely displaying image properties.

> Current status: **v0.1.0 alpha**. The application is useful, but packaging and broader workflow compatibility still need real-world testing.

## Features

- Filesystem tree and responsive thumbnail browser
- Persistent thumbnail cache and lazy thumbnail loading
- Search and filtering by filename, prompt, model, sampler, scheduler, and star rating
- Full-size image preview with responsive splitter resizing
- Summary, LoRA, prompt JSON, workflow JSON, and raw metadata views
- Side-by-side comparison with linked zoom and pan
- Highlighted parameter and LoRA differences
- Similarity Search by checkpoint, LoRAs, seed, positive prompt, sampler, scheduler, and resolution
- Prompt Library with titles, tags, notes, editing, clipboard copy, and links to originating images
- Persistent 0–5 star ratings, rating filters, and rating-aware sorting
- Experiment View for images in one directory sharing an identical positive prompt
- Dark interface, persistent UI settings, live folder watching, and drag-and-drop support

## Screenshots

Screenshots will be added before the first public release. The `screenshots` directory is ready for the main window, comparison view, Experiment View, and Prompt Library images.

## Run from source

Python 3.11 or newer is required.

### Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
py main.py
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 main.py
```

PySide6 includes the Qt libraries required by the application; a separate Qt installation is not normally needed.

## Install as a Python package

```bash
python -m pip install -e .
metaview
```

## Build a native application

Install the development requirements and run the platform-native PyInstaller build:

```bash
python -m pip install -r requirements-dev.txt
python scripts/build.py
```

PyInstaller is not a cross-compiler. Windows, macOS, and Linux packages must each be built on their respective operating system. GitHub Actions handles this using separate hosted runners.

## Repository layout

```text
metaView/
├── .github/workflows/     # CI, native builds, and release publishing
├── screenshots/          # README and release screenshots
├── scripts/build.py       # Cross-platform PyInstaller entry point
├── src/metaview/          # Application package and bundled assets
├── tests/                 # Automated source and asset checks
├── main.py                # Convenient development launcher
├── pyproject.toml         # Package metadata
├── requirements.txt       # Runtime dependencies
└── requirements-dev.txt   # Test and packaging dependencies
```

The application currently remains mostly in one module to minimise regression risk before the first release. Future work can split metadata parsing, comparison, Experiment View, ratings, and prompt-library functionality into focused modules.

## GitHub Actions

- **CI** runs source compilation and tests on Windows, macOS, and Linux with Python 3.11 and 3.13.
- **Build applications** runs manually or whenever a tag matching `v*` is pushed. It creates downloadable Windows, macOS, and Linux artifacts.
- **Publish release** is run manually after the tagged build succeeds. It creates a GitHub Release and attaches all three platform archives.

## Planned features

- Combined model, LoRA, sampler, and scheduler statistics window
- Collections
- Generation timeline
- Contact-sheet generation
- Improved prompt difference visualisation
- Duplicate and near-duplicate detection
- More comprehensive automated tests

## Privacy and stored data

Ratings and Prompt Library entries are stored locally in the operating system's application-data area. metaView does not need to modify source images to save ratings or prompt-library records.

## Contributing

Bug reports and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

metaView is released under the [MIT License](LICENSE).
