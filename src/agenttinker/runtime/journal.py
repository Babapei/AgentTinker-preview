"""Persist call boundaries and results under the same lock as cancellation."""

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from agenttinker.core.records import Cost, Span, Usage
from agenttinker.core.states import RunStatus
from agenttinker.m0.accounting import PriceBook, cost_estimate, normalized_usage
from agenttinker.m0.models import ModelOutput, ProbeSpan
from agenttinker.storage.sqlite import SQLiteEventStore


class RunCancelled(Exception):
    pass


class ExecutionFailed(Exception):
    """Only a stable diagnostic code is propagated, never raw provider exceptions."""


class RunJournal:
    def __init__(self, database, run_id: str, lock: RLock, pricing: PriceBook | None):
        self.database, self.run_id, self.lock, self.pricing = database, run_id, lock, pricing

    def emit(self, event_type: str, data, **metadata):
        with self.lock, SQLiteEventStore(self.database) as store:
            return store.append_next(
                {
                    "event_id": f"evt_{uuid4().hex}",
                    "run_id": self.run_id,
                    "occurred_at": datetime.now(UTC),
                    "type": event_type,
                    "data": data,
                    **metadata,
                }
            )

    def require_running(self):
        with SQLiteEventStore(self.database) as store:
            if store.get_view(self.run_id).run.status != RunStatus.RUNNING:
                raise RunCancelled()

    def begin(self, **operation) -> Span:
        with self.lock:
            self.require_running()
            span = Span(
                span_id=f"span_{uuid4().hex}",
                run_id=self.run_id,
                started_at=datetime.now(UTC),
                **operation,
            )
            self.emit("span.started", span, span_id=span.span_id)
            return span

    def finish(
        self,
        span: Span,
        *,
        duration_ms: float,
        status: str,
        output: dict,
        reply: ModelOutput | None = None,
    ):
        usage, cost = Usage(), Cost()
        if reply is not None:
            try:
                usage = Usage(**normalized_usage(reply.usage), raw=reply.usage)
            except ValueError:
                usage = Usage(raw=reply.usage)
            observed = ProbeSpan(
                span_id=span.span_id,
                run_id=span.run_id,
                kind="model",
                started_at=span.started_at.isoformat(),
                duration_ms=duration_ms,
                status=status,
                input=span.input or {},
                output=reply.model_dump(),
                usage=reply.usage,
            )
            estimate = cost_estimate([observed], self.pricing)
            cost = Cost(
                kind=estimate["kind"],
                amount=estimate["amount"],
                currency=estimate["currency"],
                price_version=estimate["price_version"],
            )
        ended = Span.model_validate(
            {
                **span.model_dump(),
                "ended_at": datetime.now(UTC),
                "duration_ms": duration_ms,
                "status": status,
                "output": output,
                "usage": usage,
                "cost": cost,
                "model": reply.model if reply else span.model,
            }
        )
        self.emit("span.finished", ended, span_id=span.span_id)

    def tool_failure(self, span: Span, *, error_code: str, origin: str, retry_limit: int) -> bool:
        with self.lock, SQLiteEventStore(self.database) as store:
            retry = (
                store.get_view(self.run_id).run.status == RunStatus.RUNNING
                and span.attempt <= retry_limit
            )
            metadata = dict(
                span_id=span.span_id,
                logical_call_id=span.logical_call_id,
                logical_node_id=span.logical_node_id,
                attempt=span.attempt,
            )
            self.emit(
                "tool.attempt_failed",
                {
                    "error_code": error_code,
                    "origin": origin,
                    "retry_owner": "executor",
                    "will_retry": retry,
                    "fault_plan_id": "first-search-timeout" if origin == "injected" else None,
                },
                **metadata,
            )
            if retry:
                self.emit("tool.retry_scheduled", {"next_attempt": span.attempt + 1}, **metadata)
            return retry

    def checkpoint(self, reference):
        with self.lock:
            self.require_running()
            self.emit("checkpoint.saved", reference)
