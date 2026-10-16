"""M1 records: explicit versions, provenance, lineage, and unknown measurements."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from agenttinker.core.states import RunStatus

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Count = Annotated[int, Field(strict=True, ge=0)]
PositiveCount = Annotated[int, Field(strict=True, ge=1)]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
JSONData = dict[str, JsonValue]


class ValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Record(ValueModel):
    schema_version: Literal["0.1"] = "0.1"


class VersionRef(ValueModel):
    id: Identifier
    version: Text


class Capabilities(ValueModel):
    trace_view: bool = True
    record_playback: bool = True
    run_from_start: bool = False
    fork_from_checkpoint: bool = False
    patch_tool_policy: bool = False
    patch_arbitrary_state: Literal[False] = False
    pause_live_execution: Literal[False] = False
    parallel_fork: Literal[False] = False

    @model_validator(mode="after")
    def patch_requires_fork(self) -> "Capabilities":
        if self.patch_tool_policy and not self.fork_from_checkpoint:
            raise ValueError("patch_requires_fork_capability")
        return self


class RunConfig(ValueModel):
    agent: VersionRef
    task: Text | None = None
    tool_policy: JSONData = Field(default_factory=dict)
    price_version: Text | None = None
    experiment: VersionRef | None = None
    case: VersionRef | None = None
    variant: VersionRef | None = None
    provider: Text | None = None
    requested_model: Text | None = None
    model_parameters: JSONData = Field(default_factory=dict)
    prompt_version: Text | None = None
    tool_versions: dict[Identifier, Text] = Field(default_factory=dict)
    fixture_hash: SHA256 | None = None
    fault_plan: VersionRef | None = None
    fault_parameters: JSONData = Field(default_factory=dict)
    evaluator_versions: dict[Identifier, Text] = Field(default_factory=dict)
    runtime_versions: dict[Identifier, Text] = Field(default_factory=dict)


class Run(Record):
    run_id: Identifier
    mode: Literal["live", "recorded", "synthetic", "imported"]
    status: RunStatus = RunStatus.QUEUED
    config: RunConfig
    created_at: AwareDatetime
    updated_at: AwareDatetime
    capabilities: Capabilities = Field(default_factory=Capabilities)
    parent_run_id: Identifier | None = None
    source_checkpoint_id: Identifier | None = None
    inherited_span_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def valid_lineage(self) -> "Run":
        if (self.parent_run_id is None) != (self.source_checkpoint_id is None):
            raise ValueError("incomplete_fork_lineage")
        if self.parent_run_id == self.run_id:
            raise ValueError("run_cannot_parent_itself")
        if self.inherited_span_ids and self.parent_run_id is None:
            raise ValueError("inherited_spans_require_parent")
        if len(set(self.inherited_span_ids)) != len(self.inherited_span_ids):
            raise ValueError("duplicate_inherited_span")
        if self.updated_at < self.created_at:
            raise ValueError("updated_before_created")
        if self.mode == "imported" and (
            self.capabilities.run_from_start or self.capabilities.fork_from_checkpoint
        ):
            raise ValueError("imported_record_cannot_execute")
        return self


class Usage(ValueModel):
    prompt_tokens: Count | None = None
    completion_tokens: Count | None = None
    total_tokens: Count | None = None
    cached_input_tokens: Count | None = None
    uncached_input_tokens: Count | None = None
    raw: JSONData | None = None

    @model_validator(mode="after")
    def consistent_counts(self) -> "Usage":
        if (
            self.prompt_tokens is not None
            and self.completion_tokens is not None
            and self.total_tokens is not None
            and self.prompt_tokens + self.completion_tokens != self.total_tokens
        ):
            raise ValueError("inconsistent_total_tokens")
        if self.prompt_tokens is not None:
            for count in (self.cached_input_tokens, self.uncached_input_tokens):
                if count is not None and count > self.prompt_tokens:
                    raise ValueError("cache_count_exceeds_prompt")
            if (
                self.cached_input_tokens is not None
                and self.uncached_input_tokens is not None
                and self.cached_input_tokens + self.uncached_input_tokens != self.prompt_tokens
            ):
                raise ValueError("inconsistent_cache_counts")
        return self


class Cost(ValueModel):
    kind: Literal["unknown", "estimate", "actual"] = "unknown"
    amount: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    price_version: Text | None = None
    evidence_artifact_id: Identifier | None = None

    @model_validator(mode="after")
    def known_cost_has_source(self) -> "Cost":
        if self.kind == "unknown":
            if self.amount is not None:
                raise ValueError("unknown_cost_cannot_have_amount")
        elif self.amount is None or self.currency is None:
            raise ValueError("known_cost_requires_amount_and_currency")
        elif self.kind == "estimate" and self.price_version is None:
            raise ValueError("estimate_requires_price_version")
        elif self.kind == "actual" and self.evidence_artifact_id is None:
            raise ValueError("actual_cost_requires_evidence")
        return self


class Span(Record):
    span_id: Identifier
    run_id: Identifier
    kind: Literal["model", "tool", "evaluation"]
    logical_node_id: Identifier
    call_index: PositiveCount
    parent_span_id: Identifier | None = None
    logical_call_id: Identifier | None = None
    attempt: PositiveCount | None = None
    status: Literal["running", "succeeded", "failed", "cancelled", "interrupted"] = "running"
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    duration_ms: Annotated[float, Field(ge=0)] | None = None
    input: JSONData | None = None
    output: JSONData | None = None
    provider: Text | None = None
    model: Text | None = None
    usage: Usage = Field(default_factory=Usage)
    cost: Cost = Field(default_factory=Cost)

    @model_validator(mode="after")
    def valid_operation(self) -> "Span":
        if self.parent_span_id == self.span_id:
            raise ValueError("span_cannot_parent_itself")
        if self.kind == "tool" and (self.logical_call_id is None or self.attempt is None):
            raise ValueError("tool_attempt_requires_logical_call_and_attempt")
        if self.kind != "tool" and self.attempt is not None:
            raise ValueError("attempt_is_only_for_tools")
        if self.status == "running" and (self.ended_at is not None or self.duration_ms is not None):
            raise ValueError("running_span_cannot_have_end")
        if self.status not in {"running", "interrupted"} and self.ended_at is None:
            raise ValueError("finished_span_requires_end")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("span_ended_before_start")
        return self


class CheckpointRef(Record):
    checkpoint_id: Identifier
    run_id: Identifier
    adapter: Identifier
    runtime_version: Text
    agent_version: Text
    tool_versions: dict[Identifier, Text]
    boundary: Literal["before_tool"] = "before_tool"
    locator: JSONData
    allowed_patch_fields: tuple[Literal["tool_retry_limit", "top_k"], ...] = ()


class Artifact(Record):
    artifact_id: Identifier
    sha256: SHA256
    size_bytes: Count
    media_type: Text
    created_at: AwareDatetime
    source: Text
    exportable: bool = False
