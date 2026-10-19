"""Optional shared-password access for a single-owner preview, including SSE."""

import base64
import binascii
from hashlib import sha256
from hmac import compare_digest
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class PreviewAccess:
    def __init__(self, app, *, password: str):
        self.app = app
        self.expected = sha256(f"preview:{password}".encode()).digest()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/healthz" and scope["method"] in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        authorized = False
        values = headers.getlist("authorization")
        if len(values) == 1:
            scheme, _, token = values[0].partition(" ")
            if scheme.lower() == "basic":
                try:
                    supplied = base64.b64decode(token, validate=True)
                    authorized = compare_digest(sha256(supplied).digest(), self.expected)
                except (binascii.Error, ValueError):
                    pass
        if not authorized:
            response = JSONResponse(
                {"detail": "preview_access_required"},
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Basic realm="AgentTinker preview", charset="UTF-8"',
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return
        # Browsers can reuse Basic credentials on cross-origin requests. Reject writes
        # from another origin, including simple requests that don't need CORS preflight.
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get("origin")
            allowed = headers.get("sec-fetch-site") != "cross-site"
            if origin is not None:
                try:
                    parsed = urlsplit(origin)
                    allowed = allowed and (
                        parsed.scheme in {"http", "https"}
                        and parsed.netloc.lower() == headers.get("host", "").lower()
                        and not parsed.path
                        and not parsed.query
                        and not parsed.fragment
                    )
                except ValueError:
                    allowed = False
            if not allowed:
                await JSONResponse({"detail": "preview_origin_rejected"}, status_code=403)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)
