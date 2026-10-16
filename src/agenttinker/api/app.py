"""HTTP reads and subscriptions never dispatch or restart a run."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from agenttinker.core.projection import RunView
from agenttinker.core.records import CheckpointRef, Count, Identifier, Run, Span, ValueModel
from agenttinker.core.schema import protocol_schemas
from agenttinker.core.states import TERMINAL_STATUSES, RunStatus
from agenttinker.m0.openai_model import ProviderNotConfigured
from agenttinker.runtime.checkpoints import ForkRejected
from agenttinker.runtime.service import CheckpointAvailability, ForkRequest, RunRequest, RunService
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore


class RunPage(ValueModel):
    items: tuple[Run, ...]
    total: Count
    next_offset: Count | None


class SpanPage(ValueModel):
    items: tuple[Span, ...]
    total: Count
    next_offset: Count | None


def read_events(database, run_id, cursor):
    with SQLiteEventStore(database) as store:
        return store.events(run_id, after_seq=cursor)


def read_view(database, run_id):
    with SQLiteEventStore(database) as store:
        return store.get_view(run_id)


def event_cursor(run_id: str, after_seq: int | None, last_event_id: str | None) -> int:
    cursor = after_seq or 0
    if last_event_id is not None:
        source, separator, sequence = last_event_id.rpartition(":")
        if not separator or source != run_id or not sequence.isascii() or not sequence.isdecimal():
            raise HTTPException(422, "invalid_event_cursor")
        resumed = int(sequence)
        if after_seq is not None and after_seq != resumed:
            raise HTTPException(422, "conflicting_event_cursors")
        cursor = resumed
    return cursor


async def stream_events(database, run_id, cursor, request, *, poll_interval, heartbeat_interval):
    last_activity = monotonic()
    while not await request.is_disconnected():
        events = await asyncio.to_thread(read_events, database, run_id, cursor)
        if events:
            for event in events:
                if await request.is_disconnected():
                    return
                yield (
                    f"id: {run_id}:{event.seq}\n"
                    f"event: {event.type}\n"
                    f"data: {event.model_dump_json()}\n\n"
                )
                cursor = event.seq
            last_activity = monotonic()
            continue
        view = await asyncio.to_thread(read_view, database, run_id)
        # A commit can land between the empty read and this status snapshot.
        if cursor < view.last_seq:
            continue
        if view.run.status in TERMINAL_STATUSES:
            return
        if monotonic() - last_activity >= heartbeat_interval:
            yield ": keep-alive\n\n"
            last_activity = monotonic()
        await asyncio.sleep(poll_interval)


def create_app(
    database: Path | str = "artifacts/runs.sqlite",
    *,
    service_factory=RunService,
    pricing=None,
    poll_interval: float = 0.1,
    heartbeat_interval: float = 15.0,
) -> FastAPI:
    if poll_interval <= 0 or heartbeat_interval <= 0:
        raise ValueError("positive_stream_intervals_required")

    @asynccontextmanager
    async def lifespan(app):
        service = await asyncio.to_thread(service_factory, database, pricing=pricing)
        app.state.service = service
        try:
            yield
        finally:
            await asyncio.to_thread(service.close)

    app = FastAPI(title="AgentTinker local runtime", version="0.0.1", lifespan=lifespan)

    @app.exception_handler(ProviderNotConfigured)
    async def missing_provider(_request, _error):
        return JSONResponse(status_code=503, content={"detail": "provider_not_configured"})

    @app.exception_handler(EventConflict)
    async def conflict(_request, _error):
        return JSONResponse(status_code=409, content={"detail": "idempotency_key_payload_conflict"})

    @app.exception_handler(ForkRejected)
    async def rejected_fork(_request, error):
        status = (
            422
            if error.code == "invalid_patch"
            else 404
            if error.code == "checkpoint_missing"
            else 409
        )
        return JSONResponse(status_code=status, content={"detail": error.code})

    @app.exception_handler(KeyError)
    async def missing_run(_request, _error):
        return JSONResponse(status_code=404, content={"detail": "run_not_found"})

    @app.exception_handler(ValueError)
    async def invalid_request(_request, _error):
        return JSONResponse(status_code=422, content={"detail": "invalid_request"})

    @app.exception_handler(RuntimeError)
    async def unavailable(_request, _error):
        return JSONResponse(status_code=503, content={"detail": "runtime_unavailable"})

    @app.get("/api/v1/protocol")
    def protocol():
        return protocol_schemas()

    @app.post("/api/v1/runs", response_model=RunView, status_code=201)
    def create_run(
        body: RunRequest,
        request: Request,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
    ):
        view, created = request.app.state.service.submit(body, idempotency_key)
        response.status_code = 201 if created else 200
        response.headers["Location"] = f"/api/v1/runs/{view.run.run_id}"
        return view

    @app.get("/api/v1/runs", response_model=RunPage)
    def list_runs(
        request: Request,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        with SQLiteEventStore(request.app.state.service.database) as store:
            ids = store.run_ids()
            items = tuple(store.get_view(key).run for key in ids[offset : offset + limit])
        next_offset = offset + len(items)
        return RunPage(
            items=items,
            total=len(ids),
            next_offset=next_offset if next_offset < len(ids) else None,
        )

    @app.get("/api/v1/runs/{run_id}", response_model=RunView)
    def get_run(run_id: Identifier, request: Request):
        return request.app.state.service.get(run_id)

    @app.get("/api/v1/runs/{run_id}/spans", response_model=SpanPage)
    def get_spans(
        run_id: Identifier,
        request: Request,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        logical_node_id: str | None = None,
        failed_only: bool = False,
    ):
        spans = tuple(
            span
            for span in request.app.state.service.get(run_id).spans
            if (logical_node_id is None or span.logical_node_id == logical_node_id)
            and (not failed_only or span.status == "failed")
        )
        items = spans[offset : offset + limit]
        next_offset = offset + len(items)
        return SpanPage(
            items=items,
            total=len(spans),
            next_offset=next_offset if next_offset < len(spans) else None,
        )

    @app.get("/api/v1/runs/{run_id}/checkpoints", response_model=tuple[CheckpointRef, ...])
    def get_checkpoints(run_id: Identifier, request: Request):
        return request.app.state.service.get(run_id).checkpoints

    @app.get(
        "/api/v1/runs/{run_id}/checkpoint-availability",
        response_model=tuple[CheckpointAvailability, ...],
    )
    def checkpoint_availability(run_id: Identifier, request: Request):
        return request.app.state.service.checkpoint_availability(run_id)

    @app.post("/api/v1/runs/{run_id}/forks", response_model=RunView, status_code=201)
    def fork_run(
        run_id: Identifier,
        body: ForkRequest,
        request: Request,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
    ):
        view, created = request.app.state.service.fork(run_id, body, idempotency_key)
        response.status_code = 201 if created else 200
        response.headers["Location"] = f"/api/v1/runs/{view.run.run_id}"
        return view

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=RunView)
    def cancel_run(run_id: Identifier, request: Request, response: Response):
        view = request.app.state.service.cancel(run_id)
        response.status_code = 202 if view.run.status == RunStatus.CANCEL_REQUESTED else 200
        return view

    @app.get(
        "/api/v1/runs/{run_id}/events",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
    )
    async def get_events(
        run_id: Identifier,
        request: Request,
        after_seq: Annotated[int | None, Query(ge=0)] = None,
        last_event_id: Annotated[str | None, Header(max_length=256)] = None,
    ):
        cursor = event_cursor(run_id, after_seq, last_event_id)
        database = request.app.state.service.database
        view = await asyncio.to_thread(read_view, database, run_id)
        if cursor > view.last_seq:
            raise HTTPException(422, "event_cursor_ahead")
        return StreamingResponse(
            stream_events(
                database,
                run_id,
                cursor,
                request,
                poll_interval=poll_interval,
                heartbeat_interval=heartbeat_interval,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
