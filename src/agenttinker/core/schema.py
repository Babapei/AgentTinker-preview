"""Generate machine-readable schemas from the same Pydantic source as validation."""

from agenttinker.core.events import EVENT_ADAPTER
from agenttinker.core.projection import RunView
from agenttinker.core.records import Artifact, CheckpointRef, Intervention, Run, Span


def protocol_schemas() -> dict:
    return {
        **{
            model.__name__: model.model_json_schema()
            for model in (Run, Span, CheckpointRef, Artifact, Intervention)
        },
        "Event": EVENT_ADAPTER.json_schema(),
        "RunView": RunView.model_json_schema(),
    }
