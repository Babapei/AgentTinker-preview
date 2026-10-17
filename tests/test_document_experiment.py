from datetime import UTC, datetime

import pytest

from agenttinker.core.projection import RunView
from agenttinker.core.records import Run, RunConfig, Span
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.evaluation import HumanReview, evaluate_documents
from agenttinker.experiments.models import ExperimentDefinition


def recorded_view(top_k=2, answer=None, status="succeeded"):
    now, spans = datetime.now(UTC), []
    found = corpus.search_documents("anything", top_k)
    for index, (tool, output) in enumerate(
        [("search_documents", {"documents": found})]
        + [
            ("read_document", {"document": corpus.read_document(doc["id"], (doc["id"],))})
            for doc in found
        ]
    ):
        spans.append(
            Span(
                span_id=f"span_{index}",
                run_id="A",
                kind="tool",
                logical_node_id=tool,
                logical_call_id=f"call_{index}",
                call_index=index + 1,
                attempt=1,
                started_at=now,
                ended_at=now,
                status="succeeded",
                output=output,
            )
        )
    if answer is not None:
        spans.append(
            Span(
                span_id="answer",
                run_id="A",
                kind="model",
                logical_node_id="model",
                call_index=1,
                started_at=now,
                ended_at=now,
                status="succeeded",
                output={"message": {"role": "assistant", "content": answer}, "choice_count": 1},
            )
        )
    return RunView(
        run=Run(
            run_id="A",
            mode="synthetic",
            status=status,
            created_at=now,
            updated_at=now,
            config=RunConfig(
                agent=corpus.AGENT,
                task=corpus.TASK,
                case=corpus.dataset_case().ref,
                experiment=corpus.EXPERIMENT,
                fixture_hash=corpus.fixture_hash(),
                tool_versions=corpus.TOOL_VERSIONS,
                prompt_version=corpus.PROMPT_VERSION,
                evaluator_versions={corpus.EVALUATOR.id: corpus.EVALUATOR.version},
            ),
        ),
        spans=tuple(spans),
        last_seq=1,
    )


def test_versions_fixed_ranking_metadata_and_read_only_allowlist():
    scenario = corpus.experiment_definition()
    case, agent = corpus.dataset_case(), corpus.agent_definition()
    assert scenario.agent == agent.ref and scenario.case == case.ref
    assert case.fixture_hash == corpus.fixture_hash()
    for query in ("release", "citations", "中文查询", "../anything"):
        a, b = corpus.search_documents(query, 2), corpus.search_documents(query, 3)
        assert b[:2] == a and b[2]["id"] == "release-v2-fix"
        assert all(set(doc) == {"id", "title"} for doc in b)
        with pytest.raises(ValueError, match="document_not_available"):
            corpus.read_document(b[2]["id"], tuple(doc["id"] for doc in a))
        assert "text" in corpus.read_document(b[2]["id"], tuple(doc["id"] for doc in b))
    # Mutating returned definitions/data cannot alter the registry or future calls.
    agent.tool_versions["read_document"] = "changed"
    assert corpus.agent_definition().tool_versions["read_document"] == "1"
    assert "text" not in corpus.search_documents("release", 3)[0]


@pytest.mark.parametrize("top_k", [0, 4, True, "2", 1.5])
def test_invalid_executor_policy_is_rejected(top_k):
    with pytest.raises(ValueError):
        corpus.search_documents("release", top_k)


def test_variants_reject_multiple_or_unapproved_changes():
    data = corpus.experiment_definition().model_dump()
    data["candidate"]["policy"]["tool_retry_limit"] = 1
    with pytest.raises(ValueError, match="invalid_experiment_variants"):
        ExperimentDefinition.model_validate(data)


def test_missing_material_and_honest_answer_are_not_automatically_fabrication():
    view = recorded_view(
        answer="Version 2 新增可配置重试 [release-v2]。材料不足，无法确认引用修复。"
    )
    original = view.model_dump_json()
    result = evaluate_documents(view)
    assert [check.verdict for check in result.checks] == ["fail", "fail", "pass"]
    assert result.answer_review == "unreviewed" and result.execution_status == "succeeded"
    assert result.sample_size == 1 and not result.statistical_conclusion
    assert view.model_dump_json() == original
    review = HumanReview(
        review_id="review_1",
        run_id="A",
        evaluation_id=result.evaluation_id,
        input_hash=result.input_hash,
        reviewer="local reviewer",
        created_at=datetime.now(UTC),
        fact_coverage={"configurable-retries": "covered", "citation-fix": "missing"},
        judgement="justified_insufficiency",
        explanation="人工确认回答明确指出缺失材料，未声称获得该事实。",
    )
    assert review.judgement == "justified_insufficiency"


def test_citations_do_not_prove_semantic_correctness_or_required_fact_coverage():
    # A deliberately wrong statement still has a known citation. No semantic pass is invented.
    result = evaluate_documents(recorded_view(3, "Version 2 移除了所有工具 [release-v2-fix]。"))
    assert [check.verdict for check in result.checks] == ["pass", "pass", "pass"]
    assert result.answer_review == "unreviewed"
    unknown = evaluate_documents(recorded_view(2, "修复了引用 [release-v2-fix] [invented]。"))
    assert unknown.checks[-1].verdict == "fail"
    assert unknown.cited_document_ids == ("invented", "release-v2-fix")


def test_cancelled_missing_answer_is_not_hidden_or_semantically_scored():
    view = recorded_view(status="cancelled")
    result = evaluate_documents(view)
    assert result.execution_status == "cancelled" and result.checks[-1].verdict == "unknown"
    assert result.answer_review == "unreviewed"
    changed = evaluate_documents(recorded_view(status="interrupted"))
    assert changed.input_hash != result.input_hash
    with pytest.raises(ValueError, match="evaluation_context_mismatch"):
        evaluate_documents(recorded_view(status="running"))
    mismatch = view.model_dump()
    mismatch["run"]["config"]["fixture_hash"] = "0" * 64
    with pytest.raises(ValueError, match="evaluation_context_mismatch"):
        evaluate_documents(RunView.model_validate(mismatch))
