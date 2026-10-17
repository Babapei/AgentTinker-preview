"""Generate machine-readable schemas from the same Pydantic source as validation."""

from agenttinker.core.events import EVENT_ADAPTER
from agenttinker.core.projection import RunView
from agenttinker.core.records import Artifact, CheckpointRef, Intervention, Run, Span
from agenttinker.experiments.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    HumanReview,
    ReviewRequest,
)
from agenttinker.experiments.models import (
    AgentDefinition,
    DatasetCase,
    ExperimentDefinition,
    Scenario,
    Variant,
)
from agenttinker.packages.models import ExperimentPackage, ImportProvenance, ImportResult


def protocol_schemas() -> dict:
    return {
        **{
            model.__name__: model.model_json_schema()
            for model in (
                Run,
                Span,
                CheckpointRef,
                Artifact,
                Intervention,
                ExperimentDefinition,
                AgentDefinition,
                DatasetCase,
                Variant,
                Scenario,
                EvaluationResult,
                HumanReview,
                EvaluationRequest,
                ReviewRequest,
                ExperimentPackage,
                ImportResult,
                ImportProvenance,
            )
        },
        "Event": EVENT_ADAPTER.json_schema(),
        "RunView": RunView.model_json_schema(),
    }
