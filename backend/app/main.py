import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo
from app.core.logging_config import configure_logging
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.features.admin.router import router as admin_router
from app.features.auth.router import router as auth_router
from app.features.documents.router import recover_interrupted_uploads
from app.features.documents.router import router as documents_router
from app.features.excel.router import router as excel_router
from app.features.ocr.pipeline import ocr_lock_status


async def _recover_interrupted_uploads_in_background() -> None:
    """Runs post-startup, never blocks the app from serving /health or any
    other request. Previously this ran inline before `yield` in lifespan(),
    which meant EVERY restart - including one caused by a crash - blocked
    the whole app (health included) until every stuck document finished a
    full sequential OCR pass. That's the actual cause of the reported "health
    briefly ok then next request hangs" pattern: health wasn't lying, the
    process just hadn't reached `yield` yet on the next restart either."""
    try:
        recovered = await recover_interrupted_uploads()
        if recovered:
            logger.warning(f"Requeued {recovered} interrupted document(s) for processing.")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Interrupted-upload recovery failed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    await connect_to_mongo()
    logger.info("MongoDB connected successfully")
    # Fire-and-forget, started AFTER Mongo connects but BEFORE yield returns
    # control - the app starts serving traffic immediately while recovery
    # runs in the background. Task is pinned to app.state so it isn't
    # garbage-collected mid-run.
    app.state.recovery_task = asyncio.create_task(_recover_interrupted_uploads_in_background())
    yield
    await close_mongo_connection()
    logger.info("MongoDB connection closed")


# Swagger/ReDoc/openapi.json hand an attacker a free, fully-enumerated map of
# every endpoint + request/response shape - no functional need for it once
# this is deployed (it's a fixed frontend/admin talking to a fixed API, not a
# public developer-facing API contract that needs discoverability). Left on
# in dev for convenience, disabled entirely in production so there's nothing
# to scan/enumerate at those paths at all.
app = FastAPI(
    title="AckIntel AI - Acknowledgement Intelligence Server",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """A malformed :id path param (e.g. "abc123") fails Pydantic's PyObjectId
    validation - without this, FastAPI's default is a 422 body shaped for
    request-schema errors. A bad id in the URL is a client input error the
    same way the old app treated it (utils/objectId.js -> 400), so path-param
    ObjectId failures specifically get remapped to a clean 400 here; every
    other validation error (bad request body/query) keeps FastAPI's normal 422."""
    for error in exc.errors():
        is_path_error = error.get("loc") and error["loc"][0] == "path"
        if is_path_error and "Invalid ObjectId" in str(error.get("msg", "")):
            return JSONResponse(status_code=400, content={"detail": "Invalid id."})
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    # Explicit allow-list only (never "*") - covers both the main app and the
    # separate admin app, in every environment. Previously this resolved to an
    # EMPTY list in production (blocking the real frontend entirely) and never
    # included the admin app's own origin at all - fixed to always be the
    # actual configured origins, sourced from env, dev or prod alike.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Browsers only expose CORS-safelisted response headers to JS by default -
    # Content-Disposition (filename) and the Download All skip-count headers
    # (documents/router.py::download_all_documents) need to be readable by
    # the frontend across origins, not just same-origin dev proxying.
    expose_headers=[
        "Content-Disposition",
        "X-Download-Included",
        "X-Download-Skipped",
        "X-Download-Total",
    ],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(excel_router, prefix="/api/documents", tags=["excel"])
app.include_router(documents_router, prefix="/api/documents", tags=["documents"])


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, object]:
    # ocrLockWedged: True only if the OCR lock has been held longer than the
    # longest legitimate single-document OCR call - distinguishes "app is up"
    # from "app is up but the OCR subsystem is stuck." Additive field only,
    # existing {"status": "ok"} consumers are unaffected.
    return {"status": "ok", "ocrLockWedged": ocr_lock_status()["wedged"]}
