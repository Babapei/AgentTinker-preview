"""Run execution state is independent of answer quality and record playback."""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
)
TRANSITIONS = {
    RunStatus.QUEUED: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.RUNNING: frozenset(
        {RunStatus.CANCEL_REQUESTED, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.CANCEL_REQUESTED: frozenset(
        {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    **{status: frozenset() for status in TERMINAL_STATUSES},
}


def validate_transition(source: RunStatus, target: RunStatus) -> None:
    if target not in TRANSITIONS[source]:
        raise ValueError(f"invalid_run_transition: {source} -> {target}")


def can_start_call(status: RunStatus) -> bool:
    """An in-flight result may still arrive after this becomes false."""
    return status == RunStatus.RUNNING
