"""Aggregate only newly observed calls; attach explicit, versioned cost estimates."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from agenttinker.m0.models import ProbeSpan


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent_total(self) -> "TokenUsage":
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("inconsistent_total_tokens")
        return self


Rate = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class ModelRates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_million: Rate
    output_per_million: Rate
    cached_input_per_million: Rate | None = None


class PriceBook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    version: str = Field(min_length=1)
    captured_at: date
    source: HttpUrl
    currency: Literal["USD"]
    rate_period: Literal["peak", "off_peak", "fixed"]
    models: dict[str, ModelRates] = Field(min_length=1)


def normalized_usage(raw: dict[str, Any] | None) -> dict[str, int | None]:
    if raw is None:
        raise ValueError("usage_missing")
    totals = TokenUsage.model_validate(raw).model_dump()
    details = raw.get("prompt_tokens_details")
    hits = [raw.get("prompt_cache_hit_tokens")]
    if details is not None:
        if not isinstance(details, dict):
            raise ValueError("invalid_cache_details")
        hits.append(details.get("cached_tokens"))
    hits = [n for n in hits if n is not None]
    misses = raw.get("prompt_cache_miss_tokens")
    for count in [*hits, *([] if misses is None else [misses])]:
        if type(count) is not int or not 0 <= count <= totals["prompt_tokens"]:
            raise ValueError("invalid_cache_count")
    if len(set(hits)) > 1:
        raise ValueError("inconsistent_cache_counts")
    cached = hits[0] if hits else None
    if misses is not None:
        if cached is not None and cached + misses != totals["prompt_tokens"]:
            raise ValueError("inconsistent_cache_counts")
        cached = totals["prompt_tokens"] - misses
    return {
        **totals,
        "cached_input_tokens": cached,
        "uncached_input_tokens": None if cached is None else totals["prompt_tokens"] - cached,
    }


def usage_summary(spans: list[ProbeSpan]) -> dict[str, Any]:
    calls = [s for s in spans if s.kind == "model"]
    usages = []
    unavailable = []
    for span in calls:
        try:
            usages.append(normalized_usage(span.usage))
        except ValueError:
            unavailable.append(span.span_id)
    complete = len(usages) == len(calls)
    summary = {
        "complete": complete,
        "coverage": {"recorded_calls": len(usages), "expected_calls": len(calls)},
        "unavailable_span_ids": unavailable,
    }
    for field in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
    ):
        known = complete and all(u[field] is not None for u in usages)
        summary[field] = sum(u[field] for u in usages) if known else None
    return summary


def cost_estimate(spans: list[ProbeSpan], pricing: PriceBook | None) -> dict[str, Any]:
    calls = [s for s in spans if s.kind == "model"]
    items = []
    unavailable = []
    for span in calls:
        reason = None
        amount = None
        model = span.output.get("model")
        if pricing is None:
            reason = "pricing_missing"
        elif span.output.get("provider") != pricing.provider:
            reason = "provider_mismatch"
        elif model not in pricing.models:
            reason = "model_price_missing"
        else:
            try:
                usage = normalized_usage(span.usage)
                rates = pricing.models[model]
                cached = usage["cached_input_tokens"]
                if rates.cached_input_per_million == rates.input_per_million:
                    input_cost = usage["prompt_tokens"] * rates.input_per_million
                elif cached is None:
                    raise ValueError("cached_usage_missing")
                elif cached > 0 and rates.cached_input_per_million is None:
                    raise ValueError("cached_price_missing")
                else:
                    input_cost = usage["uncached_input_tokens"] * rates.input_per_million
                    input_cost += cached * (rates.cached_input_per_million or Decimal(0))
                amount = (
                    input_cost + usage["completion_tokens"] * rates.output_per_million
                ) / Decimal(1_000_000)
            except (ValueError, ArithmeticError):
                reason = "usage_or_cache_price_unavailable"
        if amount is None:
            unavailable.append({"span_id": span.span_id, "reason": reason})
        else:
            items.append({"span_id": span.span_id, "model": model, "amount": str(amount)})
    complete = len(items) == len(calls) and pricing is not None
    return {
        "kind": "estimate" if complete else "unknown",
        "amount": str(sum((Decimal(item["amount"]) for item in items), Decimal(0)))
        if complete
        else None,
        "currency": pricing.currency if pricing else None,
        "price_version": pricing.version if pricing else None,
        "rate_period": pricing.rate_period if pricing else None,
        "complete": complete,
        "coverage": {"priced_calls": len(items), "expected_calls": len(calls)},
        "items": items,
        "unavailable": unavailable,
    }
