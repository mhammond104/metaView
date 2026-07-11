# metaView GenAI Metadata Viewer

**metaView** is a cross-platform desktop application for browsing AI-generated images, inspecting embedded generation metadata, comparing generations, and organising successful prompts.

It is designed primarily around ComfyUI-style metadata, with an emphasis on understanding experiments rather than merely displaying image properties.

> Current status: **v0.1.0 alpha**. The application is useful, but packaging and broader workflow compatibility still need real-world testing.

## Features

- Filesystem tree and responsive thumbnail browser
- Search and filtering by filename, prompt, model, sampler, scheduler, and star rating
- Summary, LoRA, prompt JSON, workflow JSON, and raw metadata views
- Side-by-side comparison with linked zoom and pan with highlighted parameter and LoRA differences
- Similarity Search by checkpoint, LoRAs, seed, positive prompt, sampler, scheduler, and resolution
- Prompt Library with titles, tags, notes, editing, clipboard copy, and links to originating images
- Star ratings wuth rating filters, and rating-aware sorting
- Experiment View for comparing images with identical positive prompts

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

## Privacy and stored data

Ratings and Prompt Library entries are stored locally in the operating system's application-data area. metaView does not need to modify source images to save ratings or prompt-library records.

## Contributing

Bug reports and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

metaView is released under the [MIT License](LICENSE).
