"""Validate and redact bounded observation data, without a runtime or filesystem paths."""

from copy import deepcopy

from pydantic import ValidationError

from agenttinker.core.events import parse_event
from agenttinker.core.projection import RunView
from agenttinker.core.records import Capabilities
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.evaluation import evidence_hash
from agenttinker.packages.models import (
    EvaluationBinding,
    ExperimentContext,
    ExperimentPackage,
    PackageRejected,
    PortableArtifact,
    PortableRun,
    strict_json,
)


def redact(value):
    """Remove recognized credential fields; free-form user text remains user content."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = key.casefold().replace("_", "").replace("-", "").replace(".", "")
            sensitive = normalized in {
                "authorization",
                "proxyauthorization",
                "password",
                "clientsecret",
                "accesstoken",
                "refreshtoken",
                "cookie",
                "setcookie",
                "credentials",
            } or normalized.endswith("apikey")
            result[key] = "[REDACTED]" if sensitive else redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return deepcopy(value)


def observation_view(view: RunView, *, playback: bool):
    value = redact(view.model_dump(mode="json"))
    value["run"]["capabilities"] = Capabilities(record_playback=playback).model_dump(mode="json")
    for checkpoint in value["checkpoints"]:
        checkpoint.update(locator={}, allowed_patch_fields=[])
    return RunView.model_validate(value)


def observation_events(events):
    result = []
    for event in events:
        value = redact(event.model_dump(mode="json"))
        if value["type"] == "run.created":
            value["data"]["capabilities"] = Capabilities().model_dump(mode="json")
        if value["type"] == "checkpoint.saved":
            value["data"].update(locator={}, allowed_patch_fields=[])
        result.append(parse_event(value))
    return tuple(result)


def inherited_spans(record, records):
    needed, found, visited = set(record.view.run.inherited_span_ids), {}, set()
    parent_id = record.view.run.parent_run_id
    while needed:
        if parent_id is None or parent_id in visited or parent_id not in records:
            raise ValueError("package_inherited_span_missing")
        visited.add(parent_id)
        parent = records[parent_id].view
        for span in parent.spans:
            if span.span_id in needed:
                found[span.span_id] = span
                needed.remove(span.span_id)
        parent_id = parent.run.parent_run_id
    return tuple(found[span_id] for span_id in record.view.run.inherited_span_ids)


def bind_evaluations(record, records):
    if not record.evaluations:
        return ()
    inherited = inherited_spans(record, records)
    portable_hash = evidence_hash(record.view, inherited)
    return tuple(
        EvaluationBinding(
            evaluation_id=e.evaluation_id,
            source_input_hash=e.input_hash,
            portable_input_hash=portable_hash,
        )
        for e in record.evaluations
    )


def inspect_package(package: ExperimentPackage):
    """Semantic reference checks after file hashes; no imported schema is executed."""
    context = (
        ExperimentContext.model_validate(package.files["context.json"])
        if "context.json" in package.files
        else None
    )
    if (package.manifest.kind == "experiment") != (context is not None):
        raise ValueError("package_context_missing")
    records, artifacts = {}, {}
    for path, value in package.files.items():
        if path == "context.json":
            continue
        if path.startswith("runs/"):
            record = PortableRun.model_validate(value)
            if path != f"runs/{record.source.run_id}.json":
                raise ValueError("package_run_path_mismatch")
            records[record.source.run_id] = record
        else:
            artifact = PortableArtifact.model_validate(value)
            if path != f"artifacts/{artifact.metadata.artifact_id}.json":
                raise ValueError("package_artifact_path_mismatch")
            artifacts[artifact.metadata.artifact_id] = artifact
    if not 1 <= len(records) <= 32 or package.manifest.root_run_id not in records:
        raise ValueError("package_root_missing")
    identities = {
        kind: set()
        for kind in ("span_id", "checkpoint_id", "event_id", "evaluation_id", "review_id")
    }
    for record in records.values():
        run = record.view.run
        parent = records.get(run.parent_run_id)
        if run.parent_run_id is not None and (
            parent is None
            or run.source_checkpoint_id not in {cp.checkpoint_id for cp in parent.view.checkpoints}
            or not set(run.inherited_span_ids)
            <= {s.span_id for s in parent.view.spans} | set(parent.view.run.inherited_span_ids)
            or run.intervention is not None
            and run.intervention.before != parent.view.run.config.tool_policy
        ):
            raise ValueError("package_lineage_mismatch")
        visited, current = {run.run_id}, parent
        while current is not None:
            if current.source.run_id in visited:
                raise ValueError("package_lineage_cycle")
            visited.add(current.source.run_id)
            current = records.get(current.view.run.parent_run_id)
        inherited_spans(record, records)
        for values, field in (
            (record.view.spans, "span_id"),
            (record.view.checkpoints, "checkpoint_id"),
            (record.events or (), "event_id"),
            (record.evaluations, "evaluation_id"),
            (record.reviews, "review_id"),
        ):
            for item in values:
                identity = getattr(item, field)
                if identity in identities[field]:
                    raise ValueError("package_duplicate_record_identity")
                identities[field].add(identity)
        available = {s.span_id for s in record.view.spans} | set(run.inherited_span_ids)
        if any(
            s.parent_span_id is not None and s.parent_span_id not in available
            for s in record.view.spans
        ):
            raise ValueError("package_span_parent_missing")
        if any(
            s.cost.kind == "actual" and s.cost.evidence_artifact_id not in artifacts
            for s in record.view.spans
        ):
            raise ValueError("package_cost_evidence_missing")
        if context is not None and (
            run.config.agent != context.agent.ref
            or run.config.task != context.case.task
            or run.config.fixture_hash != context.fixture.sha256
        ):
            raise ValueError("package_context_mismatch")
        if record.evaluations:
            if (
                context is None
                or context.agent.ref != corpus.AGENT
                or context.case != corpus.dataset_case()
                or record.evaluation_bindings != bind_evaluations(record, records)
            ):
                raise ValueError("package_evidence_binding_mismatch")
            declared = {e.ref.id: e.ref.version for e in context.evaluators}
            if any(
                declared.get(e.evaluator.id) != e.evaluator.version
                for e in (*record.evaluations, *record.reviews)
            ):
                raise ValueError("package_evaluator_missing")
    return context, records, artifacts


def parse_package(data: bytes) -> ExperimentPackage:
    try:
        package = ExperimentPackage.model_validate(strict_json(data))
        inspect_package(package)
        return package
    except PackageRejected:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, ValidationError):
        raise PackageRejected("package_invalid") from None
