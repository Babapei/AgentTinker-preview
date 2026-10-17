"""Record a bounded document case, then inspect/export its observations without execution."""

import hashlib
import sqlite3
from datetime import UTC, datetime

from agenttinker.core.events import parse_event
from agenttinker.core.projection import RunView, project_events
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    evaluate_documents,
)
from agenttinker.packages.context import context_for
from agenttinker.packages.exporting import make_package
from agenttinker.packages.models import EvaluationBinding, PortableRun, RecordSource, digest
from agenttinker.packages.portable import bind_evaluations, observation_events, observation_view
from agenttinker.runtime.checkpoints import checkpoint_path
from agenttinker.runtime.service import ForkRequest, RunService
from agenttinker.storage.evaluations import SQLiteEvaluationStore


def observations(view):
    models = [span for span in view.spans if span.kind == "model"]
    tokens = [span.usage.total_tokens for span in models]
    return {
        "new_model_calls": len(models),
        "new_tool_attempts": sum(span.kind == "tool" for span in view.spans),
        "new_total_tokens": sum(tokens) if tokens and all(t is not None for t in tokens) else None,
        "cost_kinds": [span.cost.kind for span in models],
        "actual_charge": None,
    }


def _checkpoint_rows(database, ids=None):
    with sqlite3.connect(checkpoint_path(database)) as connection:
        return {
            table: [
                row
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                if ids is None or row[2] in ids
            ]
            for table in ("checkpoints", "writes")
        }


def _row_hash(rows):
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _snapshot(database, view, report, name):
    with SQLiteEvaluationStore(database) as store:
        events = store.events(view.run.run_id)
        evaluation, _ = store.create_evaluation(
            view.run.run_id, EvaluationRequest(), f"reference-document:evaluation:{name}"
        )
    report["runs"][name] = view.model_dump(mode="json")
    report["events"][name] = [event.model_dump(mode="json") for event in events]
    report["evaluations"][name] = evaluation.model_dump(mode="json")
    report["measurements"][name] = observations(view)


def document_checks(report):
    """Recompute record consistency; this is not an authenticity or semantic judgement."""
    a, b = (RunView.model_validate(report["runs"][name]) for name in ("A", "B"))
    events = {
        name: tuple(parse_event(event) for event in report["events"][name]) for name in ("A", "B")
    }
    evaluations = {
        name: EvaluationResult.model_validate(report["evaluations"][name]) for name in ("A", "B")
    }
    models_a = [s for s in a.spans if s.kind == "model"]
    models_b = [s for s in b.spans if s.kind == "model"]
    searches_a = [s for s in a.spans if s.logical_node_id == "search_documents"]
    searches_b = [s for s in b.spans if s.logical_node_id == "search_documents"]
    prefix = tuple(s for s in a.spans if s.span_id in b.run.inherited_span_ids)
    rules_match = True
    for name, view, inherited in (("A", a, ()), ("B", b, prefix)):
        recomputed = evaluate_documents(view, inherited)
        rules_match &= recomputed.model_dump(
            exclude={"evaluation_id", "created_at"}
        ) == evaluations[name].model_dump(exclude={"evaluation_id", "created_at"})
    verdicts = {
        name: {check.check_id: check.verdict for check in result.checks}
        for name, result in evaluations.items()
    }
    models = [*models_a, *models_b]
    actual_modes = {a.run.mode, b.run.mode}
    live = report["mode"] == "live"
    return {
        "case_and_modes_match": actual_modes == {report["mode"]}
        and all(view.run.config.agent == corpus.AGENT for view in (a, b)),
        "both_executions_succeeded": a.run.status == b.run.status == "succeeded",
        "baseline_missing_material": verdicts["A"]["required_documents_returned"] == "fail"
        and "release-v2-fix" not in evaluations["A"].returned_document_ids,
        "candidate_material_returned_and_read": verdicts["B"]["required_documents_returned"]
        == verdicts["B"]["required_documents_read"]
        == "pass",
        "candidate_citations_reference_read_sources": verdicts["B"]["citation_sources_read"]
        == "pass",
        "single_policy_change": b.run.config.model_copy(
            update={"tool_policy": a.run.config.tool_policy, "variant": a.run.config.variant}
        )
        == a.run.config
        and a.run.config.tool_policy == {"tool_retry_limit": 0, "top_k": 2}
        and b.run.config.tool_policy == {"tool_retry_limit": 0, "top_k": 3}
        and a.run.config.variant == corpus.experiment_definition().baseline.ref
        and b.run.config.variant == corpus.experiment_definition().candidate.ref
        and b.run.intervention is not None
        and b.run.intervention.patch == {"top_k": 3},
        "lineage_and_prefix_not_recalled": bool(models_a and models_b)
        and b.run.parent_run_id == a.run.run_id
        and b.run.inherited_span_ids == (models_a[0].span_id,)
        and [s.call_index for s in models_b] == list(range(2, len(models_b) + 2))
        and not {s.span_id for s in a.spans} & {s.span_id for s in b.spans},
        "same_search_call_and_query": bool(searches_a and searches_b)
        and searches_a[0].input["tool_call"] == searches_b[0].input["tool_call"]
        and searches_a[0].logical_call_id == searches_b[0].logical_call_id,
        "bounded_serial_auto_tools": bool(models)
        and len(models_a) <= corpus.MAX_MODEL_CALLS
        and len(models_b) + 1 <= corpus.MAX_MODEL_CALLS
        and (not live or all(s.input.get("tool_choice") == "auto" for s in models)),
        "event_projections_match": project_events(events["A"]) == a
        and project_events(events["B"]) == b,
        "rule_evidence_recomputed": rules_match,
        "answer_semantics_remain_unreviewed": all(
            result.answer_review == "unreviewed" and not result.statistical_conclusion
            for result in evaluations.values()
        ),
        "measurements_match_new_spans": all(
            report["measurements"][name] == observations(view)
            for name, view in (("A", a), ("B", b))
        ),
        "provider_observations_retained": not live
        or all(
            s.provider == a.run.config.provider
            and s.usage.total_tokens is not None
            and s.output.get("response_id")
            and s.output.get("raw_response")
            and s.output.get("usage") == s.usage.raw
            for s in models
        ),
        "actual_charge_unknown": all(s.cost.kind == "unknown" for s in models),
    }


def capture_document(database, request, *, service_factory=RunService, timeout=270):
    report = {
        "schema_version": "m4-document-reference-1",
        "captured_at": datetime.now(UTC).isoformat(),
        "mode": request.mode,
        "runtime_state_included": False,
        "portable_execution": False,
        "real_reference_verified": False,
        "created_now": {"A": False, "B": False},
        "runs": {},
        "events": {},
        "evaluations": {},
        "measurements": {},
        "checks": {},
        "limitations": [
            "One case, shared prefix, no statistical or semantic conclusion.",
            "No human review is fabricated; rule results retain answer_review=unreviewed.",
            "No price book selected; actual provider charges remain unknown.",
            "Internal checks do not independently authenticate provider observations.",
            "Private runtime state is not included or portable.",
        ],
    }
    with service_factory(database) as service:
        created, fresh = service.submit_document(request, "reference-document:A")
        a = service.wait(created.run.run_id, timeout=timeout)
        report["created_now"]["A"] = fresh
    _snapshot(database, a, report, "A")
    references = [cp for cp in a.checkpoints if cp.allowed_patch_fields == ("top_k",)]
    report["checks"]["baseline_has_first_search_boundary"] = len(references) == 1
    if len(references) != 1:
        return report
    before = _checkpoint_rows(database)
    ids = {row[2] for row in before["checkpoints"]}
    with service_factory(database) as service:
        boundary = service.resolve_checkpoint(a.run.run_id, references[0].checkpoint_id)
        created, fresh = service.fork(
            a.run.run_id,
            ForkRequest(source_checkpoint_id=references[0].checkpoint_id, patch={"top_k": 3}),
            "reference-document:B",
        )
        b = service.wait(created.run.run_id, timeout=timeout)
        report["created_now"]["B"] = fresh
        a_after = service.get(a.run.run_id)
    _snapshot(database, b, report, "B")
    after = _checkpoint_rows(database, ids)
    with SQLiteEvaluationStore(database) as store:
        unchanged = a_after == a and tuple(
            e.model_dump(mode="json") for e in store.events(a.run.run_id)
        ) == tuple(report["events"]["A"])
    report["source_runtime_rows_sha256"] = {"before": _row_hash(before), "after": _row_hash(after)}
    report["checks"].update(
        restart_resolved_original_boundary=boundary.next == ("tool",),
        source_observations_unchanged=unchanged,
        source_checkpoint_rows_and_pending_writes_unchanged=before == after,
        **document_checks(report),
    )
    report["real_reference_verified"] = request.mode == "live" and all(report["checks"].values())
    return report


DOCUMENT_OUTCOME_CHECKS = {
    "both_executions_succeeded",
    "baseline_missing_material",
    "candidate_material_returned_and_read",
    "candidate_citations_reference_read_sources",
}


def package_reference(report, *, include_observed_failure=False):
    """Convert native reference facts; never read a saver, construct SDKs or rerun tools."""
    if report.get("schema_version") not in {"m3-reference-1", "m4-document-reference-1"}:
        raise ValueError("reference_version_unsupported")
    if set(report["runs"]) != {"A", "B"} or set(report["events"]) != {"A", "B"}:
        raise ValueError("reference_pair_incomplete")
    if not report.get("checks"):
        raise ValueError("reference_checks_failed")
    checked = dict(report["checks"])
    if report["schema_version"] == "m4-document-reference-1":
        recomputed = document_checks(report)
        if any(report["checks"].get(key) != value for key, value in recomputed.items()):
            raise ValueError("reference_checks_failed")
        checked.update(recomputed)
    allowed_failures = (
        DOCUMENT_OUTCOME_CHECKS
        if include_observed_failure and report["schema_version"] == "m4-document-reference-1"
        else set()
    )
    if any(not value for key, value in checked.items() if key not in allowed_failures):
        raise ValueError("reference_checks_failed")
    records = {}
    views = [RunView.model_validate(report["runs"][name]) for name in ("A", "B")]
    for name, view in zip(("A", "B"), views, strict=True):
        events = tuple(parse_event(event) for event in report["events"][name])
        if project_events(events) != view:
            raise ValueError("reference_projection_mismatch")
        evaluations = (
            (EvaluationResult.model_validate(report["evaluations"][name]),)
            if "evaluations" in report
            else ()
        )
        records[view.run.run_id] = PortableRun(
            source=RecordSource(
                run_id=view.run.run_id, mode=view.run.mode, view_sha256=digest(view)
            ),
            view=observation_view(view, playback=True),
            events=observation_events(events),
            evaluations=evaluations,
            evaluation_bindings=tuple(
                EvaluationBinding(
                    evaluation_id=e.evaluation_id,
                    source_input_hash=e.input_hash,
                    portable_input_hash="0" * 64,
                )
                for e in evaluations
            ),
        )
    for key, record in records.items():
        records[key] = record.model_copy(
            update={"evaluation_bindings": bind_evaluations(record, records)}
        )
    context = context_for(views)
    unmet = sorted(key for key, value in checked.items() if not value)
    if unmet:
        context = context.model_copy(
            update={
                "notes": (
                    *context.notes,
                    "录制的预期结果未全部满足，保留实际失败，不代表成功参考。未满足："
                    + ", ".join(unmet),
                )
            }
        )
    return make_package(
        {
            "context.json": context.model_dump(mode="json"),
            **{f"runs/{key}.json": value.model_dump(mode="json") for key, value in records.items()},
        },
        root_run_id=views[-1].run.run_id,
        title=context.experiment.title,
        source=(
            f"AgentTinker native reference observations ({report['schema_version']}); "
            "source claims remain unverified on import"
        ),
        created_at=datetime.fromisoformat(report["captured_at"]),
    )
