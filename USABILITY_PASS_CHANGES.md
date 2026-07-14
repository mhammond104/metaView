# v0.3.0 usability pass

Implemented from Windows testing feedback:

- Thumbnail double-click now opens the integrated Preview window.
- Preview uses smooth pixmap transformation while zooming.
- Preview toolbar is anchored to the Preview window rather than the image scene.
- Moving the pointer to the top edge reveals a hidden Preview toolbar.
- Added a direct Experiment Notebook button and menu action.
- Added an Experiment Notebook browser for opening existing experiments.
- Added File, Edit, Image, Experiment, View and Help menus.
- Added menu actions for copying prompts and paths, Preview, system viewer,
  file-manager reveal, similarity search, comparison, experiments and Trash.
- Added Add to Experiment, which creates one run per selected image.

## Validation

Run on the ThinkPad:

```bash
source .venv/bin/activate
python -m compileall -q src main.py
PYTHONPATH=src pytest
python main.py
```

Manually verify Preview toolbar positioning/reveal, smooth zooming, all menu actions,
opening existing experiments, and adding disposable images to an experiment.
