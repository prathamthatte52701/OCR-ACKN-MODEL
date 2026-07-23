from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Replicates helmet()'s defaults used by the old Express app (crossOriginResourcePolicy
# disabled there too, for the same reason: dev frontend on a different port fetches
# JSON/blob cross-origin, and the app's own CORS config already governs that).
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-DNS-Prefetch-Control": "off",
    "X-Download-Options": "noopen",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=15552000; includeSubDomains",
}


# This backend only ever serves JSON (plus FastAPI's own /docs, /redoc,
# /openapi.json - which load Swagger UI's inline scripts/styles from a CDN,
# so they're excluded from the CSP below rather than left unrestricted).
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}
_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers[name] = value
        if request.url.path not in _DOCS_PATHS:
            response.headers["Content-Security-Policy"] = _CSP
        return response
