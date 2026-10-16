"""Capture one native timeout/fork reference; explicit live mode can incur provider fees."""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from agenttinker.core.projection import project_events
from agenttinker.runtime.checkpoints import checkpoint_path
from agenttinker.runtime.service import ForkRequest, RunRequest, RunService
from agenttinker.storage.sqlite import SQLiteEventStore


def facts(database, run_id):
    with SQLiteEventStore(database) as store:
        return store.events(run_id)


def checkpoint_rows(database, original_ids=None):
    with sqlite3.connect(checkpoint_path(database)) as connection:
        rows = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("checkpoints", "writes")
        }
    if original_ids is not None:
        rows = {
            table: [row for row in values if row[2] in original_ids]
            for table, values in rows.items()
        }
    return rows


def digest(value):
    return hashlib.sha256(repr(value).encode()).hexdigest()


def observations(view):
    models = [span for span in view.spans if span.kind == "model"]
    tools = [span for span in view.spans if span.kind == "tool"]
    tokens = [span.usage.total_tokens for span in models]
    return {
        "new_model_calls": len(models),
        "new_tool_attempts": len(tools),
        "new_total_tokens": sum(tokens) if all(value is not None for value in tokens) else None,
        "cost_kinds": [span.cost.kind for span in models],
        "actual_charge": None,
    }


def capture(database, request):
    with RunService(database) as service:
        created, fresh_a = service.submit(request, "reference-timeout:A")
        a = service.wait(created.run.run_id, timeout=45)
    a_events = facts(database, a.run.run_id)
    report = {
        "schema_version": "m3-reference-1",
        "captured_at": datetime.now(UTC).isoformat(),
        "mode": request.mode,
        "runtime_state_included": False,
        "portable_execution": False,
        "real_reference_verified": False,
        "created_now": {"A": fresh_a, "B": False},
        "checks": {},
        "runs": {"A": a.model_dump(mode="json")},
        "events": {"A": [event.model_dump(mode="json") for event in a_events]},
        "measurements": {"A": observations(a)},
        "limitations": [
            "Observations and runtime locators are included; private saver state is not.",
            "Actual charges remain unknown. No price book was selected; costs remain unknown.",
            "One bounded model/tool/model case; execution success is not answer evaluation.",
        ],
    }
    models_a = [span for span in a.spans if span.kind == "model"]
    tools_a = [span for span in a.spans if span.kind == "tool"]
    valid_a = (
        a.run.status == "failed"
        and len(a.checkpoints) == 1
        and len(models_a) == len(tools_a) == 1
        and tools_a[0].output == {"error_code": "TOOL_TIMEOUT", "origin": "injected"}
    )
    report["checks"]["expected_baseline_timeout"] = valid_a
    if not valid_a:
        return report
    before = checkpoint_rows(database)
    original_ids = {row[2] for row in before["checkpoints"]}
    with RunService(database) as service:
        boundary = service.resolve_checkpoint(a.run.run_id, a.checkpoints[0].checkpoint_id)
        available = service.checkpoint_availability(a.run.run_id)[0].available
        created, fresh_b = service.fork(
            a.run.run_id,
            ForkRequest(
                source_checkpoint_id=a.checkpoints[0].checkpoint_id, patch={"tool_retry_limit": 1}
            ),
            "reference-timeout:B",
        )
        b = service.wait(created.run.run_id, timeout=45)
        a_after = service.get(a.run.run_id)
    b_events = facts(database, b.run.run_id)
    after = checkpoint_rows(database, original_ids)
    models_b = [span for span in b.spans if span.kind == "model"]
    tools_b = [span for span in b.spans if span.kind == "tool"]
    checks = {
        **report["checks"],
        "restart_resolved_original_boundary": available
        and boundary.next == ("tool",)
        and boundary.values["tool_call"] == tools_a[0].input["tool_call"],
        "branch_succeeded": b.run.status == "succeeded",
        "source_observations_unchanged": a_after == a and facts(database, a.run.run_id) == a_events,
        "source_checkpoint_rows_and_pending_writes_unchanged": before == after,
        "single_policy_change": b.run.config.model_copy(
            update={"tool_policy": a.run.config.tool_policy}
        )
        == a.run.config
        and b.run.intervention.patch == {"tool_retry_limit": 1},
        "lineage_and_inheritance": b.run.parent_run_id == a.run.run_id
        and b.run.source_checkpoint_id == a.checkpoints[0].checkpoint_id
        and b.run.inherited_span_ids == (models_a[0].span_id,),
        "prefix_not_recalled": len(models_b) == 1 and models_b[0].call_index == 2,
        "same_call_and_first_fault": len(tools_b) == 2
        and all(span.input["tool_call"] == tools_a[0].input["tool_call"] for span in tools_b)
        and tools_b[0].output == tools_a[0].output
        and tools_b[1].status == "succeeded",
        "event_projection_matches": project_events(a_events) == a and project_events(b_events) == b,
        "provider_usage_observed": request.mode == "synthetic"
        or all(span.usage.total_tokens is not None for span in [*models_a, *models_b]),
        "actual_charge_unknown": all(
            span.cost.kind == "unknown" for span in [*models_a, *models_b]
        ),
    }
    report.update(
        {
            "checks": checks,
            "real_reference_verified": request.mode == "live" and all(checks.values()),
            "created_now": {"A": fresh_a, "B": fresh_b},
            "runs": {"A": a.model_dump(mode="json"), "B": b.model_dump(mode="json")},
            "events": {
                "A": [event.model_dump(mode="json") for event in a_events],
                "B": [event.model_dump(mode="json") for event in b_events],
            },
            "measurements": {"A": observations(a), "B": observations(b)},
            "source_runtime_rows_sha256": {"before": digest(before), "after": digest(after)},
        }
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("synthetic", "live"))
    parser.add_argument("--provider", choices=("deepseek", "openai"))
    parser.add_argument("--model")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = RunRequest(mode=args.mode, provider=args.provider, model=args.model)
    try:
        report = capture(args.database, request)
    except Exception as error:
        report = {
            "schema_version": "m3-reference-1",
            "mode": request.mode,
            "real_reference_verified": False,
            "checks": {"capture_completed": False},
            "error_code": type(error).__name__,
            "runs": {},
        }
        if args.database.exists():
            with SQLiteEventStore(args.database) as store:
                report["runs"] = {
                    key: store.get_view(key).model_dump(mode="json") for key in store.run_ids()
                }
    verified = all(report["checks"].values())
    output = args.output if verified else args.output.with_suffix(".failed.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    print(
        json.dumps(
            {
                "mode": request.mode,
                "verified": verified,
                "real_reference_verified": report["real_reference_verified"],
                "measurements": report.get("measurements"),
                "output": str(output),
            }
        )
    )
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
