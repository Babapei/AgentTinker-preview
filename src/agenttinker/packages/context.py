"""Data definitions for the two built-in templates; no imported definitions execute."""

import hashlib

from agenttinker.core.records import VersionRef
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.models import AgentDefinition, Document, ExperimentDefinition, Variant
from agenttinker.m0.fixtures import DOCUMENTS, FIXTURE_VERSION, fixture_hash
from agenttinker.m0.models import ToolPolicy
from agenttinker.m0.openai_model import SEARCH_TOOL
from agenttinker.m0.probe import SYSTEM
from agenttinker.packages.models import (
    EvaluatorDefinition,
    ExecutionCase,
    ExperimentContext,
    Fixture,
    PackageRejected,
)


def context_for(views) -> ExperimentContext:
    config = views[-1].run.config
    if any(
        view.run.config.task != config.task
        or view.run.config.agent != config.agent
        or view.run.config.fixture_hash != config.fixture_hash
        for view in views
    ):
        raise PackageRejected("package_context_mismatch")
    if corpus.is_document_agent(config.agent):
        if corpus.document_version(config) is None:
            raise PackageRejected("package_context_mismatch")
        scenario = corpus.scenario(config.agent.version)
        if any(
            view.run.config.case != scenario.case.ref
            or view.run.config.task != scenario.case.task
            or view.run.config.fixture_hash != scenario.case.fixture_hash
            for view in views
        ):
            raise PackageRejected("package_context_mismatch")
        variants = {
            v.ref.id: v for v in (scenario.definition.baseline, scenario.definition.candidate)
        }
        for view in views:
            policy = ToolPolicy.model_validate(view.run.config.tool_policy)
            ref = VersionRef(id=f"document-top{policy.top_k}", version="1")
            if policy.tool_retry_limit != 0 or view.run.config.variant != ref:
                raise PackageRejected("package_context_mismatch")
            variants.setdefault(ref.id, Variant(ref=ref, role="candidate", policy=policy))
        return ExperimentContext(
            experiment=scenario.definition,
            agent=scenario.agent,
            case=scenario.case,
            fixture=Fixture(
                ref=scenario.case.fixture,
                documents=scenario.documents,
                sha256=scenario.case.fixture_hash,
                hash_method="document-case-v1",
            ),
            variants=tuple(variants.values()),
            evaluators=(
                EvaluatorDefinition(
                    ref=corpus.EVALUATOR,
                    kind="rule",
                    description="检查固定文档返回、正文读取和引用 ID，不评价自由文本语义。",
                ),
                EvaluatorDefinition(
                    ref=VersionRef(id="human-document-review", version="1"),
                    kind="human",
                    description="用户独立复核事实覆盖、诚实不足与无依据断言。",
                ),
            ),
        )
    if config.agent != VersionRef(id="serial-checkpoint", version="2") or not config.task:
        raise PackageRejected("package_context_unsupported")
    if any(
        view.run.config.fixture_hash != fixture_hash()
        or view.run.config.prompt_version != "single-tool-v1"
        or view.run.config.tool_versions != {"search_documents": "1"}
        for view in views
    ):
        raise PackageRejected("package_context_mismatch")
    case = ExecutionCase(
        ref=VersionRef(
            id=f"timeout-task-{hashlib.sha256(config.task.encode()).hexdigest()[:16]}", version="1"
        ),
        task=config.task,
        fixture=VersionRef(id=FIXTURE_VERSION, version="1"),
        fixture_hash=fixture_hash(),
        expected_execution=(
            "同一首次超时下，无重试会失败；增加一次执行器重试可取得材料。"
            "是否启用故障以 RunConfig 为准，答案质量另行判断。"
        ),
    )
    baseline = Variant(
        ref=VersionRef(id="timeout-r0-k2", version="1"),
        role="baseline",
        policy=ToolPolicy(tool_retry_limit=0, top_k=2),
    )
    candidate = Variant(
        ref=VersionRef(id="timeout-r1-k2", version="1"),
        role="candidate",
        policy=ToolPolicy(tool_retry_limit=1, top_k=2),
    )
    variants = {v.ref.id: v for v in (baseline, candidate)}
    for view in views:
        policy = ToolPolicy.model_validate(view.run.config.tool_policy)
        ref = VersionRef(id=f"timeout-r{policy.tool_retry_limit}-k{policy.top_k}", version="1")
        variants.setdefault(ref.id, Variant(ref=ref, role="candidate", policy=policy))
    return ExperimentContext(
        experiment=ExperimentDefinition(
            ref=VersionRef(id="tool-timeout", version="1"),
            title="工具超时以后发生了什么",
            description="单逻辑工具调用的有界串行模板，比较执行器策略；不是完整 ReAct。",
            success_criteria=(
                "保留相同首次故障和原查询/调用身份，从工具前分支仅修改一个因素。",
                "过程恢复与答案质量分开，继承前缀不重复计费。",
            ),
            agent=config.agent,
            case=case.ref,
            allowed_variables=("tool_retry_limit", "top_k"),
            baseline=baseline,
            candidate=candidate,
            source="AgentTinker built-in timeout experiment",
        ),
        agent=AgentDefinition(
            ref=config.agent,
            prompt_version="single-tool-v1",
            system_prompt=SYSTEM,
            tool_versions={"search_documents": "1"},
            tool_schemas={"search_documents": SEARCH_TOOL},
            max_model_calls=2,
        ),
        case=case,
        fixture=Fixture(
            ref=case.fixture,
            sha256=fixture_hash(),
            hash_method="legacy-document-list-v1",
            documents=tuple(
                Document(document_id=d["id"], title=d["title"], text=d["text"]) for d in DOCUMENTS
            ),
        ),
        variants=tuple(variants.values()),
        notes=(
            "旧 Run 没有 Case/Variant 引用时，以上定义由导出器根据冻结任务/策略生成；"
            "未补写源 Run。",
        ),
    )
