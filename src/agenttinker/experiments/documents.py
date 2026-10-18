"""Fixed ranking makes the missing third document a controlled executor variable.

Search returns metadata. Only read_document exposes the body; neither tool touches
the network, filesystem paths, or the legacy M0 fixture implementation.
"""

import hashlib
import json
from copy import deepcopy

from agenttinker.core.records import VersionRef
from agenttinker.experiments.models import (
    AgentDefinition,
    DatasetCase,
    Document,
    ExperimentDefinition,
    FactRequirement,
    Scenario,
    Variant,
)
from agenttinker.m0.models import ToolPolicy

AGENT = VersionRef(id="document-react", version="1")
EXPERIMENT = VersionRef(id="document-missing", version="1")
FIXTURE = VersionRef(id="fictional-document-lab", version="1")
EVALUATOR = VersionRef(id="document-evidence", version="1")
PROMPT_VERSION = "document-react-v1"
TOOL_VERSIONS = {"search_documents": "2", "read_document": "1"}
MAX_MODEL_CALLS = 8
MAX_TOOL_CALLS = 7
SYSTEM = (
    "You investigate a fixed fictional release-note corpus. Use the read-only tools as needed. "
    "Search results are metadata, not document bodies. Read a document before using its facts. "
    "Search ranking is fixed; query text is recorded but does not change the ranking. "
    "The executor controls top_k; do not invent a top_k argument. "
    "Only read IDs returned by search. "
    "Answer using only bodies actually read, citing each source as [document-id]. "
    "If the returned material is insufficient, say which information is missing honestly. "
    "Make at most one tool call per response. Finish within seven tool calls."
)
AGENT_V2 = VersionRef(id="document-react", version="2")
EXPERIMENT_V2 = VersionRef(id="document-missing", version="2")
PROMPT_VERSION_V2 = "document-react-v2"
SYSTEM_V2 = SYSTEM.replace(
    "Make at most one tool call per response. Finish within seven tool calls.",
    "You may request multiple tools in one response; they execute serially in the given order. "
    "Finish within seven tool calls in total.",
)
TASK = (
    "根据虚构发布说明，说明 Version 2 新增的可配置能力，以及修复的引用问题。"
    "请先读取材料，为每项结论引用 [document-id]；如果材料不足，请明确说明。"
)


class DocumentAccessError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def documents() -> tuple[Document, ...]:
    # Construct fresh records: callers cannot alter subsequent experiments through nested data.
    return (
        Document(
            document_id="release-v1",
            title="Release v1",
            text="Version 1 supports document search.",
        ),
        Document(
            document_id="release-v2",
            title="Release v2",
            text="Version 2 adds configurable tool retries.",
        ),
        Document(
            document_id="release-v2-fix",
            title="Release v2 fixes",
            text="Version 2 fixes missing citations.",
        ),
    )


def fixture_hash() -> str:
    payload = {"fixture": FIXTURE.model_dump(), "documents": [d.model_dump() for d in documents()]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def search_documents(query: str, top_k: int) -> list[dict[str, str]]:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("invalid_query")
    ToolPolicy(top_k=top_k)  # Strict range/type validation, including bool rejection.
    return [{"id": doc.document_id, "title": doc.title} for doc in documents()[:top_k]]


def read_document(document_id: str, available_ids: tuple[str, ...]) -> dict[str, str]:
    if document_id not in available_ids:
        raise DocumentAccessError("document_not_available")
    for doc in documents():
        if doc.document_id == document_id:
            return {"id": doc.document_id, "title": doc.title, "text": doc.text}
    raise DocumentAccessError("document_not_found")


def tool_schemas() -> dict[str, dict]:
    def schema(name, description, key):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {key: {"type": "string"}},
                    "required": [key],
                    "additionalProperties": False,
                },
            },
        }

    return {
        "search_documents": schema(
            "search_documents", "Get metadata in fixed corpus order; executor sets top_k.", "query"
        ),
        "read_document": schema(
            "read_document", "Read the body of an ID previously returned by search.", "document_id"
        ),
    }


def is_document_agent(agent: VersionRef) -> bool:
    return agent in (AGENT, AGENT_V2)


def document_version(config) -> str | None:
    for agent, experiment, prompt in (
        (AGENT, EXPERIMENT, PROMPT_VERSION),
        (AGENT_V2, EXPERIMENT_V2, PROMPT_VERSION_V2),
    ):
        if (config.agent, config.experiment, config.prompt_version) == (agent, experiment, prompt):
            return agent.version
    return None


def agent_definition(version="1") -> AgentDefinition:
    if version not in {"1", "2"}:
        raise ValueError("unsupported_document_version")
    return AgentDefinition(
        ref=deepcopy(AGENT if version == "1" else AGENT_V2),
        prompt_version=PROMPT_VERSION if version == "1" else PROMPT_VERSION_V2,
        system_prompt=SYSTEM if version == "1" else SYSTEM_V2,
        tool_versions=deepcopy(TOOL_VERSIONS),
        tool_schemas=tool_schemas(),
        max_model_calls=MAX_MODEL_CALLS,
    )


def dataset_case() -> DatasetCase:
    return DatasetCase(
        ref=VersionRef(id="release-v2-evidence", version="1"),
        task=TASK,
        fixture=deepcopy(FIXTURE),
        fixture_hash=fixture_hash(),
        required_document_ids=("release-v2", "release-v2-fix"),
        required_facts=(
            FactRequirement(
                fact_id="configurable-retries",
                description="Version 2 新增可配置的工具重试。",
                document_ids=("release-v2",),
            ),
            FactRequirement(
                fact_id="citation-fix",
                description="Version 2 修复引用缺失问题。",
                document_ids=("release-v2-fix",),
            ),
        ),
    )


def experiment_definition(version="1") -> ExperimentDefinition:
    return ExperimentDefinition(
        ref=deepcopy(EXPERIMENT if version == "1" else EXPERIMENT_V2),
        title="没有检索到，还是没有正确使用",
        description="固定材料排序；top_k=2 缺少第三份材料，分支只改为 3。单次结果仅为个例。",
        success_criteria=(
            "区分必需文档返回、正文读取、引用来源与答案语义评价。",
            "缺少材料时诚实说明；事实覆盖和编造与否由人工复核，不能仅凭字符串判定。",
        ),
        agent=agent_definition(version).ref,
        case=dataset_case().ref,
        allowed_variables=("top_k",),
        baseline=Variant(
            ref=VersionRef(id="document-top2", version="1"),
            policy=ToolPolicy(tool_retry_limit=0, top_k=2),
            role="baseline",
        ),
        candidate=Variant(
            ref=VersionRef(id="document-top3", version="1"),
            policy=ToolPolicy(tool_retry_limit=0, top_k=3),
            role="candidate",
        ),
        source="AgentTinker built-in fictional teaching corpus; no external documents",
    )


def scenario(version="1") -> Scenario:
    return Scenario(
        definition=experiment_definition(version),
        agent=agent_definition(version),
        case=dataset_case(),
        documents=documents(),
    )
