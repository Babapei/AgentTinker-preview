"""Freeze the public request template, independently of conversation messages."""

import json
from copy import deepcopy

# Existing runs froze only these fields. Never replace their recorded configuration.
LEGACY_PARAMETER_KEYS = frozenset({"max_tokens", "max_completion_tokens", "extra_body"})


def request_parameters(prepared):
    # Model identity already has its own RunConfig field. Tools/choice are part of
    # the template, including the presence or absence of a parallel-call control.
    return deepcopy(
        {key: value for key, value in prepared.items() if key not in {"model", "messages"}}
    )


def same_parameters(left, right):
    # JSON types matter: false must not compare equal to 0 (or true to 1).
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
