"""Export browser wire contracts without opening storage or starting a runtime."""

import json

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

from agenttinker.api.app import RunPage, SpanPage
from agenttinker.core.events import Event
from agenttinker.core.projection import RunView
from agenttinker.experiments.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    HumanReview,
    ReviewRequest,
)
from agenttinker.experiments.models import Scenario
from agenttinker.packages.models import ImportProvenance, ImportResult
from agenttinker.runtime.service import (
    CheckpointAvailability,
    DocumentRunRequest,
    ForkRequest,
    RunRequest,
)
from agenttinker.storage.evaluations import EvaluationPage, ReviewPage


class ResponseSchema(GenerateJsonSchema):
    def field_is_required(self, field, total):
        # API responses serialize defaults too; omitted fields must not be mistaken
        # for an observed zero/empty result by the inspector.
        if self.mode == "serialization":
            return not field.get("serialization_exclude", False)
        return super().field_is_required(field, total)


class RuntimeProtocol(BaseModel):
    run_view: RunView
    run_page: RunPage
    span_page: SpanPage
    event: Event
    checkpoint_availability: tuple[CheckpointAvailability, ...]
    run_request: RunRequest
    fork_request: ForkRequest
    scenarios: tuple[Scenario, ...]
    document_run_request: DocumentRunRequest
    evaluation_request: EvaluationRequest
    review_request: ReviewRequest
    evaluation: EvaluationResult
    human_review: HumanReview
    evaluation_page: EvaluationPage
    review_page: ReviewPage
    import_result: ImportResult
    import_provenance: ImportProvenance | None


if __name__ == "__main__":
    # Decimal is a string on the wire; use serialization rather than input schema.
    print(
        json.dumps(
            RuntimeProtocol.model_json_schema(
                mode="serialization", schema_generator=ResponseSchema
            ),
            sort_keys=True,
        )
    )
