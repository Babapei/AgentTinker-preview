"""One local owner dispatches native runs; durable identity precedes external work."""

import os
import sqlite3
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import Field, model_validator

from agenttinker.core.records import (
    Capabilities,
    CheckpointRef,
    Identifier,
    Intervention,
    JSONData,
    Run,
    RunConfig,
    Text,
    ValueModel,
    VersionRef,
)
from agenttinker.core.requests import request_identity
from agenttinker.core.states import TERMINAL_STATUSES, RunStatus
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.document_model import document_model
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.fixtures import fixture_hash, search_documents
from agenttinker.m0.models import ToolPolicy
from agenttinker.m0.openai_model import OpenAIModel, ProviderNotConfigured
from agenttinker.m0.probe import TASK
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.runtime.checkpoints import (
    AGENT_ID,
    AGENT_VERSION,
    PATCH_FIELDS,
    TOOL_VERSIONS,
    CheckpointUnavailable,
    ForkRejected,
    checkpoint_path,
    open_checkpoints,
    runtime_versions,
)
from agenttinker.runtime.document import DocumentExecutor
from agenttinker.runtime.journal import ExecutionFailed, RunCancelled, RunJournal
from agenttinker.runtime.model_config import (
    LEGACY_PARAMETER_KEYS,
    request_parameters,
    same_parameters,
)
from agenttinker.runtime.serial import SerialExecutor
from agenttinker.storage.evaluations import AssessmentRejected, SQLiteEvaluationStore
from agenttinker.storage.sqlite import SQLiteEventStore


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


class ForkRequest(ValueModel):
    source_checkpoint_id: Identifier
    patch: JSONData


class DocumentRunRequest(ValueModel):
    mode: Literal["live", "synthetic"]
    provider: Literal["openai", "deepseek"] | None = None
    model: Text | None = None
    variant: Literal["baseline", "candidate"] = "baseline"

    @model_validator(mode="after")
    def explicit_provider(self):
        # Keep the original RunRequest wire shape and idempotency fingerprint unchanged.
        RunRequest(mode=self.mode, provider=self.provider, model=self.model)
        return self


class CheckpointAvailability(ValueModel):
    checkpoint: CheckpointRef
    available: bool
    reason: (
        Literal[
            "unsupported_capability",
            "source_run_active",
            "checkpoint_missing",
            "runtime_incompatible",
            "checkpoint_state_invalid",
            "checkpoint_unreadable",
        ]
        | None
    )
    allowed_patch_fields: tuple[Literal["tool_retry_limit", "top_k"], ...]


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
                    if (
                        run.mode in {"live", "synthetic"}
                        and run.config.agent.id in {AGENT_ID, corpus.AGENT.id}
                        and run.status not in TERMINAL_STATUSES
                    ):
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

    def _model(self, request, agent):
        if self.model_factory is default_model and agent == corpus.AGENT:
            return document_model(request)
        return self.model_factory(request)

    def _check_model_config(self, model, request, view):
        prepared = model._request([{"role": "user", "content": request.task}])
        expected = request_parameters(prepared)
        config = view.run.config
        recorded = config.model_parameters
        if prepared.get("model") != config.requested_model:
            raise ForkRejected("runtime_incompatible")
        if same_parameters(recorded, expected):
            return
        # Old configurations lack the tools/choice fields. Compare the complete
        # observed first request instead, including an inherited model prefix.
        if set(recorded) <= LEGACY_PARAMETER_KEYS and same_parameters(
            recorded,
            {key: value for key, value in expected.items() if key in LEGACY_PARAMETER_KEYS},
        ):
            try:
                with SQLiteEvaluationStore(self.database) as store:
                    spans = (*view.spans, *store.inherited_spans(view))
            except AssessmentRejected:
                raise ForkRejected("runtime_incompatible") from None
            initial = [span for span in spans if span.kind == "model" and span.call_index == 1]
            if (
                len(initial) == 1
                and initial[0].provider == config.provider
                and initial[0].input.get("model") == config.requested_model
                and same_parameters(request_parameters(initial[0].input), expected)
            ):
                return
        raise ForkRejected("runtime_incompatible")

    @staticmethod
    def _executor(agent):
        if agent == corpus.AGENT:
            return DocumentExecutor
        if agent == VersionRef(id=AGENT_ID, version=AGENT_VERSION):
            return SerialExecutor
        raise CheckpointUnavailable("runtime_incompatible")

    def resolve_checkpoint(self, run_id, checkpoint_id):
        view = self.get(run_id)
        reference = next(
            (item for item in view.checkpoints if item.checkpoint_id == checkpoint_id), None
        )
        if reference is None or not checkpoint_path(self.database).is_file():
            raise CheckpointUnavailable("checkpoint_missing")
        try:
            with open_checkpoints(self.database) as saver:
                return self._executor(view.run.config.agent).load_checkpoint(saver, view, reference)
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            raise CheckpointUnavailable("checkpoint_unreadable") from None

    def _fork_boundary(self, view, checkpoint_id):
        if not (
            view.run.capabilities.fork_from_checkpoint and view.run.capabilities.patch_tool_policy
        ):
            raise ForkRejected("unsupported_capability")
        if view.run.status not in TERMINAL_STATUSES:
            raise ForkRejected("source_run_active")
        self._compatible_context(view.run.config)
        reference = next(
            (item for item in view.checkpoints if item.checkpoint_id == checkpoint_id), None
        )
        if reference is None:
            raise CheckpointUnavailable("checkpoint_missing")
        expected_fields = ("top_k",) if view.run.config.agent == corpus.AGENT else PATCH_FIELDS
        if set(reference.allowed_patch_fields) != set(expected_fields):
            raise ForkRejected("unsupported_capability")
        snapshot = self.resolve_checkpoint(view.run.run_id, checkpoint_id)
        return reference, snapshot

    def _compatible_context(self, config):
        if (
            config.price_version != (self.pricing.version if self.pricing else None)
            or config.fault_parameters not in ({"inject_timeout": True}, {"inject_timeout": False})
            or config.fault_plan
            != (
                VersionRef(id="first-search-timeout", version="1")
                if config.fault_parameters.get("inject_timeout")
                else None
            )
        ):
            raise ForkRejected("runtime_incompatible")
        if config.agent == corpus.AGENT and (
            config.fault_parameters != {"inject_timeout": False}
            or config.experiment != corpus.EXPERIMENT
            or config.case != corpus.dataset_case().ref
            or config.task != corpus.TASK
            or config.tool_policy.get("tool_retry_limit") != 0
            or config.variant
            != VersionRef(id=f"document-top{config.tool_policy.get('top_k')}", version="1")
            or config.evaluator_versions != {corpus.EVALUATOR.id: corpus.EVALUATOR.version}
        ):
            raise ForkRejected("runtime_incompatible")

    def checkpoint_availability(self, run_id):
        view = self.get(run_id)
        results = []
        for reference in view.checkpoints:
            reason = None
            try:
                self._fork_boundary(view, reference.checkpoint_id)
            except ForkRejected as error:
                reason = error.code
            results.append(
                CheckpointAvailability(
                    checkpoint=reference,
                    available=reason is None,
                    reason=reason,
                    allowed_patch_fields=reference.allowed_patch_fields if reason is None else (),
                )
            )
        return tuple(results)

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
        fingerprint = request_identity(request_key, request.model_dump(mode="json"))
        return self._submit(request, request_key, fingerprint)

    def submit_document(self, request: DocumentRunRequest, request_key: str):
        definition = corpus.experiment_definition()
        variant = definition.baseline if request.variant == "baseline" else definition.candidate
        resolved = RunRequest(
            mode=request.mode,
            provider=request.provider,
            model=request.model,
            task=corpus.TASK,
            policy=variant.policy,
            inject_timeout=False,
        )
        fingerprint = request_identity(
            request_key,
            {
                "operation": "document-experiment",
                "experiment": definition.ref.model_dump(),
                "request": request.model_dump(mode="json"),
            },
        )
        return self._submit(resolved, request_key, fingerprint, variant=variant.ref)

    def _submit(self, request, request_key, fingerprint, *, variant=None):
        agent = corpus.AGENT if variant else VersionRef(id=AGENT_ID, version=AGENT_VERSION)
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
                    configured = self._model(resolved, agent)  # Configuration only; no HTTP call.
                    try:
                        prepared = configured._request([{"role": "user", "content": resolved.task}])
                        model_parameters = request_parameters(prepared)
                    finally:
                        configured.close()
            now = datetime.now(UTC)
            run = Run(
                run_id=f"run_{uuid4().hex}",
                mode=resolved.mode,
                created_at=now,
                updated_at=now,
                capabilities=Capabilities(
                    run_from_start=True, fork_from_checkpoint=True, patch_tool_policy=True
                ),
                config=RunConfig(
                    agent=agent,
                    task=resolved.task,
                    tool_policy=resolved.policy.model_dump(),
                    price_version=self.pricing.version if self.pricing else None,
                    provider=resolved.provider or "synthetic",
                    requested_model=resolved.model,
                    model_parameters=model_parameters,
                    prompt_version=corpus.PROMPT_VERSION if variant else "single-tool-v1",
                    tool_versions=corpus.TOOL_VERSIONS if variant else TOOL_VERSIONS,
                    fixture_hash=corpus.fixture_hash() if variant else fixture_hash(),
                    experiment=corpus.EXPERIMENT if variant else None,
                    case=corpus.dataset_case().ref if variant else None,
                    variant=variant,
                    evaluator_versions={corpus.EVALUATOR.id: corpus.EVALUATOR.version}
                    if variant
                    else {},
                    fault_plan=VersionRef(id="first-search-timeout", version="1")
                    if resolved.inject_timeout
                    else None,
                    fault_parameters={"inject_timeout": resolved.inject_timeout},
                    runtime_versions=runtime_versions(),
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

    def fork(self, source_run_id, request: ForkRequest, request_key: str):
        fingerprint = request_identity(
            request_key,
            {
                "operation": "fork",
                "source_run_id": source_run_id,
                "request": request.model_dump(mode="json"),
            },
        )
        with self._lock, SQLiteEventStore(self.database) as store:
            if self._closing:
                raise RuntimeError("runtime_closed")
            existing = store.request_run(request_key, fingerprint)
            if existing is not None:
                return existing, False
            source = store.get_view(source_run_id)
            reference, snapshot = self._fork_boundary(source, request.source_checkpoint_id)
            before = source.run.config.tool_policy
            if (
                len(request.patch) != 1
                or not set(request.patch) <= set(reference.allowed_patch_fields)
                or all(before.get(key) == value for key, value in request.patch.items())
            ):
                raise ForkRejected("invalid_patch")
            try:
                policy = ToolPolicy.model_validate({**before, **request.patch})
            except ValueError:
                raise ForkRejected("invalid_patch") from None
            config = source.run.config
            resolved = RunRequest(
                mode=source.run.mode,
                provider=config.provider if source.run.mode == "live" else None,
                model=config.requested_model if source.run.mode == "live" else None,
                task=config.task,
                policy=policy,
                inject_timeout=config.fault_parameters["inject_timeout"],
            )
            if resolved.mode == "live" and self.model_factory is default_model:
                configured = self._model(
                    resolved, config.agent
                )  # Configuration only; no HTTP call.
                try:
                    self._check_model_config(configured, resolved, source)
                finally:
                    configured.close()
            now = datetime.now(UTC)
            intervention = Intervention(
                intervention_id=f"intervention_{uuid4().hex}",
                parent_run_id=source_run_id,
                source_checkpoint_id=reference.checkpoint_id,
                patch=request.patch,
                before=before,
                after=policy.model_dump(),
            )
            run = Run(
                run_id=f"run_{uuid4().hex}",
                mode=source.run.mode,
                config=config.model_copy(
                    update={
                        "tool_policy": policy.model_dump(),
                        **(
                            {"variant": VersionRef(id=f"document-top{policy.top_k}", version="1")}
                            if config.agent == corpus.AGENT
                            else {}
                        ),
                    }
                ),
                created_at=now,
                updated_at=now,
                capabilities=source.run.capabilities,
                parent_run_id=source_run_id,
                source_checkpoint_id=reference.checkpoint_id,
                inherited_span_ids=(snapshot.values["model_span_id"],),
                intervention=intervention,
            )
            view, created = store.create_requested_run(run, request_key, fingerprint)
            if created:
                try:
                    self._futures[run.run_id] = self._pool.submit(
                        self._execute,
                        run.run_id,
                        resolved,
                        (source_run_id, reference.checkpoint_id),
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
            run = self.get(run_id).run
            if run.mode == "imported":
                raise ForkRejected("unsupported_capability")
            status = run.status
            if status not in TERMINAL_STATUSES:
                self._status(run_id, RunStatus.CANCEL_REQUESTED, "user_requested")
                if status == RunStatus.QUEUED:
                    self._status(run_id, RunStatus.CANCELLED, "cancelled_before_dispatch")
            return self.get(run_id)

    def _execute(self, run_id, request, source=None):
        model = None
        try:
            with self._lock:
                if self.get(run_id).run.status != RunStatus.QUEUED:
                    return
                self._status(run_id, RunStatus.RUNNING)
            view = self.get(run_id)
            agent = view.run.config.agent
            model = self._model(request, agent)
            if model.mode != request.mode or model.provider != (request.provider or "synthetic"):
                raise ExecutionFailed("adapter_provenance_mismatch")
            if request.mode == "live" and self.model_factory is default_model:
                self._check_model_config(model, request, view)
            with open_checkpoints(self.database) as saver:
                executor = self._executor(agent)(self.journal(run_id), request, model, self.tool)
                if source is None:
                    executor.execute(saver)
                else:
                    parent = self.get(source[0])
                    reference = next(
                        item for item in parent.checkpoints if item.checkpoint_id == source[1]
                    )
                    executor.fork(saver, parent, reference)
            self._finish(run_id, RunStatus.SUCCEEDED)
        except RunCancelled:
            self._finish(run_id, RunStatus.CANCELLED)
        except ExecutionFailed as error:
            self._finish(run_id, RunStatus.FAILED, str(error))
        except ForkRejected as error:
            self._finish(run_id, RunStatus.FAILED, error.code)
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
