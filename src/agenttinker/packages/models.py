"""Bounded JSON package, content integrity, and explicit observation provenance."""

import hashlib
import json
import re
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from agenttinker.core.events import Event
from agenttinker.core.projection import RunView, project_events
from agenttinker.core.records import (
    SHA256,
    Artifact,
    Count,
    Identifier,
    Record,
    Text,
    ValueModel,
    VersionRef,
)
from agenttinker.core.states import TERMINAL_STATUSES
from agenttinker.experiments.evaluation import EvaluationResult, HumanReview
from agenttinker.experiments.models import (
    AgentDefinition,
    DatasetCase,
    Document,
    ExperimentDefinition,
    Variant,
)

MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_FILES = 128


def canonical(value) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class PackageRejected(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ExecutionCase(Record):
    ref: VersionRef
    task: Text
    fixture: VersionRef
    fixture_hash: SHA256
    expected_execution: Text


class Fixture(Record):
    ref: VersionRef
    documents: tuple[Document, ...]
    sha256: SHA256
    hash_method: Literal["legacy-document-list-v1", "document-case-v1"]

    @model_validator(mode="after")
    def content_matches_hash(self):
        if len({d.document_id for d in self.documents}) != len(self.documents):
            raise ValueError("duplicate_document")
        value = (
            [{"id": d.document_id, "title": d.title, "text": d.text} for d in self.documents]
            if self.hash_method == "legacy-document-list-v1"
            else {
                "fixture": self.ref.model_dump(),
                "documents": [d.model_dump() for d in self.documents],
            }
        )
        if hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() != self.sha256:
            raise ValueError("fixture_hash_mismatch")
        return self


class EvaluatorDefinition(Record):
    ref: VersionRef
    kind: Literal["rule", "human"]
    description: Text

    @model_validator(mode="after")
    def builtin_only(self):
        expected = {"document-evidence": "rule", "human-document-review": "human"}
        if self.ref.version != "1" or expected.get(self.ref.id) != self.kind:
            raise ValueError("unsupported_evaluator_definition")
        return self


class ExperimentContext(Record):
    experiment: ExperimentDefinition
    agent: AgentDefinition
    case: DatasetCase | ExecutionCase
    fixture: Fixture
    variants: tuple[Variant, ...]
    evaluators: tuple[EvaluatorDefinition, ...] = ()
    notes: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def matching_context(self):
        variants = {v.ref.id: v for v in self.variants}
        if (
            self.experiment.agent != self.agent.ref
            or self.experiment.case != self.case.ref
            or self.case.fixture != self.fixture.ref
            or self.case.fixture_hash != self.fixture.sha256
            or len(variants) != len(self.variants)
            or variants.get(self.experiment.baseline.ref.id) != self.experiment.baseline
            or variants.get(self.experiment.candidate.ref.id) != self.experiment.candidate
            or len({e.ref.id for e in self.evaluators}) != len(self.evaluators)
        ):
            raise ValueError("package_context_mismatch")
        return self


class RecordSource(ValueModel):
    run_id: Identifier
    mode: Literal["live", "recorded", "synthetic", "imported"]
    view_sha256: SHA256
    claim: Literal["unverified_source_record"] = "unverified_source_record"


class EvaluationBinding(ValueModel):
    evaluation_id: Identifier
    source_input_hash: SHA256
    portable_input_hash: SHA256


class PortableRun(Record):
    source: RecordSource
    view: RunView
    events: tuple[Event, ...] | None = Field(default=None, max_length=5000)
    evaluations: tuple[EvaluationResult, ...] = Field(default=(), max_length=1000)
    reviews: tuple[HumanReview, ...] = Field(default=(), max_length=1000)
    evaluation_bindings: tuple[EvaluationBinding, ...] = ()

    @model_validator(mode="after")
    def valid_observations(self):
        if self.source.run_id != self.view.run.run_id or self.source.mode != self.view.run.mode:
            raise ValueError("package_source_mismatch")
        if self.events is not None and (
            self.view.run.status not in TERMINAL_STATUSES
            or project_events(self.events) != self.view
        ):
            raise ValueError("package_projection_mismatch")
        if len({s.span_id for s in self.view.spans}) != len(self.view.spans):
            raise ValueError("duplicate_span")
        evaluations = {e.evaluation_id: e for e in self.evaluations}
        bindings = {b.evaluation_id: b for b in self.evaluation_bindings}
        if (
            len(evaluations) != len(self.evaluations)
            or set(bindings) != set(evaluations)
            or len(bindings) != len(self.evaluation_bindings)
            or len({r.review_id for r in self.reviews}) != len(self.reviews)
        ):
            raise ValueError("package_assessment_identity_mismatch")
        for result in self.evaluations:
            if (
                result.run_id != self.source.run_id
                or result.input_hash != bindings[result.evaluation_id].source_input_hash
            ):
                raise ValueError("package_evaluation_binding_mismatch")
        for review in self.reviews:
            evaluation = evaluations.get(review.evaluation_id)
            if (
                review.run_id != self.source.run_id
                or evaluation is None
                or review.input_hash != evaluation.input_hash
            ):
                raise ValueError("package_review_binding_mismatch")
        return self


class PortableArtifact(Record):
    metadata: Artifact
    content: str

    @model_validator(mode="after")
    def distributable_content(self):
        data = self.content.encode()
        if (
            not self.metadata.exportable
            or self.metadata.media_type not in {"application/json", "text/plain"}
            or self.metadata.size_bytes != len(data)
            or self.metadata.sha256 != hashlib.sha256(data).hexdigest()
        ):
            raise ValueError("artifact_not_portable")
        if self.metadata.media_type == "application/json":
            strict_json(data)
        return self


class ManifestEntry(ValueModel):
    path: Text
    sha256: SHA256
    size_bytes: Count = Field(le=MAX_ENTRY_BYTES)
    media_type: Literal["application/json"] = "application/json"

    @model_validator(mode="after")
    def known_data_path(self):
        if not re.fullmatch(
            r"context\.json|(?:runs|artifacts)/[A-Za-z0-9][A-Za-z0-9_.:-]*\.json", self.path
        ):
            raise ValueError("invalid_package_path")
        return self


class Manifest(ValueModel):
    title: Text
    source: Text
    license: Text | None = None
    created_at: AwareDatetime
    producer: VersionRef
    root_run_id: Identifier
    kind: Literal["experiment", "trace"]
    transformations: tuple[
        Literal["execution_disabled", "checkpoint_locators_removed", "credential_fields_redacted"],
        ...,
    ]
    private_checkpoint_state_included: Literal[False] = False
    entries: tuple[ManifestEntry, ...] = Field(min_length=1, max_length=MAX_FILES)


class ExperimentPackage(ValueModel):
    format: Literal["agenttinker-package"] = "agenttinker-package"
    format_version: Literal["1"] = "1"
    manifest: Manifest
    files: dict[str, JsonValue]

    @model_validator(mode="after")
    def files_match_manifest(self):
        paths = [entry.path for entry in self.manifest.entries]
        if len(set(paths)) != len(paths) or set(paths) != set(self.files):
            raise ValueError("package_entries_mismatch")
        for entry in self.manifest.entries:
            data = canonical(self.files[entry.path])
            if len(data) != entry.size_bytes or hashlib.sha256(data).hexdigest() != entry.sha256:
                raise ValueError("package_entry_hash_mismatch")
        if len(canonical(self)) > MAX_PACKAGE_BYTES:
            raise ValueError("package_too_large")
        return self


def strict_json(data: bytes):
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackageRejected("package_too_large")

    def object_values(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def non_finite(_value):
        raise ValueError("non_finite_json_number")

    return json.loads(data, object_pairs_hook=object_values, parse_constant=non_finite)
