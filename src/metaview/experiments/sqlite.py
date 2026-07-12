"""SQLite persistence for experimentation notebooks."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .models import (
    Experiment,
    ExperimentNote,
    ExperimentRun,
    Notebook,
    NoteScope,
    RunImage,
)
from .repository import ExperimentNotFoundError, ExperimentRepository

_SCHEMA_VERSION = 1


class SQLiteExperimentRepository(ExperimentRepository):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if str(database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(database_path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version > _SCHEMA_VERSION:
            raise RuntimeError("The experimentation database was created by a newer version of metaView.")
        if version < 1:
            with self._connection:
                self._connection.executescript(
                    """
                    CREATE TABLE experiment_notebooks (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active', 'archived')),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_experiment_notebooks_status_title
                        ON experiment_notebooks(status, title COLLATE NOCASE);

                    CREATE TABLE experiments (
                        id INTEGER PRIMARY KEY,
                        notebook_id INTEGER NOT NULL
                            REFERENCES experiment_notebooks(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        hypothesis TEXT NOT NULL DEFAULT '',
                        method TEXT NOT NULL DEFAULT '',
                        conclusion TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'planned'
                            CHECK(status IN ('planned','active','complete','abandoned')),
                        position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
                        control_run_id INTEGER
                            REFERENCES experiment_runs(id) ON DELETE SET NULL
                            DEFERRABLE INITIALLY DEFERRED,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_experiments_notebook_position
                        ON experiments(notebook_id, position, id);

                    CREATE TABLE experiment_runs (
                        id INTEGER PRIMARY KEY,
                        experiment_id INTEGER NOT NULL
                            REFERENCES experiments(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        notes TEXT NOT NULL DEFAULT '',
                        position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_experiment_runs_experiment_position
                        ON experiment_runs(experiment_id, position, id);

                    CREATE TABLE experiment_run_images (
                        id INTEGER PRIMARY KEY,
                        run_id INTEGER NOT NULL
                            REFERENCES experiment_runs(id) ON DELETE CASCADE,
                        image_path TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'candidate'
                            CHECK(role IN ('candidate','control','reference','representative','rejected')),
                        notes TEXT NOT NULL DEFAULT '',
                        position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
                        rating INTEGER NOT NULL DEFAULT 0 CHECK(rating BETWEEN 0 AND 5),
                        added_at TEXT NOT NULL,
                        UNIQUE(run_id, image_path)
                    );
                    CREATE INDEX idx_experiment_run_images_run_position
                        ON experiment_run_images(run_id, position, id);
                    CREATE INDEX idx_experiment_run_images_path
                        ON experiment_run_images(image_path);

                    CREATE TABLE experiment_notes (
                        id INTEGER PRIMARY KEY,
                        scope TEXT NOT NULL CHECK(scope IN ('notebook','experiment','run','image')),
                        content TEXT NOT NULL,
                        notebook_id INTEGER REFERENCES experiment_notebooks(id) ON DELETE CASCADE,
                        experiment_id INTEGER REFERENCES experiments(id) ON DELETE CASCADE,
                        run_id INTEGER REFERENCES experiment_runs(id) ON DELETE CASCADE,
                        run_image_id INTEGER REFERENCES experiment_run_images(id) ON DELETE CASCADE,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_experiment_notes_notebook ON experiment_notes(notebook_id, created_at);
                    CREATE INDEX idx_experiment_notes_experiment ON experiment_notes(experiment_id, created_at);
                    CREATE INDEX idx_experiment_notes_run ON experiment_notes(run_id, created_at);
                    CREATE INDEX idx_experiment_notes_image ON experiment_notes(run_image_id, created_at);
                    """
                )
                self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def add_notebook(self, notebook: Notebook) -> Notebook:
        if notebook.id is not None:
            raise ValueError("A new notebook must not already have an ID")
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO experiment_notebooks(title,description,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                (notebook.title, notebook.description, notebook.status.value, notebook.created_at.isoformat(), notebook.updated_at.isoformat()),
            )
        return replace(notebook, id=int(cursor.lastrowid))

    def update_notebook(self, notebook: Notebook) -> Notebook:
        self._require_id(notebook.id, "notebook")
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE experiment_notebooks SET title=?,description=?,status=?,updated_at=? WHERE id=?",
                (notebook.title, notebook.description, notebook.status.value, notebook.updated_at.isoformat(), notebook.id),
            )
        if cursor.rowcount == 0:
            raise ExperimentNotFoundError(f"Notebook {notebook.id} was not found")
        return notebook

    def get_notebook(self, notebook_id: int) -> Notebook | None:
        row = self._connection.execute("SELECT * FROM experiment_notebooks WHERE id=?", (notebook_id,)).fetchone()
        return self._notebook(row) if row else None

    def list_notebooks(self, *, include_archived: bool = False) -> list[Notebook]:
        sql = "SELECT * FROM experiment_notebooks"
        params: tuple[object, ...] = ()
        if not include_archived:
            sql += " WHERE status='active'"
        sql += " ORDER BY title COLLATE NOCASE, id"
        return [self._notebook(row) for row in self._connection.execute(sql, params)]

    def delete_notebook(self, notebook_id: int) -> bool:
        return self._delete("experiment_notebooks", notebook_id)

    def add_experiment(self, experiment: Experiment) -> Experiment:
        if experiment.id is not None:
            raise ValueError("A new experiment must not already have an ID")
        with self._connection:
            cursor = self._connection.execute(
                """INSERT INTO experiments(notebook_id,title,description,hypothesis,method,conclusion,status,position,control_run_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                self._experiment_values(experiment),
            )
        return replace(experiment, id=int(cursor.lastrowid))

    def update_experiment(self, experiment: Experiment) -> Experiment:
        self._require_id(experiment.id, "experiment")
        with self._connection:
            cursor = self._connection.execute(
                """UPDATE experiments SET notebook_id=?,title=?,description=?,hypothesis=?,method=?,conclusion=?,status=?,position=?,control_run_id=?,updated_at=? WHERE id=?""",
                (*self._experiment_values(experiment)[:9], experiment.updated_at.isoformat(), experiment.id),
            )
        if cursor.rowcount == 0:
            raise ExperimentNotFoundError(f"Experiment {experiment.id} was not found")
        return experiment

    def get_experiment(self, experiment_id: int) -> Experiment | None:
        row = self._connection.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        return self._experiment(row) if row else None

    def list_experiments(self, notebook_id: int) -> list[Experiment]:
        rows = self._connection.execute("SELECT * FROM experiments WHERE notebook_id=? ORDER BY position,id", (notebook_id,))
        return [self._experiment(row) for row in rows]

    def delete_experiment(self, experiment_id: int) -> bool:
        return self._delete("experiments", experiment_id)

    def add_run(self, run: ExperimentRun) -> ExperimentRun:
        if run.id is not None:
            raise ValueError("A new run must not already have an ID")
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO experiment_runs(experiment_id,title,notes,position,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (run.experiment_id, run.title, run.notes, run.position, run.created_at.isoformat(), run.updated_at.isoformat()),
            )
        return replace(run, id=int(cursor.lastrowid))

    def update_run(self, run: ExperimentRun) -> ExperimentRun:
        self._require_id(run.id, "run")
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE experiment_runs SET experiment_id=?,title=?,notes=?,position=?,updated_at=? WHERE id=?",
                (run.experiment_id, run.title, run.notes, run.position, run.updated_at.isoformat(), run.id),
            )
        if cursor.rowcount == 0:
            raise ExperimentNotFoundError(f"Run {run.id} was not found")
        return run

    def get_run(self, run_id: int) -> ExperimentRun | None:
        row = self._connection.execute("SELECT * FROM experiment_runs WHERE id=?", (run_id,)).fetchone()
        return self._run(row) if row else None

    def list_runs(self, experiment_id: int) -> list[ExperimentRun]:
        rows = self._connection.execute("SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY position,id", (experiment_id,))
        return [self._run(row) for row in rows]

    def delete_run(self, run_id: int) -> bool:
        return self._delete("experiment_runs", run_id)

    def add_run_image(self, image: RunImage) -> RunImage:
        if image.id is not None:
            raise ValueError("A new run image must not already have an ID")
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO experiment_run_images(run_id,image_path,role,notes,position,rating,added_at) VALUES(?,?,?,?,?,?,?)",
                (image.run_id, str(image.image_path), image.role.value, image.notes, image.position, image.rating, image.added_at.isoformat()),
            )
        return replace(image, id=int(cursor.lastrowid))

    def list_run_images(self, run_id: int) -> list[RunImage]:
        rows = self._connection.execute("SELECT * FROM experiment_run_images WHERE run_id=? ORDER BY position,id", (run_id,))
        return [self._run_image(row) for row in rows]

    def remove_run_image(self, run_image_id: int) -> bool:
        return self._delete("experiment_run_images", run_image_id)

    def add_note(self, note: ExperimentNote) -> ExperimentNote:
        if note.id is not None:
            raise ValueError("A new note must not already have an ID")
        with self._connection:
            cursor = self._connection.execute(
                """INSERT INTO experiment_notes(scope,content,notebook_id,experiment_id,run_id,run_image_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (note.scope.value, note.content, note.notebook_id, note.experiment_id, note.run_id, note.run_image_id, note.created_at.isoformat(), note.updated_at.isoformat()),
            )
        return replace(note, id=int(cursor.lastrowid))

    def list_notes(self, *, notebook_id: int | None = None, experiment_id: int | None = None, run_id: int | None = None, run_image_id: int | None = None) -> list[ExperimentNote]:
        filters = [("notebook_id", notebook_id), ("experiment_id", experiment_id), ("run_id", run_id), ("run_image_id", run_image_id)]
        active = [(name, value) for name, value in filters if value is not None]
        if len(active) != 1:
            raise ValueError("Specify exactly one note owner")
        name, value = active[0]
        rows = self._connection.execute(f"SELECT * FROM experiment_notes WHERE {name}=? ORDER BY created_at,id", (value,))
        return [self._note(row) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def _delete(self, table: str, entity_id: int) -> bool:
        with self._connection:
            cursor = self._connection.execute(f"DELETE FROM {table} WHERE id=?", (entity_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _require_id(value: int | None, name: str) -> int:
        if value is None:
            raise ValueError(f"A persisted {name} must have an ID")
        return value

    @staticmethod
    def _dt(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @classmethod
    def _notebook(cls, row: sqlite3.Row) -> Notebook:
        return Notebook(id=row["id"], title=row["title"], description=row["description"], status=row["status"], created_at=cls._dt(row["created_at"]), updated_at=cls._dt(row["updated_at"]))

    @staticmethod
    def _experiment_values(value: Experiment) -> tuple[object, ...]:
        return (value.notebook_id, value.title, value.description, value.hypothesis, value.method, value.conclusion, value.status.value, value.position, value.control_run_id, value.created_at.isoformat(), value.updated_at.isoformat())

    @classmethod
    def _experiment(cls, row: sqlite3.Row) -> Experiment:
        return Experiment(id=row["id"], notebook_id=row["notebook_id"], title=row["title"], description=row["description"], hypothesis=row["hypothesis"], method=row["method"], conclusion=row["conclusion"], status=row["status"], position=row["position"], control_run_id=row["control_run_id"], created_at=cls._dt(row["created_at"]), updated_at=cls._dt(row["updated_at"]))

    @classmethod
    def _run(cls, row: sqlite3.Row) -> ExperimentRun:
        return ExperimentRun(id=row["id"], experiment_id=row["experiment_id"], title=row["title"], notes=row["notes"], position=row["position"], created_at=cls._dt(row["created_at"]), updated_at=cls._dt(row["updated_at"]))

    @classmethod
    def _run_image(cls, row: sqlite3.Row) -> RunImage:
        return RunImage(id=row["id"], run_id=row["run_id"], image_path=Path(row["image_path"]), role=row["role"], notes=row["notes"], position=row["position"], rating=row["rating"], added_at=cls._dt(row["added_at"]))

    @classmethod
    def _note(cls, row: sqlite3.Row) -> ExperimentNote:
        return ExperimentNote(id=row["id"], scope=NoteScope(row["scope"]), content=row["content"], notebook_id=row["notebook_id"], experiment_id=row["experiment_id"], run_id=row["run_id"], run_image_id=row["run_image_id"], created_at=cls._dt(row["created_at"]), updated_at=cls._dt(row["updated_at"]))
