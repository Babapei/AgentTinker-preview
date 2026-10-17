"""Canonical local request identity; the original run fingerprint stays unchanged."""

import hashlib
import json


def request_identity(request_key, body):
    if (
        not isinstance(request_key, str)
        or not 1 <= len(request_key) <= 128
        or not request_key.isprintable()
    ):
        raise ValueError("invalid_idempotency_key")
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
