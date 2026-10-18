"""Convert validated packages to OTLP JSON for local M5 observation, without execution."""

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
    parser.add_argument("--format", choices=("json", "protobuf"), default="json")
    args = parser.parse_args()
    try:
        if args.output.resolve() in {path.resolve() for path in args.package}:
            raise ValueError("output_must_differ_from_source")
        packages = [parse_package(path.read_bytes()) for path in args.package]
        payload = make_otlp(packages)
        data = encode_otlp(payload, args.format)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=args.output.parent, delete=False) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        temporary.replace(args.output)
    except Exception as error:
        print(json.dumps({"converted": False, "error_code": type(error).__name__}))
        return 1
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    print(
        json.dumps(
            {"converted": True, "derived_spans": len(spans), "source_packages": len(packages)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
