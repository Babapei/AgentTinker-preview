"""Convert validated packages for local M5 observation, without model/tool execution."""

import argparse
import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from agenttinker.packages.models import digest
from agenttinker.packages.portable import inspect_package, parse_package


def identifier(namespace, kind, original, length):
    return hashlib.sha256(f"m5:{namespace}:{kind}:{original}".encode()).hexdigest()[:length]


def attributes(values):
    result = []
    for key, value in values.items():
        if value is None:
            continue
        field = (
            "boolValue"
            if type(value) is bool
            else "intValue"
            if type(value) is int
            else "stringValue"
        )
        result.append({"key": key, "value": {field: str(value) if field == "intValue" else value}})
    return result


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def nanos(value):
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return str((delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000)


def status(value):
    return {"code": 1 if value == "succeeded" else 2 if value == "failed" else 0}


def export_package(package):
    _, records, _ = inspect_package(package)
    namespace = digest(package)

    def trace(run_id):
        return identifier(namespace, "trace", run_id, 32)

    def span_id(original):
        return identifier(namespace, "span", original, 16)

    def root(run_id):
        return identifier(namespace, "root", run_id, 16)

    owners = {span.span_id: key for key, record in records.items() for span in record.view.spans}

    def link(original):
        return {"traceId": trace(owners[original]), "spanId": span_id(original)}

    spans = []
    for run_id, record in records.items():
        run = record.view.run
        models = [span for span in record.view.spans if span.kind == "model"]
        last_model = models[-1] if models else None
        message = (last_model.output or {}).get("message", {}) if last_model else {}
        answer = (
            message.get("content")
            if last_model
            and run.status == "succeeded"
            and last_model.status == "succeeded"
            and not message.get("tool_calls")
            else None
        )
        spans.append(
            {
                "traceId": trace(run_id),
                "spanId": root(run_id),
                "name": f"{run.config.agent.id}:{run.config.agent.version} / {run_id}",
                "kind": 1,
                "startTimeUnixNano": nanos(run.created_at),
                "endTimeUnixNano": nanos(run.updated_at),
                "status": status(run.status),
                "links": [link(original) for original in run.inherited_span_ids],
                "attributes": attributes(
                    {
                        "openinference.span.kind": "CHAIN",
                        "input.value": run.config.task,
                        "output.value": answer,
                        "agenttinker.source_run_id": run_id,
                        "agenttinker.source_status": run.status,
                        "agenttinker.source_mode": record.source.mode,
                        "agenttinker.source_claim": "unverified_source_record",
                        "agenttinker.package_sha256": namespace,
                        "agenttinker.parent_source_run_id": run.parent_run_id,
                        "agenttinker.inherited_source_span_ids": json_text(run.inherited_span_ids),
                        "agenttinker.source_checkpoint_id": run.source_checkpoint_id,
                        "agenttinker.source_intervention": (
                            json_text(run.intervention.model_dump(mode="json"))
                            if run.intervention
                            else None
                        ),
                        "agenttinker.derived_container": True,
                        "agenttinker.config": json_text(run.config.model_dump(mode="json")),
                        "agenttinker.source_evaluations": json_text(
                            [item.model_dump(mode="json") for item in record.evaluations]
                        ),
                        "agenttinker.source_reviews": json_text(
                            [item.model_dump(mode="json") for item in record.reviews]
                        ),
                        "agenttinker.billing": "see source_cost; collector estimates are not bills",
                    }
                ),
            }
        )
        for span in record.view.spans:
            if span.ended_at is None:
                raise ValueError("m5_otlp_requires_complete_span_timestamps")
            inherited_parent = span.parent_span_id in run.inherited_span_ids
            spans.append(
                {
                    "traceId": trace(run_id),
                    "spanId": span_id(span.span_id),
                    "parentSpanId": (
                        span_id(span.parent_span_id)
                        if span.parent_span_id and not inherited_parent
                        else root(run_id)
                    ),
                    "name": f"{span.logical_node_id} #{span.call_index}"
                    + (f" attempt {span.attempt}" if span.attempt is not None else ""),
                    "kind": 1,
                    "startTimeUnixNano": nanos(span.started_at),
                    "endTimeUnixNano": nanos(span.ended_at),
                    "status": status(span.status),
                    "links": [link(span.parent_span_id)] if inherited_parent else [],
                    "attributes": attributes(
                        {
                            "openinference.span.kind": {"model": "LLM", "tool": "TOOL"}.get(
                                span.kind, "CHAIN"
                            ),
                            "input.value": json_text(span.input),
                            "input.mime_type": "application/json",
                            "output.value": json_text(span.output),
                            "output.mime_type": "application/json",
                            "llm.model_name": span.model,
                            "llm.provider": span.provider,
                            "llm.token_count.prompt": span.usage.prompt_tokens,
                            "llm.token_count.completion": span.usage.completion_tokens,
                            "llm.token_count.total": span.usage.total_tokens,
                            "agenttinker.source_run_id": run_id,
                            "agenttinker.source_span_id": span.span_id,
                            "agenttinker.source_parent_span_id": span.parent_span_id,
                            "agenttinker.source_status": span.status,
                            "agenttinker.logical_call_id": span.logical_call_id,
                            "agenttinker.attempt": span.attempt,
                            "agenttinker.source_usage": json_text(
                                span.usage.model_dump(mode="json")
                            ),
                            "agenttinker.source_cost": json_text(span.cost.model_dump(mode="json")),
                            "agenttinker.package_sha256": namespace,
                        }
                    ),
                }
            )
    return spans


def make_otlp(packages):
    hashes = [digest(package) for package in packages]
    if len(set(hashes)) != len(hashes):
        raise ValueError("duplicate_package")
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": attributes(
                        {
                            "service.name": "agenttinker-m5-reference",
                            "openinference.project.name": "agenttinker-m5",
                        }
                    )
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agenttinker.m5.offline-conversion", "version": "1"},
                        "spans": [span for package in packages for span in export_package(package)],
                    }
                ],
            }
        ]
    }


def make_experiments(packages):
    """Map paired historical records to native Phoenix experiments, never rerun them."""
    if len({digest(package) for package in packages}) != len(packages):
        raise ValueError("duplicate_package")
    dataset = {
        "name": "agenttinker-m5-historical",
        "description": "Historical A/B pairs; imported records, no new Agent executions.",
        "inputs": [],
        "outputs": [],
        "metadata": [],
    }
    variants = [
        {
            "name": f"history-{name}",
            "description": "Imported source records. No new model/tool execution or human review.",
            "metadata": {
                "observation_kind": "imported_historical_record",
                "counts_as_user_session": False,
                "new_provider_requests": 0,
                "cross_case_average_is_quality_claim": False,
            },
            "runs": [],
        }
        for name in ("A", "B")
    ]
    for index, package in enumerate(packages):
        _, records, _ = inspect_package(package)
        namespace = digest(package)
        child = records[package.manifest.root_run_id]
        parent = records.get(child.view.run.parent_run_id)
        if len(records) != 2 or parent is None or parent.view.run.parent_run_id is not None:
            raise ValueError("m5_experiments_require_one_parent_child_pair")
        a, b = parent.view.run, child.view.run
        if (a.config.task, a.config.agent, a.config.fixture_hash) != (
            b.config.task,
            b.config.agent,
            b.config.fixture_hash,
        ):
            raise ValueError("m5_experiments_case_mismatch")
        dataset["inputs"].append(
            {
                "task": a.config.task,
                "agent": a.config.agent.model_dump(mode="json"),
                "fixture_hash": a.config.fixture_hash,
            }
        )
        # There is no human-reviewed gold answer in these packages.
        dataset["outputs"].append({})
        dataset["metadata"].append(
            {
                "source_package_sha256": namespace,
                "source_run_ids": [a.run_id, b.run_id],
                "observation_kind": "imported_historical_record",
                "gold_answer_available": False,
            }
        )
        roots = {
            item["spanId"]: {
                attribute["key"]: next(iter(attribute["value"].values()))
                for attribute in item["attributes"]
            }
            for item in export_package(package)
            if "parentSpanId" not in item
        }
        for variant, record in zip(variants, (parent, child), strict=True):
            run = record.view.run
            root = roots[identifier(namespace, "root", run.run_id, 16)]
            evaluations, names = [], set()
            for evaluation in record.evaluations:
                for check in evaluation.checks:
                    evaluator = evaluation.evaluator
                    name = f"source/{evaluator.id}:{evaluator.version}/{check.check_id}"
                    if name in names:
                        raise ValueError("m5_ambiguous_evaluation_snapshots")
                    names.add(name)
                    evaluations.append(
                        {
                            "name": name,
                            "annotator_kind": "CODE",
                            "start_time": evaluation.created_at.isoformat(),
                            "end_time": evaluation.created_at.isoformat(),
                            "result": {
                                "label": check.verdict,
                                "score": {"pass": 1, "fail": 0, "unknown": None}[check.verdict],
                                "explanation": check.explanation,
                            },
                            "metadata": {
                                "observation_kind": "copied_source_rule",
                                "source_package_sha256": namespace,
                                "source_evaluation_id": evaluation.evaluation_id,
                                "source_input_hash": evaluation.input_hash,
                                "source_span_ids": list(check.span_ids),
                                "answer_review": evaluation.answer_review,
                                "sample_size": evaluation.sample_size,
                                "statistical_conclusion": evaluation.statistical_conclusion,
                                "source_duration_seconds": None,
                                "adapter_interval_is_instant": True,
                            },
                        }
                    )
            variant["runs"].append(
                {
                    "case_index": index,
                    "request": {
                        "output": {
                            "observation_kind": "imported_historical_record",
                            "source_package_sha256": namespace,
                            "source_mode": record.source.mode,
                            "source_provenance": record.source.model_dump(mode="json"),
                            "source_view": record.view.model_dump(mode="json"),
                            "source_evaluation_bindings": [
                                item.model_dump(mode="json") for item in record.evaluation_bindings
                            ],
                            "source_evaluations": [
                                item.model_dump(mode="json") for item in record.evaluations
                            ],
                            "source_reviews": [
                                item.model_dump(mode="json") for item in record.reviews
                            ],
                            "final_answer": root.get("output.value"),
                        },
                        "repetition_number": 1,
                        "start_time": run.created_at.isoformat(),
                        "end_time": run.updated_at.isoformat(),
                        "trace_id": identifier(namespace, "trace", run.run_id, 32),
                        "error": None if run.status == "succeeded" else run.status,
                    },
                    "evaluations": evaluations,
                }
            )
    return {"schema_version": "m5-phoenix-experiments-1", "dataset": dataset, "variants": variants}


def encode_otlp(payload, wire_format):
    if wire_format == "json":
        return json_text(payload).encode()
    # Optional research dependency, supplied with uv --with, never by the application.
    from google.protobuf.json_format import ParseDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    def protobuf_ids(value):
        if isinstance(value, list):
            return [protobuf_ids(item) for item in value]
        if isinstance(value, dict):
            return {
                key: (
                    base64.b64encode(bytes.fromhex(item)).decode()
                    if key in {"traceId", "spanId", "parentSpanId"}
                    else protobuf_ids(item)
                )
                for key, item in value.items()
            }
        return value

    return ParseDict(protobuf_ids(payload), ExportTraceServiceRequest()).SerializeToString()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--format", choices=("json", "protobuf", "phoenix-experiments"), default="json"
    )
    args = parser.parse_args()
    try:
        if args.output.resolve() in {path.resolve() for path in args.package}:
            raise ValueError("output_must_differ_from_source")
        packages = [parse_package(path.read_bytes()) for path in args.package]
        payload = (
            make_experiments(packages)
            if args.format == "phoenix-experiments"
            else make_otlp(packages)
        )
        data = (
            json_text(payload).encode()
            if args.format == "phoenix-experiments"
            else encode_otlp(payload, args.format)
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=args.output.parent, delete=False) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        temporary.replace(args.output)
    except Exception as error:
        print(json.dumps({"converted": False, "error_code": type(error).__name__}))
        return 1
    if args.format == "phoenix-experiments":
        print(
            json.dumps(
                {
                    "converted": True,
                    "historical_runs": sum(len(item["runs"]) for item in payload["variants"]),
                    "source_packages": len(packages),
                }
            )
        )
        return 0
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    print(
        json.dumps(
            {"converted": True, "derived_spans": len(spans), "source_packages": len(packages)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
