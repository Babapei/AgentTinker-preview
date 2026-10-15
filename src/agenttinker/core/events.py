"""Typed, versioned event envelopes; order comes from seq, never timestamps."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from agenttinker.core.records import (
    CheckpointRef,
    Identifier,
    PositiveCount,
    Record,
    Run,
    Span,
    Text,
    ValueModel,
)
from agenttinker.core.states import RunStatus, validate_transition


class Envelope(Record):
    event_id: Identifier
    run_id: Identifier
    seq: PositiveCount
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    span_id: Identifier | None = None
    parent_span_id: Identifier | None = None
    logical_node_id: Identifier | None = None
    logical_call_id: Identifier | None = None
    attempt: PositiveCount | None = None


class RunCreated(Envelope):
    type: Literal["run.created"] = "run.created"
    data: Run

    @model_validator(mode="after")
    def valid_creation(self) -> "RunCreated":
        if self.seq != 1 or self.data.status != RunStatus.QUEUED:
            raise ValueError("run_must_begin_queued_at_seq_one")
        if self.data.run_id != self.run_id:
            raise ValueError("event_run_mismatch")
        return self


class StatusChange(ValueModel):
    before: RunStatus
    after: RunStatus
    reason: Text | None = None

    @model_validator(mode="after")
    def legal_transition(self) -> "StatusChange":
        validate_transition(self.before, self.after)
        return self


class RunStatusChanged(Envelope):
    type: Literal["run.status_changed"] = "run.status_changed"
    data: StatusChange


class SpanEvent(Envelope):
    span_id: Identifier
    data: Span

    @model_validator(mode="after")
    def matching_span(self) -> "SpanEvent":
        if self.run_id != self.data.run_id or self.span_id != self.data.span_id:
            raise ValueError("event_span_mismatch")
        for field in ("parent_span_id", "logical_node_id", "logical_call_id", "attempt"):
            value = getattr(self, field)
            if value is not None and value != getattr(self.data, field):
                raise ValueError("event_span_metadata_mismatch")
        return self


class SpanStarted(SpanEvent):
    type: Literal["span.started"] = "span.started"

    @model_validator(mode="after")
    def running(self) -> "SpanStarted":
        if self.data.status != "running":
            raise ValueError("span_started_requires_running")
        return self


class SpanFinished(SpanEvent):
    type: Literal["span.finished"] = "span.finished"

    @model_validator(mode="after")
    def finished(self) -> "SpanFinished":
        if self.data.status == "running":
            raise ValueError("span_finished_requires_terminal_status")
        return self


class ToolFailure(ValueModel):
    error_code: Text
    fault_plan_id: Identifier | None = None
    origin: Literal["injected", "tool", "provider", "executor"]
    retry_owner: Literal["executor", "agent"]
    will_retry: bool


class ToolAttemptFailed(Envelope):
    type: Literal["tool.attempt_failed"] = "tool.attempt_failed"
    span_id: Identifier
    logical_call_id: Identifier
    attempt: PositiveCount
    data: ToolFailure


class Retry(ValueModel):
    next_attempt: PositiveCount
    retry_owner: Literal["executor"] = "executor"


class ToolRetryScheduled(Envelope):
    type: Literal["tool.retry_scheduled"] = "tool.retry_scheduled"
    span_id: Identifier
    logical_call_id: Identifier
    attempt: PositiveCount
    data: Retry

    @model_validator(mode="after")
    def next_attempt(self) -> "ToolRetryScheduled":
        if self.data.next_attempt != self.attempt + 1:
            raise ValueError("retry_attempt_must_increment")
        return self


class CheckpointSaved(Envelope):
    type: Literal["checkpoint.saved"] = "checkpoint.saved"
    data: CheckpointRef

    @model_validator(mode="after")
    def matching_run(self) -> "CheckpointSaved":
        if self.data.run_id != self.run_id:
            raise ValueError("event_checkpoint_run_mismatch")
        return self


Event = Annotated[
    RunCreated
    | RunStatusChanged
    | SpanStarted
    | SpanFinished
    | ToolAttemptFailed
    | ToolRetryScheduled
    | CheckpointSaved,
    Field(discriminator="type"),
]
EVENT_ADAPTER = TypeAdapter(Event)


def parse_event(value: str | bytes | dict | Envelope) -> Event:
    if isinstance(value, (str, bytes)):
        return EVENT_ADAPTER.validate_json(value)
    return EVENT_ADAPTER.validate_python(value)
