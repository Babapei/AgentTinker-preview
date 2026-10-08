"""Versioned fictional release notes used by the local read-only tool."""

import hashlib
import json

DOCUMENTS = (
    {"id": "release-v1", "title": "Release v1", "text": "Version 1 supports document search."},
    {
        "id": "release-v2",
        "title": "Release v2",
        "text": "Version 2 adds configurable tool retries.",
    },
    {
        "id": "release-v2-fix",
        "title": "Release v2 fixes",
        "text": "Version 2 fixes missing citations.",
    },
)
FIXTURE_VERSION = "fictional-releases-v1"


def fixture_hash() -> str:
    encoded = json.dumps(DOCUMENTS, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def search_documents(query: str, top_k: int) -> list[dict[str, str]]:
    """Return matching fictional documents in stable fixture order."""
    terms = query.casefold().split()
    return [
        dict(doc)
        for doc in DOCUMENTS
        if any(term in f"{doc['title']} {doc['text']}".casefold() for term in terms)
    ][:top_k]
