"""Request-size guard for the upload endpoints.

Why a middleware and not a check inside the route: FastAPI parses the whole
multipart body (File()/Form() parameters) BEFORE the route function or any
dependency runs, so a handler-level check can only fire after a huge body has
already been received and spooled. This runs first and does two things:

1. Declared size: a Content-Length above the route's ceiling is refused with
   413 before a single body byte is read.
2. Streamed size: the body is counted as it arrives, so a missing/understated
   Content-Length or chunked encoding cannot get past the ceiling - the request
   is cut off with 413 the moment it exceeds it.

The per-file 5 MB rule (and type/MIME/page checks) still lives in the route; this
only bounds the whole request so one connection cannot make the server buffer
gigabytes.
"""

import json

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_BIG_DETAIL = "File size must be 5 MB or less."
_TOO_BIG_BODY = json.dumps({"detail": TOO_BIG_DETAIL}).encode()


class _RequestTooLarge(Exception):
    pass


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, limits: dict[str, int]) -> None:
        self.app = app
        self.limits = limits  # exact path -> max request body bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self.limits.get(scope.get("path", "")) if scope["type"] == "http" else None
        if limit is None or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True
            if too_big:
                await self._reject(scope, receive, send)
                return

        received = 0
        exceeded = False
        body_sent = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _RequestTooLarge
            return message

        async def replacing_send(message: Message) -> None:
            # FastAPI turns ANY error raised while it reads the body into its own
            # 400 "error parsing the body", so the exception above cannot be relied
            # on to surface. Instead remember that the limit was crossed and swap
            # whatever response the app produces for the real answer: 413.
            nonlocal body_sent
            if not exceeded:
                await send(message)
                return
            if message["type"] == "http.response.start":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(_TOO_BIG_BODY)).encode()),
                        ],
                    }
                )
            elif message["type"] == "http.response.body" and not body_sent:
                body_sent = True
                await send({"type": "http.response.body", "body": _TOO_BIG_BODY})

        try:
            await self.app(scope, limited_receive, replacing_send)
        except _RequestTooLarge:
            if not body_sent:
                await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"detail": TOO_BIG_DETAIL}, status_code=413)
        await response(scope, receive, send)
