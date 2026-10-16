"""One local owner dispatches native runs; durable identity precedes external work."""

import hashlib
import json
import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import Field, model_validator

from agenttinker.core.records import Capabilities, Run, RunConfig, Text, ValueModel, VersionRef
from agenttinker.core.states import TERMINAL_STATUSES, RunStatus
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.fixtures import fixture_hash, search_documents
from agenttinker.m0.models import ToolPolicy
from agenttinker.m0.openai_model import OpenAIModel, ProviderNotConfigured
from agenttinker.m0.probe import TASK
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.runtime.journal import ExecutionFailed, RunCancelled, RunJournal
from agenttinker.runtime.serial import SerialExecutor
from agenttinker.storage.sqlite import SQLiteEventStore

AGENT_ID = "serial-checkpoint"


class RunRequest(ValueModel):
    mode: Literal["live", "synthetic"]
    provider: Literal["openai", "deepseek"] | None = None
    model: Text | None = None
    task: Text = Field(default=TASK, max_length=8000)
    policy: ToolPolicy = Field(default_factory=ToolPolicy)
    inject_timeout: bool = True

    @model_validator(mode="after")
    def explicit_provider(self):
        if self.mode == "live" and self.provider is None:
            raise ValueError("live_provider_required")
        if self.mode == "synthetic" and (self.provider is not None or self.model is not None):
            raise ValueError("synthetic_cannot_select_live_provider")
        return self


def default_model(request: RunRequest):
    if request.mode == "synthetic":
        return SyntheticModel()
    profile = DeepSeekModel if request.provider == "deepseek" else OpenAIModel
    return profile.from_environment(request.model)


class RunService:
    def __init__(
        self,
        database: Path | str,
        *,
        model_factory=None,
        tool=search_documents,
        pricing=None,
        max_workers: int = 2,
    ):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._owner = FileLock(str(self.database) + ".runtime.lock", thread_local=False)
        try:
            self._owner.acquire(timeout=0)
        except Timeout:
            raise RuntimeError("runtime_owner_already_active") from None
        self._lock, self._closing, self._closed = RLock(), False, False
        self.model_factory = model_factory or default_model
        self.tool, self.pricing = tool, pricing
        self._futures: dict[str, Future] = {}
        try:
            with SQLiteEventStore(self.database) as store:
                for run_id in store.run_ids():
                    run = store.get_view(run_id).run
                    if run.config.agent.id == AGENT_ID and run.status not in TERMINAL_STATUSES:
                        self._status(run_id, RunStatus.INTERRUPTED, "previous_owner_stopped")
            self._pool = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="agenttinker"
            )
        except Exception:
            self._owner.release()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def journal(self, run_id):
        return RunJournal(self.database, run_id, self._lock, self.pricing)

    def get(self, run_id):
        with SQLiteEventStore(self.database) as store:
            return store.get_view(run_id)

    def _status(self, run_id, status, reason=None):
        with self._lock:
            previous = self.get(run_id).run.status
            if previous in TERMINAL_STATUSES or previous == status:
                return
            self.journal(run_id).emit(
                "run.status_changed",
                {
                    "before": previous,
                    "after": status,
                    "reason": reason,
                },
            )

    def submit(self, request: RunRequest, request_key: str):
        if (
            not isinstance(request_key, str)
            or not 1 <= len(request_key) <= 128
            or not request_key.isprintable()
        ):
            raise ValueError("invalid_idempotency_key")
        fingerprint = hashlib.sha256(
            json.dumps(request.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        with self._lock, SQLiteEventStore(self.database) as store:
            if self._closing:
                raise RuntimeError("runtime_closed")
            existing = store.request_run(request_key, fingerprint)
            if existing is not None:
                return existing, False
            resolved = request
            model_parameters = {}
            if request.mode == "live":
                model_id = (
                    request.model or os.environ.get(f"{request.provider.upper()}_MODEL", "")
                ).strip()
                if not model_id:
                    raise ProviderNotConfigured("provider_not_configured: model ID required")
                resolved = request.model_copy(update={"model": model_id})
                if self.model_factory is default_model:
                    configured = default_model(resolved)  # Configuration only; no provider call.
                    try:
                        prepared = configured._request([{"role": "user", "content": resolved.task}])
                        model_parameters = {
                            key: value
                            for key, value in prepared.items()
                            if key in {"max_tokens", "max_completion_tokens", "extra_body"}
                        }
                    finally:
                        configured.close()
            now = datetime.now(UTC)
            run = Run(
                run_id=f"run_{uuid4().hex}",
                mode=resolved.mode,
                created_at=now,
                updated_at=now,
                capabilities=Capabilities(run_from_start=True),
                config=RunConfig(
                    agent=VersionRef(id=AGENT_ID, version="1"),
                    task=resolved.task,
                    tool_policy=resolved.policy.model_dump(),
                    price_version=self.pricing.version if self.pricing else None,
                    provider=resolved.provider or "synthetic",
                    requested_model=resolved.model,
                    model_parameters=model_parameters,
                    prompt_version="single-tool-v1",
                    tool_versions={"search_documents": "1"},
                    fixture_hash=fixture_hash(),
                    fault_plan=VersionRef(id="first-search-timeout", version="1")
                    if resolved.inject_timeout
                    else None,
                    fault_parameters={"inject_timeout": resolved.inject_timeout},
                    runtime_versions={
                        name: version(name)
                        for name in ("langgraph", "langgraph-checkpoint", "openai")
                    },
                ),
            )
            view, created = store.create_requested_run(run, request_key, fingerprint)
            if created:
                try:
                    self._futures[run.run_id] = self._pool.submit(
                        self._execute, run.run_id, resolved
                    )
                except Exception as error:
                    self._status(
                        run.run_id, RunStatus.FAILED, f"dispatch_failed:{type(error).__name__}"
                    )
                    view = store.get_view(run.run_id)
            return view, created

    def cancel(self, run_id):
        with self._lock:
            if self._closed:
                raise RuntimeError("runtime_closed")
            status = self.get(run_id).run.status
            if status not in TERMINAL_STATUSES:
                self._status(run_id, RunStatus.CANCEL_REQUESTED, "user_requested")
                if status == RunStatus.QUEUED:
                    self._status(run_id, RunStatus.CANCELLED, "cancelled_before_dispatch")
            return self.get(run_id)

    def _execute(self, run_id, request):
        model = None
        try:
            with self._lock:
                if self.get(run_id).run.status != RunStatus.QUEUED:
                    return
                self._status(run_id, RunStatus.RUNNING)
            model = self.model_factory(request)
            if model.mode != request.mode or model.provider != (request.provider or "synthetic"):
                raise ExecutionFailed("adapter_provenance_mismatch")
            SerialExecutor(self.journal(run_id), request, model, self.tool).execute()
            self._finish(run_id, RunStatus.SUCCEEDED)
        except RunCancelled:
            self._finish(run_id, RunStatus.CANCELLED)
        except ExecutionFailed as error:
            self._finish(run_id, RunStatus.FAILED, str(error))
        except ProviderNotConfigured:
            self._finish(run_id, RunStatus.FAILED, "provider_not_configured")
        except Exception as error:
            self._status(run_id, RunStatus.INTERRUPTED, f"executor_error:{type(error).__name__}")
            raise
        finally:
            if isinstance(model, OpenAIModel):
                model.close()

    def _finish(self, run_id, status, reason=None):
        with self._lock:
            if self.get(run_id).run.status == RunStatus.CANCEL_REQUESTED:
                status, reason = RunStatus.CANCELLED, "cooperative_cancel_completed"
            self._status(run_id, status, reason)

    def wait(self, run_id, timeout=10):
        with self._lock:
            future = self._futures.get(run_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(run_id)

    def close(self):
        with self._lock:
            if self._closing:
                return
            self._closing = True
            for run_id in self._futures:
                self.cancel(run_id)
        try:
            self._pool.shutdown(wait=True)
        finally:
            self._closed = True
            self._owner.release()
