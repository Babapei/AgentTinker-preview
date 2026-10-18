"""The research bridge must retain native executor behavior and old checkpoint values."""

import runpy
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_packages import finished_pair

from agenttinker.runtime.journal import ExecutionFailed
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunService

SCRIPT = runpy.run_path("scripts/m5_studio/graphs.py")


def consume(graph, state, config):
    finished, error = [], None
    try:
        for event in graph.stream(state, config, stream_mode="custom"):
            if event["type"] == "span.finished":
                finished.append(event["data"])
    except ExecutionFailed as failure:
        error = str(failure)
    return finished, error


@pytest.mark.parametrize("case", ["timeout", "document"])
def test_studio_nodes_match_native_pair_without_reexecuting_prefix_or_changing_old_states(
    tmp_path, case
):
    if case == "document":
        with RunService(tmp_path / "native.sqlite") as service:
            a, _ = service.submit_document(
                DocumentRunRequest(mode="synthetic", agent_version="2"), "a"
            )
            a = service.wait(a.run.run_id)
            b, _ = service.fork(
                a.run.run_id,
                ForkRequest(
                    source_checkpoint_id=a.checkpoints[0].checkpoint_id, patch={"top_k": 3}
                ),
                "b",
            )
            b = service.wait(b.run.run_id)
    else:
        a, b = finished_pair(tmp_path / "native.sqlite", document=False)
    graph = SCRIPT["make_graph"](case).builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "comparison"}}
    initial = SCRIPT["initial_state"](case, "studio_a")
    baseline, error = consume(graph, initial, config)
    assert error == ("tool_error:TOOL_TIMEOUT" if case == "timeout" else None)
    for actual, expected in zip(baseline, a.spans, strict=True):
        assert (actual["kind"], actual["status"], actual["output"]) == (
            expected.kind,
            expected.status,
            expected.output,
        )
    history = list(graph.get_state_history(config))
    old = [(item.config, deepcopy(item.values)) for item in history]
    boundary = next(
        item
        for item in history
        if item.next == ("tool",) and item.values.get("tool_span_id") is None
    )
    policy = {
        **initial["run_config"]["tool_policy"],
        **({"tool_retry_limit": 1} if case == "timeout" else {"top_k": 3}),
    }
    forked = graph.update_state(
        boundary.config,
        {
            "run_id": "studio_b",
            "run_config": SCRIPT["run_config"](case, policy).model_dump(mode="json"),
        },
        as_node="model",
    )
    candidate, error = consume(graph, None, forked)
    assert error is None
    for actual, expected in zip(candidate, b.spans, strict=True):
        assert (actual["kind"], actual["status"], actual["output"]) == (
            expected.kind,
            expected.status,
            expected.output,
        )
        assert actual["cost"]["amount"] is None and actual["usage"]["total_tokens"] is None
    assert all(graph.get_state(checkpoint).values == values for checkpoint, values in old)
    assert candidate[0]["parent_span_id"] == baseline[0]["span_id"]
    if case == "timeout":
        assert [span["status"] for span in candidate if span["kind"] == "tool"] == [
            "failed",
            "succeeded",
        ]
    else:
        assert graph.get_state(config).values["pending_calls"] == []
        assert graph.get_state(forked).next == ("tool",)


def test_studio_bridge_rejects_changed_provider_task_or_materials_before_model_construction(
    monkeypatch,
):
    def forbidden():
        pytest.fail("driver must not be constructed for changed configuration")

    monkeypatch.setitem(SCRIPT["Nodes"].executor.__globals__, "SyntheticModel", forbidden)
    for field, value in [
        ("provider", "deepseek"),
        ("task", "another task"),
        ("fixture_hash", "0" * 64),
    ]:
        state = SCRIPT["initial_state"]("timeout")
        state["run_config"][field] = value
        with pytest.raises(ValueError, match="studio_comparison_requires_frozen_synthetic_config"):
            SCRIPT["Nodes"]("timeout").executor(state)
