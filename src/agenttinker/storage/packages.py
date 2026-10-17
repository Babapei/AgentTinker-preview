"""One transaction imports observations, mappings, provenance and request identity."""

from datetime import UTC, datetime
from uuid import uuid4

from agenttinker.core.requests import request_identity
from agenttinker.packages.mapping import ImportMapping
from agenttinker.packages.models import (
    ExperimentPackage,
    ImportedRunLink,
    ImportProvenance,
    ImportResult,
    PackageRejected,
    canonical,
    digest,
)
from agenttinker.packages.portable import inspect_package, normalize_package, parse_package
from agenttinker.storage.evaluations import SQLiteEvaluationStore
from agenttinker.storage.sqlite import EventConflict, encode


class SQLitePackageStore(SQLiteEvaluationStore):
    def get_import(self, import_id):
        row = self._connection.execute(
            "SELECT result_json FROM imports WHERE import_id=?", (import_id,)
        ).fetchone()
        if row is None:
            raise PackageRejected("import_not_found")
        return ImportResult.model_validate_json(row[0])

    def package_for_run(self, run_id):
        row = self._connection.execute(
            "SELECT i.package_json FROM imports i JOIN import_runs r USING(import_id) "
            "WHERE r.run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise PackageRejected("import_not_found")
        return ExperimentPackage.model_validate_json(row[0])

    def provenance(self, run_id):
        self.get_view(run_id)
        row = self._connection.execute(
            "SELECT import_id, source_run_id FROM import_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        result, package = self.get_import(row[0]), self.package_for_run(run_id)
        context, records, _ = inspect_package(package)
        record = records[row[1]]
        return ImportProvenance(
            import_id=result.import_id,
            local_run_id=run_id,
            imported_at=result.imported_at,
            source_package_sha256=result.source_package_sha256,
            portable_package_sha256=result.portable_package_sha256,
            title=result.title,
            source=package.manifest.source,
            license=package.manifest.license,
            source_run_id=record.source.run_id,
            source_mode=record.source.mode,
            source_view_sha256=record.source.view_sha256,
            portable_view_sha256=digest(record.view),
            context=context,
            evaluations=record.evaluations,
            reviews=record.reviews,
            evaluation_bindings=record.evaluation_bindings,
        )

    def import_data(self, data: bytes, request_key):
        package = parse_package(data)
        source_hash = digest(package)
        fingerprint = request_identity(
            request_key, {"operation": "import", "package_sha256": source_hash}
        )
        try:
            portable = normalize_package(package)
        except PackageRejected:
            raise
        except (ValueError, TypeError, KeyError, RecursionError):
            raise PackageRejected("package_invalid") from None
        _, records, artifacts = inspect_package(portable)
        with self._transaction():
            previous = self._connection.execute(
                "SELECT fingerprint, import_id FROM import_requests WHERE request_key=?",
                (request_key,),
            ).fetchone()
            if previous is not None:
                if previous[0] != fingerprint:
                    raise EventConflict("idempotency_key_payload_conflict")
                return self.get_import(previous[1]), False
            duplicate = self._connection.execute(
                "SELECT import_id FROM imports WHERE source_sha256=?",
                (source_hash,),
            ).fetchone()
            if duplicate is not None:
                result = self.get_import(duplicate[0])
                created = False
            else:
                mapping = ImportMapping(records, artifacts)
                links = tuple(
                    ImportedRunLink(
                        source_run_id=key,
                        local_run_id=mapping.runs[key],
                        source_mode=record.source.mode,
                        record_playback=record.events is not None,
                    )
                    for key, record in records.items()
                )
                result = ImportResult(
                    import_id=f"import_{uuid4().hex}",
                    source_package_sha256=source_hash,
                    portable_package_sha256=digest(portable),
                    imported_at=datetime.now(UTC),
                    title=package.manifest.title,
                    root_run_id=mapping.runs[package.manifest.root_run_id],
                    runs=links,
                )
                self._connection.execute(
                    "INSERT INTO imports(import_id, source_sha256, package_json, result_json) "
                    "VALUES (?, ?, ?, ?)",
                    (result.import_id, source_hash, canonical(portable).decode(), encode(result)),
                )
                for key, artifact in artifacts.items():
                    metadata = artifact.metadata.model_copy(
                        update={"artifact_id": mapping.artifacts[key]}
                    )
                    self._put_artifact(metadata, artifact.content.encode())
                pending = set(records)
                while pending:
                    ready = [
                        key for key in pending if records[key].view.run.parent_run_id not in pending
                    ]
                    if not ready:
                        raise PackageRejected("package_lineage_invalid")
                    for key in ready:
                        view, events = mapping.observations(records[key])
                        self._connection.execute(
                            "INSERT INTO runs(run_id, last_seq, view_json) VALUES (?, ?, ?)",
                            (view.run.run_id, view.last_seq, encode(view)),
                        )
                        self._connection.executemany(
                            "INSERT INTO events(event_id, run_id, seq, body) VALUES (?, ?, ?, ?)",
                            ((e.event_id, e.run_id, e.seq, encode(e)) for e in events),
                        )
                        self._connection.execute(
                            "INSERT INTO import_runs(run_id, import_id, source_run_id) "
                            "VALUES (?, ?, ?)",
                            (view.run.run_id, result.import_id, key),
                        )
                        pending.remove(key)
                created = True
            self._connection.execute(
                "INSERT INTO import_requests(request_key, fingerprint, import_id) VALUES (?, ?, ?)",
                (request_key, fingerprint, result.import_id),
            )
            return result, created
