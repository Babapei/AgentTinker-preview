"""Atomic append-only facts and rebuildable views; no external calls on open or replay."""

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from agenttinker.core.events import Event, RunCreated, SpanFinished, parse_event
from agenttinker.core.projection import RunView, project_events
from agenttinker.core.records import Artifact


class EventConflict(ValueError):
    """The same event identity or sequence was used for different facts."""


def encode(model) -> str:
    return json.dumps(
        model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, allow_nan=False
    )


class SQLiteEventStore:
    def __init__(self, database: Path | str, artifact_root: Path | str | None = None):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root = (
            Path(artifact_root)
            if artifact_root is not None
            else self.database.with_suffix(".artifacts")
        )
        self._connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        try:
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA journal_mode=WAL")
            with self._transaction():
                version = self._connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    tables = self._connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                    if tables:
                        raise ValueError("unrecognized_database_schema")
                    for statement in (
                        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, last_seq INTEGER NOT NULL, "
                        "view_json TEXT NOT NULL)",
                        "CREATE TABLE events (event_id TEXT PRIMARY KEY, "
                        "run_id TEXT NOT NULL REFERENCES runs(run_id), seq INTEGER NOT NULL, "
                        "body TEXT NOT NULL, UNIQUE(run_id, seq))",
                        "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, "
                        "metadata_json TEXT NOT NULL)",
                        "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                        "BEGIN SELECT RAISE(ABORT, 'events_append_only'); END",
                        "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
                        "BEGIN SELECT RAISE(ABORT, 'events_append_only'); END",
                        "PRAGMA user_version=1",
                    ):
                        self._connection.execute(statement)
                elif version != 1:
                    raise ValueError("unsupported_database_schema_version")
        except Exception:
            self.close()
            raise

    def __enter__(self) -> "SQLiteEventStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.execute("COMMIT")
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise

    def _history(self, run_id: str) -> list[Event]:
        return [
            parse_event(row[0])
            for row in self._connection.execute(
                "SELECT body FROM events WHERE run_id=? ORDER BY seq", (run_id,)
            )
        ]

    def _append(self, event: Event) -> Event:
        body = encode(event)
        event = parse_event(body)  # Snapshot nested values before validation and persistence.
        existing = self._connection.execute(
            "SELECT body FROM events WHERE event_id=?", (event.event_id,)
        ).fetchone()
        if existing is not None:
            if existing[0] != body:
                raise EventConflict("event_id_conflict")
            return parse_event(existing[0])
        row = self._connection.execute(
            "SELECT last_seq FROM runs WHERE run_id=?", (event.run_id,)
        ).fetchone()
        if event.seq != (1 if row is None else row[0] + 1):
            raise EventConflict("event_sequence_conflict")
        if row is None and not isinstance(event, RunCreated):
            raise KeyError(event.run_id)
        if isinstance(event, RunCreated) and event.data.parent_run_id is not None:
            parent = self.get_view(event.data.parent_run_id)
            if event.data.source_checkpoint_id not in {
                checkpoint.checkpoint_id for checkpoint in parent.checkpoints
            }:
                raise ValueError("fork_source_checkpoint_missing")
            parent_spans = {span.span_id for span in parent.spans} | set(
                parent.run.inherited_span_ids
            )
            if not set(event.data.inherited_span_ids) <= parent_spans:
                raise ValueError("inherited_span_missing")
        if isinstance(event, SpanFinished) and event.data.cost.kind == "actual":
            self.read_artifact(event.data.cost.evidence_artifact_id)
        view = project_events([*self._history(event.run_id), event])
        if row is None:
            self._connection.execute(
                "INSERT INTO runs(run_id, last_seq, view_json) VALUES (?, ?, ?)",
                (event.run_id, event.seq, encode(view)),
            )
        else:
            self._connection.execute(
                "UPDATE runs SET last_seq=?, view_json=? WHERE run_id=?",
                (event.seq, encode(view), event.run_id),
            )
        self._connection.execute(
            "INSERT INTO events(event_id, run_id, seq, body) VALUES (?, ?, ?, ?)",
            (event.event_id, event.run_id, event.seq, body),
        )
        return event

    def append(self, event: Event) -> Event:
        """Append an explicitly sequenced internal event, or confirm an identical retry."""
        with self._transaction():
            return self._append(event)

    def append_next(self, draft: dict) -> Event:
        """Allocate seq under the write lock; received_at is assigned on first receipt."""
        if "seq" in draft:
            raise ValueError("sequence_is_assigned_by_store")
        with self._transaction():
            existing = self._connection.execute(
                "SELECT body FROM events WHERE event_id=?", (draft["event_id"],)
            ).fetchone()
            row = self._connection.execute(
                "SELECT last_seq FROM runs WHERE run_id=?", (draft["run_id"],)
            ).fetchone()
            old = parse_event(existing[0]) if existing is not None else None
            event = parse_event(
                {
                    "received_at": old.received_at if old else datetime.now(UTC),
                    **draft,
                    "seq": old.seq if old else (row[0] + 1 if row else 1),
                }
            )
            return self._append(event)

    def get_view(self, run_id: str) -> RunView:
        row = self._connection.execute(
            "SELECT view_json FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunView.model_validate_json(row[0])

    def events(self, run_id: str, *, after_seq: int = 0, limit: int = 1000) -> tuple[Event, ...]:
        if (
            type(after_seq) is not int
            or after_seq < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError("invalid_event_cursor_or_limit")
        row = self._connection.execute(
            "SELECT last_seq FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        if after_seq > row[0]:
            raise ValueError("cursor_ahead_of_run")
        return tuple(
            parse_event(item[0])
            for item in self._connection.execute(
                "SELECT body FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after_seq, limit),
            )
        )

    def rebuild_view(self, run_id: str) -> RunView:
        with self._transaction():
            history = self._history(run_id)
            if not history:
                raise KeyError(run_id)
            view = project_events(history)
            self._connection.execute(
                "UPDATE runs SET last_seq=?, view_json=? WHERE run_id=?",
                (view.last_seq, encode(view), run_id),
            )
            return view

    def run_ids(self) -> tuple[str, ...]:
        return tuple(
            row[0] for row in self._connection.execute("SELECT run_id FROM runs ORDER BY run_id")
        )

    def put_artifact(
        self,
        content: bytes,
        *,
        media_type: str,
        source: str,
        exportable: bool = False,
        artifact_id: str | None = None,
    ) -> Artifact:
        artifact = Artifact(
            artifact_id=artifact_id or f"artifact_{uuid4().hex}",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type=media_type,
            created_at=datetime.now(UTC),
            source=source,
            exportable=exportable,
        )
        path = self.artifact_root / artifact.sha256[:2] / artifact.sha256[2:]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("artifact_content_corrupt")
        else:
            handle = NamedTemporaryFile(dir=path.parent, delete=False)
            temporary = Path(handle.name)
            try:
                with handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        with self._transaction():
            self._connection.execute(
                "INSERT INTO artifacts(artifact_id, metadata_json) VALUES (?, ?)",
                (artifact.artifact_id, encode(artifact)),
            )
        return artifact

    def get_artifact(self, artifact_id: str) -> Artifact:
        row = self._connection.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id=?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return Artifact.model_validate_json(row[0])

    def read_artifact(self, artifact_id: str) -> bytes:
        artifact = self.get_artifact(artifact_id)
        content = (self.artifact_root / artifact.sha256[:2] / artifact.sha256[2:]).read_bytes()
        if (
            len(content) != artifact.size_bytes
            or hashlib.sha256(content).hexdigest() != artifact.sha256
        ):
            raise ValueError("artifact_content_corrupt")
        return content
