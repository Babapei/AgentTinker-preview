from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from agenttinker.m0.models import ToolPolicy
from agenttinker.m0.probe import CheckpointProbe, run_comparison
from agenttinker.m0.synthetic import SyntheticModel


def test_retry_branch_keeps_baseline_and_reexecutes_the_same_fault():
    report = run_comparison(SyntheticModel())
    assert all(report["checks"].values())
    assert report["baseline"]["new_model_calls"] == 1
    assert report["branch"]["new_model_calls"] == 1
    assert report["baseline"]["new_tool_attempts"] == 1
    assert report["branch"]["new_tool_attempts"] == 2
    assert len(report["baseline_checkpoints"]) >= 4
    assert len({c["checkpoint_id"] for c in report["baseline_checkpoints"]}) >= 4
    assert report["branch"]["parent_run_id"] == report["baseline"]["run_id"]
    assert report["branch"]["state"]["policy"] == {"tool_retry_limit": 1, "top_k": 2}
    assert report["mode"] == "synthetic"
    assert report["m0_real_call_verified"] is False
    assert report["branch"]["new_cost"] is None
    assert all(span["usage"] is None for span in report["branch"]["spans"])


def test_retrieval_branch_preserves_query_and_does_not_recall_model_prefix():
    probe = CheckpointProbe(SyntheticModel(), inject_timeout=False)
    a = probe.run()
    original = probe.evidence(a)
    b = probe.fork(a, {"top_k": 3})
    assert len(probe.state(a)["documents"]) == 2
    assert len(probe.state(b)["documents"]) == 3
    assert probe.evidence(a) == original
    assert probe.evidence(a)["new_model_calls"] == 2
    assert probe.evidence(b)["new_model_calls"] == 1
    assert probe.evidence(b)["new_tool_attempts"] == 1
    a_tool = next(s for s in probe.spans[a.run_id] if s.kind == "tool")
    b_tool = next(s for s in probe.spans[b.run_id] if s.kind == "tool")
    assert a_tool.input["tool_call"] == b_tool.input["tool_call"]
    assert b_tool.parent_span_id == a_tool.parent_span_id


@pytest.mark.parametrize("patch", [{"query": "changed"}, {"run_id": "changed"}, {}])
def test_unsupported_patches_create_no_new_history_or_calls(patch):
    probe = CheckpointProbe(SyntheticModel())
    a = probe.run()
    history = probe.history(a)
    records = deepcopy(probe.spans)
    with pytest.raises(ValueError, match="invalid_patch"):
        probe.fork(a, patch)
    assert probe.history(a) == history
    assert probe.spans == records


@pytest.mark.parametrize("patch", [{"top_k": 0}, {"top_k": "3"}, {"tool_retry_limit": -1}])
def test_invalid_policy_does_not_execute(patch):
    probe = CheckpointProbe(SyntheticModel())
    a = probe.run()
    with pytest.raises(ValidationError):
        probe.fork(a, patch)
    assert list(probe.spans) == [a.run_id]


def test_missing_checkpoint_cannot_fork():
    probe = CheckpointProbe(SyntheticModel())
    a = probe.run()
    with pytest.raises(ValueError, match="checkpoint_missing"):
        probe.fork(replace(a, tool_checkpoint=None), {"top_k": 3})


def test_multiple_branches_keep_previous_terminal_checkpoints_readable():
    probe = CheckpointProbe(SyntheticModel())
    a = probe.run()
    b = probe.fork(a, {"tool_retry_limit": 1})
    a_original, b_original = probe.evidence(a), probe.evidence(b)
    c = probe.fork(a, {"tool_retry_limit": 1, "top_k": 3})
    assert len(probe.state(c)["documents"]) == 3
    assert probe.evidence(a) == a_original
    assert probe.evidence(b) == b_original


def test_explicit_policy_runs_without_injected_timeout():
    probe = CheckpointProbe(SyntheticModel(), inject_timeout=False)
    a = probe.run(ToolPolicy(top_k=3))
    assert probe.state(a)["status"] == "succeeded"
    assert len(probe.state(a)["documents"]) == 3
