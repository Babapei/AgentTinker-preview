"""Deterministic evidence checks, deliberately separate from semantic review.

This module reads records only. It never executes a tool, invokes a model, changes
run status, or interprets a substring hit as proof of answer correctness.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from agenttinker.core.projection import RunView
from agenttinker.core.records import SHA256, Identifier, Record, Span, Text, ValueModel, VersionRef
from agenttinker.core.states import TERMINAL_STATUSES
from agenttinker.experiments import documents as corpus


class EvidenceCheck(Record):
    check_id: Identifier
    verdict: Literal["pass", "fail", "unknown"]
    explanation: Text
    span_ids: tuple[Identifier, ...]


class EvaluationResult(Record):
    evaluation_id: Identifier
    run_id: Identifier
    case: VersionRef
    evaluator: VersionRef
    input_hash: SHA256
    created_at: AwareDatetime
    execution_status: Text
    returned_document_ids: tuple[Identifier, ...]
    read_document_ids: tuple[Identifier, ...]
    cited_document_ids: tuple[Identifier, ...]
    checks: tuple[EvidenceCheck, ...]
    answer_review: Literal["unreviewed"] = "unreviewed"
    sample_size: Literal[1] = 1
    statistical_conclusion: Literal[False] = False
    status: Literal["completed", "failed"] = "completed"
    failure_code: Identifier | None = None

    @model_validator(mode="after")
    def failure_is_not_a_score(self):
        if self.status == "completed" and self.failure_code is not None:
            raise ValueError("completed_evaluation_has_failure")
        if self.status == "failed" and (
            self.failure_code is None
            or self.checks
            or self.returned_document_ids
            or self.read_document_ids
            or self.cited_document_ids
        ):
            raise ValueError("failed_evaluation_cannot_invent_checks")
        return self


class EvaluationRequest(ValueModel):
    evaluator: VersionRef = VersionRef(id="document-evidence", version="1")


class ReviewRequest(ValueModel):
    evaluation_id: Identifier
    input_hash: SHA256
    reviewer: Text = Field(max_length=160)
    fact_coverage: dict[Identifier, Literal["covered", "missing", "uncertain"]]
    judgement: Literal["supported", "justified_insufficiency", "unsupported", "uncertain"]
    explanation: Text = Field(max_length=8000)

    @model_validator(mode="after")
    def all_facts_explicit(self):
        if set(self.fact_coverage) != {
            fact.fact_id for fact in corpus.dataset_case().required_facts
        }:
            raise ValueError("review_fact_set_mismatch")
        return self


class HumanReview(Record):
    review_id: Identifier
    run_id: Identifier
    evaluation_id: Identifier
    input_hash: SHA256
    reviewer: Text
    created_at: AwareDatetime
    evaluator: VersionRef = VersionRef(id="human-document-review", version="1")
    fact_coverage: dict[Identifier, Literal["covered", "missing", "uncertain"]]
    judgement: Literal["supported", "justified_insufficiency", "unsupported", "uncertain"]
    explanation: Text

    @model_validator(mode="after")
    def all_facts_explicit(self):
        if set(self.fact_coverage) != {
            fact.fact_id for fact in corpus.dataset_case().required_facts
        }:
            raise ValueError("review_fact_set_mismatch")
        if self.evaluator != VersionRef(id="human-document-review", version="1"):
            raise ValueError("unsupported_human_evaluator")
        return self


def evidence_hash(view: RunView, inherited: tuple[Span, ...] = ()) -> str:
    payload = {
        "view": view.model_dump(mode="json"),
        "inherited": [span.model_dump(mode="json") for span in inherited],
        "case": corpus.dataset_case().model_dump(mode="json"),
        "evaluator": corpus.EVALUATOR.model_dump(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_document_context(view: RunView, inherited: tuple[Span, ...] = ()):
    # Snapshot/revalidate shallow-frozen nested values at the evidence boundary.
    view = RunView.model_validate_json(view.model_dump_json())
    inherited = tuple(Span.model_validate_json(span.model_dump_json()) for span in inherited)
    case, config = corpus.dataset_case(), view.run.config
    if (
        view.run.status not in TERMINAL_STATUSES
        or config.agent != corpus.AGENT
        or config.case != case.ref
        or config.experiment != corpus.EXPERIMENT
        or config.task != case.task
        or config.fixture_hash != case.fixture_hash
        or config.tool_versions != corpus.TOOL_VERSIONS
        or config.prompt_version != corpus.PROMPT_VERSION
        or config.evaluator_versions.get(corpus.EVALUATOR.id) != corpus.EVALUATOR.version
        or tuple(span.span_id for span in inherited) != view.run.inherited_span_ids
        or any(span.run_id == view.run.run_id for span in inherited)
    ):
        raise ValueError("evaluation_context_mismatch")
    return view, inherited


def evaluation_failure(view: RunView, inherited: tuple[Span, ...], failure_code: str):
    return EvaluationResult(
        evaluation_id=f"eval_{uuid4().hex}",
        run_id=view.run.run_id,
        case=corpus.dataset_case().ref,
        evaluator=corpus.EVALUATOR,
        input_hash=evidence_hash(view, inherited),
        created_at=datetime.now(UTC),
        execution_status=view.run.status,
        returned_document_ids=(),
        read_document_ids=(),
        cited_document_ids=(),
        checks=(),
        status="failed",
        failure_code=failure_code,
    )


def evaluate_documents(view: RunView, inherited: tuple[Span, ...] = ()) -> EvaluationResult:
    view, inherited = validate_document_context(view, inherited)
    case = corpus.dataset_case()
    spans = (*inherited, *view.spans)
    known = {doc.document_id: doc for doc in corpus.documents()}
    returned, read, evidence = set(), set(), []
    search_observed = False
    for span in spans:
        if span.kind != "tool" or span.status != "succeeded" or not span.output:
            continue
        if span.logical_node_id == "search_documents":
            search_observed = True
            found = span.output.get("documents", [])
            for doc in found if isinstance(found, list) else []:
                if isinstance(doc, dict) and isinstance(doc.get("id"), str) and doc["id"] in known:
                    returned.add(doc["id"])
            evidence.append(span.span_id)
        elif span.logical_node_id == "read_document":
            doc = span.output.get("document")
            if isinstance(doc, dict) and isinstance(doc.get("id"), str) and doc["id"] in returned:
                actual = known[doc["id"]]
                if doc == {"id": actual.document_id, "title": actual.title, "text": actual.text}:
                    read.add(doc["id"])
                    evidence.append(span.span_id)
    final = next(
        (
            span
            for span in reversed(spans)
            if span.kind == "model"
            and span.status == "succeeded"
            and span.output
            and span.output.get("choice_count") == 1
            and span.output.get("finish_reason") in {None, "stop"}
            and isinstance(span.output.get("message"), dict)
            and not span.output["message"].get("tool_calls")
            and isinstance(span.output["message"].get("content"), str)
            and span.output["message"]["content"].strip()
        ),
        None,
    )
    cited = (
        set(re.findall(r"\[([A-Za-z0-9][A-Za-z0-9_.:-]*)\]", final.output["message"]["content"]))
        if final
        else set()
    )
    required = set(case.required_document_ids)
    return EvaluationResult(
        evaluation_id=f"eval_{uuid4().hex}",
        run_id=view.run.run_id,
        case=case.ref,
        evaluator=corpus.EVALUATOR,
        input_hash=evidence_hash(view, inherited),
        created_at=datetime.now(UTC),
        execution_status=view.run.status,
        returned_document_ids=tuple(sorted(returned)),
        read_document_ids=tuple(sorted(read)),
        cited_document_ids=tuple(sorted(cited)),
        checks=(
            EvidenceCheck(
                check_id="required_documents_returned",
                verdict="pass"
                if required <= returned
                else "fail"
                if search_observed
                else "unknown",
                explanation="只检查固定必需文档的返回记录；缺失材料不等于回答编造。",
                span_ids=tuple(evidence),
            ),
            EvidenceCheck(
                check_id="required_documents_read",
                verdict="pass" if required <= read else "fail" if search_observed else "unknown",
                explanation="只检查可用文档正文的成功读取；不是事实语义评分。",
                span_ids=tuple(evidence),
            ),
            EvidenceCheck(
                check_id="citation_sources_read",
                verdict="unknown" if not cited else "pass" if cited <= read else "fail",
                explanation="只解析 [document-id] 并核对已读来源；不证明来源支持该句结论。",
                span_ids=(final.span_id,) if final else (),
            ),
        ),
    )
