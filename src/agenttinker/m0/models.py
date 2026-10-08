"""Small evidence models for checkpoint experiments."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tool_retry_limit: int = Field(default=0, ge=0, le=3)
    top_k: int = Field(default=2, ge=1, le=3)


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str | None = None
    message: dict[str, Any]
    usage: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    raw_response: dict[str, Any] | None = None


class ModelAdapter(Protocol):
    mode: Literal["synthetic", "live"]
    provider: str

    def complete(self, messages: list[dict[str, Any]]) -> ModelOutput: ...


class ProbeSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    span_id: str
    run_id: str
    kind: Literal["model", "tool"]
    parent_span_id: str | None = None
    logical_call_id: str | None = None
    attempt: int | None = None
    started_at: str
    duration_ms: float
    status: Literal["succeeded", "failed"]
    input: dict[str, Any]
    output: dict[str, Any]
    usage: dict[str, Any] | None = None
    cost: None = None
