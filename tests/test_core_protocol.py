import json
from datetime import timedelta
from itertools import product

import pytest
from pydantic import ValidationError

from agenttinker.core.events import parse_event
from agenttinker.core.projection import project_events
from agenttinker.core.records import (
    Capabilities,
    CheckpointRef,
    Cost,
    Intervention,
    Run,
    Span,
    Usage,
)
from agenttinker.core.schema import protocol_schemas
from agenttinker.core.states import RunStatus, can_start_call, validate_transition


def test_run_transition_matrix_and_terminal_immutability():
    expected = {
        "queued": {"running", "cancel_requested", "failed", "interrupted"},
        "running": {"cancel_requested", "succeeded", "failed", "interrupted"},
        "cancel_requested": {"cancelled", "failed", "interrupted"},
        "succeeded": set(),
        "failed": set(),
        "cancelled": set(),
        "interrupted": set(),
    }
    for before, after in product(RunStatus, repeat=2):
        if after in expected[before]:
            validate_transition(before, after)
        else:
            with pytest.raises(ValueError, match="invalid_run_transition"):
                validate_transition(before, after)
    assert [status for status in RunStatus if can_start_call(status)] == [RunStatus.RUNNING]


@pytest.mark.parametrize(
    "defect", [None, "multiple", "boolean", "same", "changed_other", "lineage"]
)
def test_intervention_survives_event_projection_and_rejects_invalid_changes(
    run_record, make_event, defect
):
    intervention = {
        "intervention_id": "intervention_B",
        "parent_run_id": "run_A",
        "source_checkpoint_id": "cp_A",
        "before": {"tool_retry_limit": 0, "top_k": 2},
        "after": {"tool_retry_limit": 1, "top_k": 2},
        "patch": {"tool_retry_limit": 1},
    }
    if defect == "multiple":
        intervention["patch"]["top_k"] = 3
        intervention["after"]["top_k"] = 3
    elif defect == "boolean":
        intervention["patch"]["tool_retry_limit"] = True
    elif defect == "same":
        intervention["before"]["tool_retry_limit"] = 1
    elif defect == "changed_other":
        intervention["after"]["top_k"] = 3
    branch = {
        **run_record.model_dump(),
        "run_id": "run_B",
        "parent_run_id": "run_A",
        "source_checkpoint_id": "cp_A",
        "intervention": intervention,
        "config": {**run_record.config.model_dump(), "tool_policy": intervention["after"]},
    }
    if defect == "lineage":
        branch["source_checkpoint_id"] = "another_checkpoint"
    if defect:
        with pytest.raises(ValidationError):
            Run.model_validate(branch)
    else:
        run = Run.model_validate(branch)
        event = make_event(1, "run.created", run, run_id="run_B")
        assert project_events(
            [parse_event(event.model_dump_json())]
        ).run.intervention == Intervention.model_validate(intervention)


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_version": "future"},
        {"run_id": " "},
        {"parent_run_id": "run_A", "source_checkpoint_id": "cp_A"},
        {"parent_run_id": "run_other"},
        {"inherited_span_ids": ["s1"]},
        {
            "parent_run_id": "run_other",
            "source_checkpoint_id": "cp_A",
            "inherited_span_ids": ["s1", "s1"],
        },
        {"created_at": "2026-10-15T00:00:00"},
        {"unexpected": "field"},
    ],
)
def test_invalid_run_records_are_rejected(run_record, patch):
    with pytest.raises(ValidationError):
        Run.model_validate({**run_record.model_dump(), **patch})


def test_imported_record_cannot_claim_execution_capability(run_record):
    payload = {**run_record.model_dump(), "mode": "imported"}
    assert not Run.model_validate(payload).capabilities.fork_from_checkpoint
    payload["capabilities"] = Capabilities(run_from_start=True, fork_from_checkpoint=True)
    with pytest.raises(ValidationError, match="imported_record_cannot_execute"):
        Run.model_validate(payload)
    with pytest.raises(ValidationError, match="patch_requires_fork"):
        Capabilities(patch_tool_policy=True)


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt_tokens": True},
        {"total_tokens": -1},
        {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 6},
        {"prompt_tokens": 2, "cached_input_tokens": 3},
        {"prompt_tokens": 3, "cached_input_tokens": 1, "uncached_input_tokens": 1},
    ],
)
def test_usage_rejects_inconsistent_or_coerced_counts(payload):
    with pytest.raises(ValidationError):
        Usage.model_validate(payload)


def test_unknown_measurements_and_traceable_decimal_cost():
    assert Usage().total_tokens is None
    assert Cost().amount is None
    estimate = Cost(kind="estimate", amount="0.00014640", currency="USD", price_version="price-1")
    assert json.loads(estimate.model_dump_json())["amount"] == "0.00014640"
    with pytest.raises(ValidationError, match="estimate_requires_price_version"):
        Cost(kind="estimate", amount="1", currency="USD")
    with pytest.raises(ValidationError, match="actual_cost_requires_evidence"):
        Cost(kind="actual", amount="1", currency="CNY")
    with pytest.raises(ValidationError, match="unknown_cost_cannot_have_amount"):
        Cost(amount="0")


def test_cancellation_retains_inflight_result_and_never_starts_another_call(run_record, make_event):
    span = Span(
        span_id="s_model",
        run_id="run_A",
        kind="model",
        logical_node_id="model",
        call_index=1,
        started_at=run_record.created_at,
    )
    log = [
        make_event(1, "run.created", run_record),
        make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
        make_event(3, "span.started", span, span_id=span.span_id),
        make_event(4, "run.status_changed", {"before": "running", "after": "cancel_requested"}),
    ]
    original = [event.model_dump_json() for event in log]
    view = project_events(log)
    assert view.run.status == "cancel_requested"
    assert view.spans[0].status == "running"
    late_result = span.model_copy(
        update={
            "status": "succeeded",
            "ended_at": span.started_at + timedelta(seconds=5),
            "usage": Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        }
    )
    log.extend(
        [
            make_event(5, "span.finished", late_result, span_id=span.span_id),
            make_event(
                6, "run.status_changed", {"before": "cancel_requested", "after": "cancelled"}
            ),
        ]
    )
    final = project_events(log)
    assert final.run.status == "cancelled"
    assert final.spans[0].usage.total_tokens == 12
    assert original == [event.model_dump_json() for event in log[:4]]
    assert project_events(log) == final  # Pure reconstruction, with no runtime or SDK.
    with pytest.raises(ValueError, match="run_cannot_start_call"):
        project_events(log[:4] + [make_event(5, "span.started", span, span_id=span.span_id)])
    with pytest.raises(ValueError, match="inflight_spans"):
        project_events(log[:4] + [log[-1].model_copy(update={"seq": 5})])


def test_interruption_does_not_invent_a_provider_result(run_record, make_event):
    span = Span(
        span_id="s_model",
        run_id="run_A",
        kind="model",
        logical_node_id="model",
        call_index=1,
        started_at=run_record.created_at,
    )
    view = project_events(
        [
            make_event(1, "run.created", run_record),
            make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
            make_event(3, "span.started", span, span_id=span.span_id),
            make_event(4, "run.status_changed", {"before": "running", "after": "interrupted"}),
        ]
    )
    assert view.run.status == "interrupted"
    assert view.spans[0].status == "interrupted"
    assert view.spans[0].ended_at is None
    assert view.spans[0].usage.total_tokens is None
    assert view.spans[0].cost.amount is None


@pytest.mark.parametrize("conflict", ["gap", "duplicate", "wrong_run", "stale_status", "after_end"])
def test_invalid_event_stream_cannot_change_projection(run_record, make_event, conflict):
    first = make_event(1, "run.created", run_record)
    change = make_event(2, "run.status_changed", {"before": "queued", "after": "running"})
    log = [first, change]
    if conflict == "gap":
        log[1] = change.model_copy(update={"seq": 3})
    elif conflict == "duplicate":
        log[1] = change.model_copy(update={"event_id": first.event_id})
    elif conflict == "wrong_run":
        log[1] = change.model_copy(update={"run_id": "other"})
    elif conflict == "stale_status":
        log.append(make_event(3, "run.status_changed", {"before": "queued", "after": "failed"}))
    else:
        log.append(make_event(3, "run.status_changed", {"before": "running", "after": "succeeded"}))
        log.append(make_event(4, "run.status_changed", {"before": "running", "after": "failed"}))
    with pytest.raises(ValueError):
        project_events(log)
    assert project_events([first]).run.status == "queued"


def test_fork_references_inherited_spans_without_copying_them(run_record, make_event):
    branch = Run.model_validate(
        {
            **run_record.model_dump(),
            "run_id": "run_B",
            "parent_run_id": "run_A",
            "source_checkpoint_id": "cp_A",
            "inherited_span_ids": ["s_A"],
        }
    )
    view = project_events([make_event(1, "run.created", branch, run_id="run_B")])
    assert view.run.inherited_span_ids == ("s_A",)
    assert view.spans == ()


def test_json_schema_and_event_json_round_trip(run_record, make_event):
    event = make_event(1, "run.created", run_record)
    assert parse_event(event.model_dump_json()) == event
    schemas = json.loads(json.dumps(protocol_schemas()))
    assert schemas["Event"]["discriminator"]["propertyName"] == "type"
    assert schemas["Run"]["properties"]["schema_version"]["const"] == "0.1"
    assert "additionalProperties" in schemas["Run"]
    with pytest.raises(ValidationError):
        parse_event({**event.model_dump(), "schema_version": "future"})
    with pytest.raises(ValidationError):
        parse_event({**event.model_dump(), "type": "made.up"})


@pytest.mark.parametrize("defect", [None, "not_scheduled", "wrong_attempt", "changed_input"])
def test_tool_retry_keeps_logical_call_and_attempt_lineage(run_record, make_event, defect):
    span = Span(
        span_id="s_tool_1",
        run_id="run_A",
        kind="tool",
        logical_node_id="search_documents",
        logical_call_id="search_1",
        attempt=1,
        call_index=1,
        started_at=run_record.created_at,
        input={"query": "release"},
    )
    failed = span.model_copy(
        update={
            "status": "failed",
            "ended_at": span.started_at + timedelta(seconds=1),
            "output": {"error_code": "TOOL_TIMEOUT", "origin": "injected"},
        }
    )
    log = [
        make_event(1, "run.created", run_record),
        make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
        make_event(3, "span.started", span, span_id=span.span_id),
        make_event(4, "span.finished", failed, span_id=span.span_id),
        make_event(
            5,
            "tool.attempt_failed",
            {
                "error_code": "TOOL_TIMEOUT",
                "origin": "injected",
                "retry_owner": "executor",
                "will_retry": True,
            },
            span_id=span.span_id,
            logical_call_id="search_1",
            attempt=1,
        ),
    ]
    if defect != "not_scheduled":
        log.append(
            make_event(
                6,
                "tool.retry_scheduled",
                {"next_attempt": 2},
                span_id=span.span_id,
                logical_call_id="search_1",
                attempt=1,
            )
        )
    retried = span.model_copy(
        update={
            "span_id": "s_tool_2",
            "attempt": 3 if defect == "wrong_attempt" else 2,
            "input": {"query": "changed"} if defect == "changed_input" else span.input,
        }
    )
    log.append(make_event(len(log) + 1, "span.started", retried, span_id=retried.span_id))
    if defect:
        with pytest.raises(ValueError, match="tool_retry_lineage_mismatch"):
            project_events(log)
    else:
        view = project_events(log)
        assert [(s.logical_call_id, s.attempt, s.status) for s in view.spans] == [
            ("search_1", 1, "failed"),
            ("search_1", 2, "running"),
        ]


def test_checkpoint_references_and_span_input_are_validated(run_record, make_event):
    checkpoint = CheckpointRef(
        checkpoint_id="cp_1",
        run_id="run_A",
        adapter="langgraph",
        runtime_version="1.2.14",
        agent_version="1",
        tool_versions={"search_documents": "1"},
        locator={"thread_id": "thread_1", "checkpoint_id": "native_cp_1"},
        allowed_patch_fields=("tool_retry_limit", "top_k"),
    )
    log = [
        make_event(1, "run.created", run_record),
        make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
        make_event(3, "checkpoint.saved", checkpoint),
    ]
    assert project_events(log).checkpoints == (checkpoint,)
    with pytest.raises(ValidationError, match="checkpoint_run_mismatch"):
        make_event(3, "checkpoint.saved", checkpoint, run_id="run_other")
    with pytest.raises(ValidationError):
        CheckpointRef.model_validate({**checkpoint.model_dump(), "allowed_patch_fields": ["query"]})
    with pytest.raises(ValidationError):
        Usage(raw={"invalid": float("nan")})
    with pytest.raises(ValidationError):
        make_event(True, "checkpoint.saved", checkpoint)


def test_finished_span_cannot_rewrite_input_or_terminate_twice(run_record, make_event):
    span = Span(
        span_id="s_model",
        run_id="run_A",
        kind="model",
        logical_node_id="model",
        call_index=1,
        started_at=run_record.created_at,
        input={"task": "original"},
    )
    log = [
        make_event(1, "run.created", run_record),
        make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
        make_event(3, "span.started", span, span_id=span.span_id),
    ]
    result = span.model_copy(update={"status": "succeeded", "ended_at": span.started_at})
    with pytest.raises(ValueError, match="span_identity_or_input_changed"):
        project_events(
            log
            + [
                make_event(
                    4,
                    "span.finished",
                    result.model_copy(update={"input": {"task": "changed"}}),
                    span_id=span.span_id,
                )
            ]
        )
    finish = make_event(4, "span.finished", result, span_id=span.span_id)
    with pytest.raises(ValueError, match="span_not_running"):
        project_events(log + [finish, finish.model_copy(update={"seq": 5, "event_id": "evt_5"})])


def test_clock_skew_does_not_replace_event_sequence_order(run_record, make_event):
    first = make_event(1, "run.created", run_record)
    second = make_event(
        2,
        "run.status_changed",
        {"before": "queued", "after": "running"},
        occurred_at=run_record.created_at - timedelta(days=1),
        received_at=run_record.created_at - timedelta(seconds=1),
    )
    view = project_events([first, second])
    assert view.run.status == "running"
    assert view.last_seq == 2
    assert view.run.updated_at == first.received_at
