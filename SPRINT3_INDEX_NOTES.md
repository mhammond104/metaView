# v0.3.1 Sprint 3 — Image Index 2.0

## Included

- Persistent full generation-summary metadata in the image index.
- Background indexing progress in the main status bar.
- Reuse of cached metadata for unchanged images.
- Automatic schema migration and one-time backfill of older prompt-only rows.
- Stale-path pruning when folders are rescanned.
- Smart Collections evaluated from indexed metadata rather than reopening image files.
- Automatic refresh of an open Smart Collection when indexing completes.

## ThinkPad validation

```bash
source .venv/bin/activate
python -m compileall -q src tests main.py
PYTHONPATH=src pytest
python main.py
```

Open a large folder and confirm the permanent status-bar label progresses from
`Indexing: n/total` to `Index: total images`. Reopening the same unchanged folder
should complete immediately from cached index metadata.
