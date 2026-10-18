"""M5 tool comparison converts observations, without duplicating inherited work."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from agenttinker.packages.models import canonical
from agenttinker.packages.portable import parse_package

SCRIPT = runpy.run_path("scripts/m5_export_otlp.py")


def values(span):
    return {item["key"]: next(iter(item["value"].values())) for item in span["attributes"]}


def test_same_real_cases_keep_failure_usage_causality_and_inherited_links_without_duplication():
    paths = [
        Path("examples/m4") / name for name in ["tool-timeout.json", "document-missing-v2.json"]
    ]
    originals = [path.read_bytes() for path in paths]
    packages = [parse_package(data) for data in originals]
    payload = SCRIPT["make_otlp"](packages)
    assert payload == SCRIPT["make_otlp"](packages)
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 22 and len({span["spanId"] for span in spans}) == 22
    roots = [span for span in spans if values(span).get("agenttinker.derived_container")]
    assert len(roots) == 4 and sorted(span["status"]["code"] for span in roots) == [1, 1, 1, 2]
    models = [span for span in spans if values(span)["openinference.span.kind"] == "LLM"]
    tools = [span for span in spans if values(span)["openinference.span.kind"] == "TOOL"]
    assert len(models) == 7 and len(tools) == 11
    assert sum(int(values(span)["llm.token_count.total"]) for span in models) == 5063
    assert all("llm.token_count.total" not in values(span) for span in roots + tools)
    indexed = {span["spanId"]: span for span in spans}
    for span in spans:
        assert int(span["endTimeUnixNano"]) >= int(span["startTimeUnixNano"])
        if "parentSpanId" in span:
            assert indexed[span["parentSpanId"]]["traceId"] == span["traceId"]
        for link in span["links"]:
            assert link["traceId"] == indexed[link["spanId"]]["traceId"]
            assert link["traceId"] != span["traceId"]
        attributes = values(span)
        if "agenttinker.source_cost" in attributes:
            cost = json.loads(attributes["agenttinker.source_cost"])
            assert cost["kind"] == "unknown" and cost["amount"] is None
    child = next(
        span
        for span in roots
        if values(span)["agenttinker.source_run_id"] == "run_b4955d8c41b54d18a6ad67c6a25cad20"
    )
    assert len(child["links"]) == 1
    assert len(json.loads(values(child)["agenttinker.inherited_source_span_ids"])) == 1
    assert json.loads(values(child)["agenttinker.source_intervention"])["patch"] == {"top_k": 3}
    assert "hrelease-v2" in values(child)["output.value"]
    evaluations = json.loads(values(child)["agenttinker.source_evaluations"])
    assert [check["verdict"] for check in evaluations[0]["checks"]] == ["pass", "pass", "fail"]
    assert evaluations[0]["answer_review"] == "unreviewed"
    assert json.loads(values(child)["agenttinker.source_reviews"]) == []
    assert [path.read_bytes() for path in paths] == originals
    assert [canonical(package) for package in packages] == [
        canonical(parse_package(data)) for data in originals
    ]


def test_legacy_protocol_failure_has_no_fabricated_answer_and_duplicate_sources_reject():
    package = parse_package(Path("examples/m4/document-missing.json").read_bytes())
    spans = SCRIPT["export_package"](package)
    root = next(
        span
        for span in spans
        if values(span)["agenttinker.source_run_id"] == package.manifest.root_run_id
        and values(span).get("agenttinker.derived_container")
    )
    assert root["status"]["code"] == 2 and "output.value" not in values(root)
    with pytest.raises(ValueError, match="duplicate_package"):
        SCRIPT["make_otlp"]([package, package])


def test_cli_rejects_tampered_input_and_source_alias_without_overwriting_either(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "source.json"
    source.write_bytes(Path("examples/m4/document-missing-v2.json").read_bytes())
    original = source.read_bytes()
    monkeypatch.setattr(
        sys, "argv", ["m5_export_otlp", "--package", str(source), "--output", str(source)]
    )
    assert SCRIPT["main"]() == 1 and source.read_bytes() == original
    bad = json.loads(original)
    bad["manifest"]["entries"][0]["sha256"] = "0" * 64
    source.write_text(json.dumps(bad))
    output = tmp_path / "output.json"
    output.write_text("keep existing observation")
    monkeypatch.setattr(
        sys, "argv", ["m5_export_otlp", "--package", str(source), "--output", str(output)]
    )
    assert SCRIPT["main"]() == 1 and output.read_text() == "keep existing observation"
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_native_experiments_keep_same_cases_failures_and_original_rule_provenance():
    paths = [
        Path("examples/m4") / name for name in ("tool-timeout.json", "document-missing-v2.json")
    ]
    originals = [path.read_bytes() for path in paths]
    packages = [parse_package(data) for data in originals]
    payload = SCRIPT["make_experiments"](packages)
    assert payload == SCRIPT["make_experiments"](packages)
    assert len(payload["dataset"]["inputs"]) == 2
    assert payload["dataset"]["outputs"] == [{}, {}]  # No invented gold answers.
    a, b = payload["variants"]
    assert [a["name"], b["name"]] == ["history-A", "history-B"]
    assert [run["case_index"] for run in a["runs"]] == [0, 1]
    traces = {
        span["traceId"]
        for span in SCRIPT["make_otlp"](packages)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    }
    models = []
    for variant in (a, b):
        assert variant["metadata"]["new_provider_requests"] == 0
        assert not variant["metadata"]["counts_as_user_session"]
        assert variant["runs"][0]["evaluations"] == []  # Absence isn't a passing score.
        for row in variant["runs"]:
            request = row["request"]
            assert request["trace_id"] in traces
            output = request["output"]
            assert output["source_reviews"] == []
            assert output["source_mode"] == "live"
            for span in output["source_view"]["spans"]:
                assert span["cost"]["amount"] is None and span["cost"]["kind"] == "unknown"
                if span["kind"] == "model":
                    models.append(span)
            source = output["source_evaluations"]
            for copied, check in zip(
                row["evaluations"], source[0]["checks"] if source else [], strict=True
            ):
                assert copied["annotator_kind"] == "CODE"
                assert copied["result"]["label"] == check["verdict"]
                assert copied["result"]["explanation"] == check["explanation"]
                assert copied["metadata"]["source_evaluation_id"] == source[0]["evaluation_id"]
                assert copied["metadata"]["source_input_hash"] == source[0]["input_hash"]
                assert copied["metadata"]["source_span_ids"] == check["span_ids"]
                assert copied["metadata"]["answer_review"] == "unreviewed"
                assert copied["metadata"]["source_duration_seconds"] is None
    assert len(models) == 7
    assert sum(span["usage"]["total_tokens"] for span in models) == 5063
    assert a["runs"][0]["request"]["error"] == "failed"
    assert a["runs"][0]["request"]["output"]["final_answer"] is None
    assert b["runs"][0]["request"]["error"] is None
    assert [item["result"]["score"] for item in a["runs"][1]["evaluations"]] == [0, 0, 1]
    assert [item["result"]["score"] for item in b["runs"][1]["evaluations"]] == [1, 1, 0]
    assert "hrelease-v2" in b["runs"][1]["request"]["output"]["final_answer"]
    assert [path.read_bytes() for path in paths] == originals


def test_unknown_source_rule_stays_unscored_and_ambiguous_snapshots_reject():
    from test_packages import resign

    data = json.loads(Path("examples/m4/document-missing-v2.json").read_bytes())
    record = data["files"][f"runs/{data['manifest']['root_run_id']}.json"]
    record["evaluations"][0]["checks"][0]["verdict"] = "unknown"
    payload = SCRIPT["make_experiments"]([parse_package(resign(data))])
    result = payload["variants"][1]["runs"][0]["evaluations"][0]["result"]
    assert result["label"] == "unknown" and result["score"] is None
    extra = {**record["evaluations"][0], "evaluation_id": "eval_second_snapshot"}
    record["evaluations"].append(extra)
    binding = {**record["evaluation_bindings"][0], "evaluation_id": extra["evaluation_id"]}
    record["evaluation_bindings"].append(binding)
    with pytest.raises(ValueError, match="m5_ambiguous_evaluation_snapshots"):
        SCRIPT["make_experiments"]([parse_package(resign(data))])


def test_native_experiments_reject_duplicate_input_and_single_unpaired_run():
    from test_packages import resign

    package = parse_package(Path("examples/m4/tool-timeout.json").read_bytes())
    with pytest.raises(ValueError, match="duplicate_package"):
        SCRIPT["make_experiments"]([package, package])
    data = json.loads(canonical(package))
    child = data["manifest"]["root_run_id"]
    parent = data["files"][f"runs/{child}.json"]["view"]["run"]["parent_run_id"]
    del data["files"][f"runs/{child}.json"]
    data["manifest"]["root_run_id"] = parent
    data["manifest"]["entries"] = [
        entry for entry in data["manifest"]["entries"] if entry["path"] != f"runs/{child}.json"
    ]
    with pytest.raises(ValueError, match="m5_experiments_require_one_parent_child_pair"):
        SCRIPT["make_experiments"]([parse_package(resign(data))])
