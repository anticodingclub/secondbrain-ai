"""Translates exceptions into a single, stable JSON error envelope.

The frontend can rely on one shape for every failure:
``{"error": <code>, "message": <human text>, "details": {...}, "request_id": ...}``
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import SecondBrainError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _envelope(
    request: Request, *, error: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": error, "message": message}
    if details:
        payload["details"] = details
    if request_id := getattr(request.state, "request_id", None):
        payload["request_id"] = request_id
    return payload


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SecondBrainError)
    if exc.status_code >= 500:
        logger.error("domain_error", error_code=exc.error_code, message=exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(request, error=exc.error_code, message=exc.message, details=exc.details),
    )


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(request, error="http_error", message=str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content=_envelope(
            request,
            error="validation_error",
            message="The request payload failed validation.",
            # jsonable_encoder-safe: Pydantic errors can carry non-serialisable ctx.
            details={
                "errors": [
                    {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
                    for e in exc.errors()
                ]
            },
        ),
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals to the client; the request id ties the response to
    # the full traceback in the logs.
    logger.exception("unhandled_exception", path=request.url.path, error=repr(exc))
    return JSONResponse(
        status_code=500,
        content=_envelope(request, error="internal_error", message="An unexpected error occurred."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SecondBrainError, _domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
