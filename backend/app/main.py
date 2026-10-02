"""FastAPI application factory for the Kiowa Gun Club API."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    applications,
    auth,
    board_users,
    cms,
    communications,
    dashboard,
    events,
    member,
    payments,
    people,
    system,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.site_access import gate_applies, has_board_session
from app.services.membership import WorkflowError

logger = logging.getLogger("kiowa.http")

API_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# JSON responses never need to load anything; streamed files set their own policy.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
# Rejected before the body is read. Individual files are limited further by
# services/uploads.py; this covers the largest legitimate request (a batch of
# match photos).
MAX_REQUEST_BYTES = 100 * 1024 * 1024


def _error_body(detail: str, request: Request, errors: dict[str, str] | None = None) -> dict[str, object]:
    body: dict[str, object] = {"detail": detail, "request_id": request_id_var.get()}
    if errors:
        body["errors"] = errors
    return body


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, send_default_pii=False, traces_sample_rate=0.0)

    app = FastAPI(
        title="Kiowa Gun Club API",
        version="1.0.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):  # noqa: ANN001, ANN202
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
                response = JSONResponse(status_code=413, content=_error_body("That upload is too large.", request))
            elif request.method != "OPTIONS" and gate_applies(request.url.path) and not has_board_session(request):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "This site is in private preview. Sign in with a board account to view it.",
                             "code": "preview_locked", "request_id": request_id},
                )
            else:
                response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            response.headers["X-Request-ID"] = request_id
            for header, value in API_SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            response.headers.setdefault("Content-Security-Policy", API_CSP)
            if settings.is_production:
                response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
            if request.url.path not in ("/health",):
                logger.info(
                    "request",
                    extra={"method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": duration_ms},
                )
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(request: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.message, request, exc.errors))

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            body = _error_body(str(exc.detail.get("message", "Request failed.")), request, exc.detail.get("errors"))
        else:
            body = _error_body(str(exc.detail), request)
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors: dict[str, str] = {}
        for error in exc.errors():
            location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path", "form")]
            field = location[-1] if location else "request"
            if field.isdigit() and len(location) > 1:
                field = location[-2]
            message = str(error.get("msg", "Invalid value.")).removeprefix("Value error, ")
            errors.setdefault(field, message[0].upper() + message[1:] if message else "Invalid value.")
        first = next(iter(errors.values()), "Please check the form and try again.")
        return JSONResponse(status_code=422, content=_error_body(first, request, errors))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"path": request.url.path, "method": request.method})
        return JSONResponse(
            status_code=500,
            content=_error_body("Something went wrong on our end. Please try again, or contact the club if it keeps happening.", request),
        )

    for router in (
        system.router,
        auth.router,
        auth.board_router,
        member.router,
        applications.router,
        people.router,
        payments.router,
        payments.webhook_router,
        cms.public_router,
        cms.board_router,
        events.public_router,
        events.board_router,
        communications.router,
        communications.public_router,
        communications.webhook_router,
        board_users.router,
        dashboard.router,
    ):
        app.include_router(router)

    return app


app = create_app()
