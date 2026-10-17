"""Export closed observations and distributable content; never open the saver or an SDK."""

from datetime import UTC, datetime

from agenttinker.core.records import VersionRef
from agenttinker.core.states import TERMINAL_STATUSES
from agenttinker.packages.context import context_for
from agenttinker.packages.models import (
    EvaluationBinding,
    ExperimentPackage,
    Manifest,
    ManifestEntry,
    PackageRejected,
    PortableArtifact,
    PortableRun,
    RecordSource,
    canonical,
    digest,
    strict_json,
)
from agenttinker.packages.portable import (
    bind_evaluations,
    inspect_package,
    observation_events,
    observation_view,
    redact,
)
from agenttinker.storage.packages import SQLitePackageStore


def make_package(
    files,
    *,
    root_run_id,
    title,
    kind="experiment",
    source="AgentTinker local observation export",
    created_at=None,
):
    entries = tuple(
        ManifestEntry(path=path, sha256=digest(value), size_bytes=len(canonical(value)))
        for path, value in sorted(files.items())
    )
    package = ExperimentPackage(
        manifest=Manifest(
            title=title,
            source=source,
            created_at=created_at or datetime.now(UTC),
            producer=VersionRef(id="agenttinker", version="0.0.1"),
            root_run_id=root_run_id,
            kind=kind,
            transformations=(
                "execution_disabled",
                "checkpoint_locators_removed",
                "credential_fields_redacted",
            ),
            entries=entries,
        ),
        files=files,
    )
    inspect_package(package)
    return package


def export_run(database, run_id):
    with SQLitePackageStore(database) as store:
        if store.get_view(run_id).run.mode == "imported":
            return store.package_for_run(run_id)
        views, visited, current = [], set(), run_id
        while current is not None:
            if current in visited or len(views) >= 32:
                raise PackageRejected("package_lineage_invalid")
            visited.add(current)
            view = store.get_view(current)
            if view.run.status not in TERMINAL_STATUSES:
                raise PackageRejected("package_run_active")
            if view.run.mode == "imported":
                raise PackageRejected("package_context_unsupported")
            views.insert(0, view)
            current = view.run.parent_run_id
        context = context_for(views)
        records, artifacts = {}, {}
        for view in views:
            events, offset = [], 0
            while offset < view.last_seq:
                page = store.events(view.run.run_id, after_seq=offset)
                if not page or len(events) + len(page) > 5000:
                    raise PackageRejected("package_events_incomplete")
                events.extend(page)
                offset = page[-1].seq
            # The event stream cannot change after terminal. Assessments remain separate records.
            snapshot = observation_view(view, playback=True)
            evaluations, reviews = store.assessment_snapshot(view.run.run_id)
            if len(evaluations) > 1000 or len(reviews) > 1000:
                raise PackageRejected("package_too_large")
            records[view.run.run_id] = PortableRun(
                source=RecordSource(
                    run_id=view.run.run_id, mode=view.run.mode, view_sha256=digest(view)
                ),
                view=snapshot,
                events=observation_events(events),
                evaluations=evaluations,
                reviews=reviews,
                # Bindings are calculated once the complete inherited prefix is available below.
                evaluation_bindings=tuple(
                    EvaluationBinding(
                        evaluation_id=e.evaluation_id,
                        source_input_hash=e.input_hash,
                        portable_input_hash="0" * 64,
                    )
                    for e in evaluations
                ),
            )
            for span in snapshot.spans:
                if span.cost.evidence_artifact_id is None:
                    continue
                metadata = store.get_artifact(span.cost.evidence_artifact_id)
                if not metadata.exportable:
                    raise PackageRejected("artifact_not_exportable")
                content = store.read_artifact(metadata.artifact_id).decode("utf-8")
                artifact = PortableArtifact(metadata=metadata, content=content)
                if metadata.media_type == "application/json" and redact(
                    strict_json(content.encode())
                ) != strict_json(content.encode()):
                    raise PackageRejected("artifact_contains_credentials")
                if redact(artifact.model_dump(mode="json")) != artifact.model_dump(mode="json"):
                    raise PackageRejected("artifact_contains_credentials")
                artifacts[metadata.artifact_id] = artifact
        for record_id, record in records.items():
            records[record_id] = record.model_copy(
                update={"evaluation_bindings": bind_evaluations(record, records)}
            )
        files = {"context.json": context.model_dump(mode="json")}
        files.update(
            {f"runs/{key}.json": value.model_dump(mode="json") for key, value in records.items()}
        )
        files.update(
            {
                f"artifacts/{key}.json": value.model_dump(mode="json")
                for key, value in artifacts.items()
            }
        )
        return make_package(files, root_run_id=run_id, title=context.experiment.title)
