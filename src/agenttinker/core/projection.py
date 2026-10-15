"""Rebuild native run views from facts; replay never invokes a provider or tool."""

from collections.abc import Iterable

from agenttinker.core.events import (
    CheckpointSaved,
    Event,
    RunCreated,
    RunStatusChanged,
    SpanFinished,
    SpanStarted,
    ToolAttemptFailed,
    ToolRetryScheduled,
    parse_event,
)
from agenttinker.core.records import CheckpointRef, PositiveCount, Record, Run, Span
from agenttinker.core.states import TERMINAL_STATUSES, RunStatus, can_start_call


class RunView(Record):
    run: Run
    last_seq: PositiveCount
    spans: tuple[Span, ...] = ()
    checkpoints: tuple[CheckpointRef, ...] = ()


def project_events(events: Iterable[Event]) -> RunView:
    run = None
    last_seq = 0
    event_ids = set()
    spans: dict[str, Span] = {}
    checkpoints: dict[str, CheckpointRef] = {}
    failures: dict[str, ToolAttemptFailed] = {}
    scheduled_retries: set[str] = set()
    for event in events:
        # Revalidate nested values too: Pydantic's frozen flag is shallow.
        event = parse_event(event.model_dump_json())
        if event.seq != last_seq + 1 or event.event_id in event_ids:
            raise ValueError("event_order_or_identity_conflict")
        if run is None:
            if not isinstance(event, RunCreated):
                raise ValueError("first_event_must_create_run")
            run = event.data
        else:
            if event.run_id != run.run_id:
                raise ValueError("event_run_mismatch")
            if isinstance(event, RunCreated):
                raise ValueError("run_already_created")
            if run.status in TERMINAL_STATUSES:
                raise ValueError("terminal_run_cannot_accept_execution_events")
            if isinstance(event, RunStatusChanged):
                if event.data.before != run.status:
                    raise ValueError("stale_run_status")
                if event.data.after in TERMINAL_STATUSES - {RunStatus.INTERRUPTED} and any(
                    span.status == "running" for span in spans.values()
                ):
                    raise ValueError("terminal_run_has_inflight_spans")
                if event.data.after == RunStatus.INTERRUPTED:
                    # No provider result is invented when a worker disappears.
                    spans = {
                        key: span.model_copy(update={"status": "interrupted"})
                        if span.status == "running"
                        else span
                        for key, span in spans.items()
                    }
                run = Run.model_validate({**run.model_dump(), "status": event.data.after})
            elif isinstance(event, SpanStarted):
                if not can_start_call(run.status):
                    raise ValueError("run_cannot_start_call")
                if event.span_id in spans or event.span_id in run.inherited_span_ids:
                    raise ValueError("span_already_exists")
                parent = event.data.parent_span_id
                if (
                    parent is not None
                    and parent not in spans
                    and parent not in run.inherited_span_ids
                ):
                    raise ValueError("span_parent_missing")
                if event.data.kind == "tool":
                    previous = [
                        span
                        for span in spans.values()
                        if span.kind == "tool"
                        and span.logical_call_id == event.data.logical_call_id
                    ]
                    if not previous:
                        if event.data.attempt != 1:
                            raise ValueError("tool_attempt_must_begin_at_one")
                    else:
                        prior = previous[-1]
                        if (
                            prior.span_id not in scheduled_retries
                            or event.data.attempt != prior.attempt + 1
                            or event.data.logical_node_id != prior.logical_node_id
                            or event.data.parent_span_id != prior.parent_span_id
                            or event.data.call_index != prior.call_index
                            or event.data.input != prior.input
                        ):
                            raise ValueError("tool_retry_lineage_mismatch")
                spans[event.span_id] = event.data
            elif isinstance(event, SpanFinished):
                original = spans.get(event.span_id)
                if original is None or original.status != "running":
                    raise ValueError("span_not_running")
                mutable = {"status", "ended_at", "duration_ms", "output", "model", "usage", "cost"}
                if original.model_dump(exclude=mutable) != event.data.model_dump(exclude=mutable):
                    raise ValueError("span_identity_or_input_changed")
                spans[event.span_id] = event.data
            elif isinstance(event, (ToolAttemptFailed, ToolRetryScheduled)):
                span = spans.get(event.span_id)
                if (
                    span is None
                    or span.kind != "tool"
                    or span.status != "failed"
                    or span.logical_call_id != event.logical_call_id
                    or span.attempt != event.attempt
                ):
                    raise ValueError("failed_tool_attempt_missing")
                if isinstance(event, ToolAttemptFailed):
                    if event.span_id in failures:
                        raise ValueError("tool_failure_already_recorded")
                    failures[event.span_id] = event
                else:
                    failure = failures.get(event.span_id)
                    if (
                        failure is None
                        or not failure.data.will_retry
                        or failure.data.retry_owner != "executor"
                        or event.span_id in scheduled_retries
                        or not can_start_call(run.status)
                    ):
                        raise ValueError("retry_not_allowed")
                    scheduled_retries.add(event.span_id)
            elif isinstance(event, CheckpointSaved):
                if run.status != RunStatus.RUNNING or event.data.checkpoint_id in checkpoints:
                    raise ValueError("checkpoint_not_allowed")
                checkpoints[event.data.checkpoint_id] = event.data
        run = Run.model_validate(
            {**run.model_dump(), "updated_at": max(run.updated_at, event.received_at)}
        )
        event_ids.add(event.event_id)
        last_seq = event.seq
    if run is None:
        raise ValueError("event_stream_empty")
    return RunView(
        run=run,
        last_seq=last_seq,
        spans=tuple(spans.values()),
        checkpoints=tuple(checkpoints.values()),
    )
