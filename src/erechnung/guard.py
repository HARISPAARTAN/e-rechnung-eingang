"""Pure ASGI guard for POST /validate: API key and upload size are checked before the body is read.

FastAPI parses a multipart form before any dependency runs, so a check inside the handler only sees a request whose
body has already arrived. This middleware answers 401 on a wrong or missing key without touching the body, 413 on a
Content-Length above the limit without reading, and 413 as soon as a streamed (chunked) body crosses the limit; the
rest of the stream is then not consumed. The handler's own key check and bounded read stay as defence in depth.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

KEY_DETAIL = "API-Schlüssel fehlt oder ist ungültig"
# Multipart framing (boundaries, part headers) on top of the file itself; a file of exactly max_upload_mb still passes.
MULTIPART_SLACK = 16 * 1024


async def _respond(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class UploadGuard:
    def __init__(self, app: ASGIApp, api_key: str | None, max_upload_mb: int, path: str = "/validate") -> None:
        self.app = app
        self.key = api_key.encode("utf-8") if api_key else None
        self.max_upload_mb = max_upload_mb
        self.limit = max_upload_mb * 1024 * 1024 + MULTIPART_SLACK
        self.path = path

    def _too_large(self) -> str:
        return f"Datei größer als {self.max_upload_mb} MB"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        if self.key is not None and not hmac.compare_digest(headers.get(b"x-api-key", b""), self.key):
            await _respond(send, 401, KEY_DETAIL)
            return
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.limit:
                    await _respond(send, 413, self._too_large())
                    return
            except ValueError:
                await _respond(send, 400, "ungültige Content-Length")
                return

        received = 0
        rejected = False
        started = False

        async def guarded_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    rejected = True
                    if not started:
                        await _respond(send, 413, self._too_large())
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # the 413 has been sent; whatever the app answers to the disconnect is dropped
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except Exception:
            if not rejected:
                raise
