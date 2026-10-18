"""Exercise native Agent Server state branching with the two synthetic M5 cases."""

import argparse
import json
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from graphs import ROOT, SOURCES, initial_state, run_config
from langgraph_sdk import get_sync_client

from agenttinker.core.projection import RunView
from agenttinker.core.records import Run, RunConfig, Span
from agenttinker.experiments.evaluation import evaluate_documents
from agenttinker.packages.models import digest


def execute(client, thread, case, **kwargs):
    events = list(client.runs.stream(thread, case, stream_mode=["updates", "custom"], **kwargs))
    spans = [
        Span.model_validate(event.data["data"])
        for event in events
        if event.event == "custom" and event.data.get("type") == "span.finished"
    ]
    errors = [event.data for event in events if event.event == "error"]
    return spans, errors


def evaluate(state, spans, *, inherited=(), parent=None, checkpoint=None):
    now = datetime.now(UTC)
    view = RunView(
        run=Run(
            run_id=state["run_id"],
            mode="synthetic",
            status="succeeded",
            config=RunConfig.model_validate(state["run_config"]),
            created_at=now,
            updated_at=now,
            parent_run_id=parent,
            source_checkpoint_id=checkpoint,
            inherited_span_ids=tuple(span.span_id for span in inherited),
        ),
        spans=tuple(spans),
        # Local cursor over completed Span observations, not a platform event seq.
        last_seq=len(spans),
    )
    return evaluate_documents(view, tuple(inherited)).model_dump(mode="json")


def check(base, output):
    if urlparse(base).hostname != "127.0.0.1":
        raise ValueError("local_comparison_only")
    client = get_sync_client(url=base)
    results, details = [], []
    originals = [(ROOT / "examples/m4" / name).read_bytes() for name in SOURCES.values()]
    for index, case in enumerate(SOURCES):
        assistant = client.assistants.search(graph_id=case)[0]
        edges = client.assistants.get_graph(assistant["assistant_id"])["edges"]
        pairs = {(edge["source"], edge["target"]) for edge in edges}
        assert {("model", "tool"), ("tool", "model"), ("model", "__end__")} <= pairs
        if case == "document":
            assert ("tool", "tool") in pairs
        thread = client.threads.create(metadata={"counts_as_user_session": False, "m5_case": case})[
            "thread_id"
        ]
        state = initial_state(case)
        baseline, errors = execute(client, thread, case, input=state)
        if case == "timeout":
            # The dev API deliberately masks exception messages. Inspect the
            # recorded tool output and persisted task, not the generic SSE text.
            assert [error["error"] for error in errors] == ["ExecutionFailed"]
            assert baseline[-1].output["error_code"] == "TOOL_TIMEOUT"
        else:
            assert errors == []
        a = client.threads.get_state(thread)
        if case == "timeout":
            assert any("TOOL_TIMEOUT" in (task.get("error") or "") for task in a["tasks"])
        history = client.threads.get_history(thread, limit=100)
        before = [
            client.threads.get_state(thread, checkpoint=item["checkpoint"]) for item in history
        ]
        boundaries = [
            item
            for item in history
            if item["next"] == ["tool"] and item["values"].get("tool_span_id") is None
        ]
        assert len(boundaries) == 1
        boundary = boundaries[0]
        assert boundary["values"]["model_span_id"] == baseline[0].span_id
        patch = {"tool_retry_limit": 1} if case == "timeout" else {"top_k": 3}
        policy = {**state["run_config"]["tool_policy"], **patch}
        branch = client.threads.update_state(
            thread,
            {
                "run_id": f"studio_{uuid4().hex}",
                "run_config": run_config(case, policy).model_dump(mode="json"),
            },
            as_node="model",
            checkpoint=boundary["checkpoint"],
        )
        candidate, errors = execute(
            client, thread, case, input=None, checkpoint=branch["checkpoint"]
        )
        assert errors == []
        b = client.threads.get_state(thread)
        assert b["next"] == []
        assert candidate[0].parent_span_id == baseline[0].span_id
        assert all(span.run_id == b["values"]["run_id"] for span in candidate)
        assert sum(span.kind == "model" for span in candidate) == (1 if case == "timeout" else 2)
        after = [
            client.threads.get_state(thread, checkpoint=item["checkpoint"]) for item in history
        ]
        assert before == after
        assert all(
            span.usage.total_tokens is None and span.cost.amount is None
            for span in (*baseline, *candidate)
        )
        rules = None
        if case == "timeout":
            assert [
                (span.status, (span.output or {}).get("error_code"))
                for span in candidate
                if span.kind == "tool"
            ] == [("failed", "TOOL_TIMEOUT"), ("succeeded", None)]
        else:
            rules = [
                evaluate(a["values"], baseline),
                evaluate(
                    b["values"],
                    candidate,
                    inherited=baseline[:1],
                    parent=a["values"]["run_id"],
                    checkpoint=boundary["checkpoint"]["checkpoint_id"],
                ),
            ]
            assert [[item["verdict"] for item in rule["checks"]] for rule in rules] == [
                ["fail", "fail", "pass"],
                ["pass", "pass", "pass"],
            ]
        result = {
            "case": case,
            "inspected_graph_edges": edges,
            "thread_id": thread,
            "baseline_checkpoint": a["checkpoint"],
            "branch_point": boundary["checkpoint"],
            "candidate_checkpoint": b["checkpoint"],
            "source_package_sha256": digest(json.loads(originals[index])),
            "agent": state["run_config"]["agent"],
            "fixture_hash": state["run_config"]["fixture_hash"],
            "execution_policy_patch": patch,
            "a_new_model_steps": sum(span.kind == "model" for span in baseline),
            "b_new_model_steps": sum(span.kind == "model" for span in candidate),
            "a_tool_attempts": sum(span.kind == "tool" for span in baseline),
            "b_tool_attempts": sum(span.kind == "tool" for span in candidate),
            "old_checkpoints_checked": len(before),
            "before_sha256": digest(before),
            "after_sha256": digest(after),
            "local_document_rule_verdicts": [
                [item["verdict"] for item in rule["checks"]] for rule in rules
            ]
            if rules
            else None,
        }
        results.append(result)
        details.append(
            {
                "result": result,
                "baseline": a,
                "candidate": b,
                "old_states": before,
                "source_spans": [span.model_dump(mode="json") for span in (*baseline, *candidate)],
                "local_rules": rules,
            }
        )
    assert originals == [(ROOT / "examples/m4" / name).read_bytes() for name in SOURCES.values()]
    proof = {
        "schema_version": "m5-studio-control-1",
        "checked_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "observer_kind": "assistant_api_check",
        "counts_as_user_session": False,
        "user_completion_rate": None,
        "user_elapsed_seconds": None,
        "mode": "synthetic",
        "tool": "LangGraph Agent Server development API",
        "cases": results,
        "new_provider_requests": 0,
        "local_document_rule_evaluations": 2,
        "human_reviews_created": 0,
        "limitations": [
            "Reuses production model/tool nodes and graph edges, "
            "with fixed synthetic drivers and a custom-stream journal bridge.",
            "Agent Server owns checkpoints and state edits; this is not RunService "
            "fork validation, an Intervention or a new platform adapter.",
            "Document rules were executed locally by the check script, "
            "not by a LangSmith evaluator or a human.",
            "Studio browser interaction is recorded separately; no user completion rate, "
            "cancellation or restart equivalence is claimed.",
            "Original live citation failure and unknown bills remain unchanged; "
            "synthetic success is not a replacement.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".state.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2) + "\n"
    )
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:12025")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/m5-studio-control.json")
    args = parser.parse_args()
    try:
        check(args.base_url, args.output)
    except Exception as error:
        (ROOT / "artifacts/m5-studio-control-failure.json").write_text(
            json.dumps(
                {
                    "error_code": type(error).__name__,
                    "frames": [
                        {"file": Path(frame.filename).name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)
                    ],
                }
            )
        )
        print(json.dumps({"passed": False, "error_code": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps({"passed": True, "cases": 2, "new_provider_requests": 0}))
