from pathlib import Path

import pytest
from pydantic import ValidationError

from agenttinker.m0.accounting import PriceBook, cost_estimate, normalized_usage, usage_summary
from agenttinker.m0.models import ProbeSpan

PRICING_PATH = Path(__file__).parents[1] / "examples/m0/pricing-deepseek-flash-peak.json"
PRICE = PriceBook.model_validate_json(PRICING_PATH.read_text())
USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 2,
    "total_tokens": 12,
    "prompt_cache_hit_tokens": 4,
    "prompt_cache_miss_tokens": 6,
    "prompt_tokens_details": {"cached_tokens": 4},
}


def span(identifier="s1", usage=None, model="deepseek-flash", provider="deepseek"):
    return ProbeSpan(
        span_id=identifier,
        run_id="run-A",
        kind="model",
        started_at="2026-10-08T00:00:00Z",
        duration_ms=1,
        status="succeeded",
        input={},
        output={"model": model, "provider": provider},
        usage=usage,
    )


def test_cache_hit_miss_and_token_totals_are_preserved():
    usage = normalized_usage(USAGE)
    assert usage["cached_input_tokens"] == 4
    assert usage["uncached_input_tokens"] == 6
    totals = usage_summary([span("s1", USAGE), span("s2", USAGE)])
    assert totals["complete"] is True
    assert totals["total_tokens"] == 24
    assert totals["cached_input_tokens"] == 8


def test_partial_usage_is_not_presented_as_a_complete_total_or_zero():
    totals = usage_summary([span("s1", USAGE), span("s2")])
    assert totals["coverage"] == {"recorded_calls": 1, "expected_calls": 2}
    assert totals["total_tokens"] is None
    assert totals["complete"] is False
    assert totals["unavailable_span_ids"] == ["s2"]


@pytest.mark.parametrize(
    "patch",
    [
        {"prompt_tokens": -1},
        {"total_tokens": 99},
        {"prompt_tokens": True},
        {"prompt_cache_hit_tokens": 11},
        {"prompt_cache_miss_tokens": 9},
        {"prompt_tokens_details": {"cached_tokens": 5}},
    ],
)
def test_inconsistent_provider_usage_cannot_produce_an_estimated_bill(patch):
    bad = {**USAGE, **patch}
    with pytest.raises(ValueError):
        normalized_usage(bad)
    assert cost_estimate([span(usage=bad)], PRICE)["amount"] is None


def test_cost_uses_cache_and_exact_versioned_decimal_rates():
    estimate = cost_estimate([span(usage=USAGE)], PRICE)
    assert estimate["amount"] == "0.000004224"
    assert estimate["kind"] == "estimate"
    assert estimate["price_version"] == PRICE.version
    assert estimate["rate_period"] == "peak"
    assert estimate["coverage"] == {"priced_calls": 1, "expected_calls": 1}


@pytest.mark.parametrize(
    "pricing,call",
    [
        (None, span(usage=USAGE)),
        (PRICE, span(usage=USAGE, model="unpriced-model")),
        (PRICE, span(usage=USAGE, provider="openai")),
        (PRICE, span()),
    ],
)
def test_missing_price_model_provider_or_usage_preserves_unknown(pricing, call):
    estimate = cost_estimate([call], pricing)
    assert estimate["amount"] is None
    assert estimate["kind"] == "unknown"
    assert estimate["coverage"]["priced_calls"] == 0


def test_known_partial_cost_is_not_reported_as_total_cost():
    estimate = cost_estimate([span("s1", USAGE), span("s2")], PRICE)
    assert estimate["amount"] is None
    assert estimate["coverage"] == {"priced_calls": 1, "expected_calls": 2}
    assert estimate["items"][0]["amount"] == "0.000004224"


def test_missing_cache_details_are_unknown_when_cache_prices_differ():
    raw = {k: USAGE[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    assert usage_summary([span(usage=raw)])["total_tokens"] == 12
    assert cost_estimate([span(usage=raw)], PRICE)["amount"] is None


@pytest.mark.parametrize("rate", ["-1", "NaN", "Infinity"])
def test_invalid_rate_is_rejected_before_any_model_call(rate):
    data = PRICE.model_dump(mode="json")
    data["models"]["deepseek-flash"]["input_per_million"] = rate
    with pytest.raises(ValidationError):
        PriceBook.model_validate(data)


def test_zero_new_calls_are_known_zero_without_hiding_missing_calls():
    assert usage_summary([])["total_tokens"] == 0
    assert cost_estimate([], PRICE)["amount"] == "0"
