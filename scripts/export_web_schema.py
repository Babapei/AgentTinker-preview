"""Export browser wire contracts without opening storage or starting a runtime."""

import json

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

from agenttinker.api.app import RunPage, SpanPage
from agenttinker.core.events import Event
from agenttinker.core.projection import RunView


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
