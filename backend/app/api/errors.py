"""Uniform error envelope and exception handlers.

Every non-2xx response from the API has the same shape:

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": ...}}

so the frontend and the evaluation harness never have to special-case error
parsing. `request_id` ties the failure back to the structured log lines and the
query_logs row for that request.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_var

logger = get_logger(__name__)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AppError(Exception):
    """Base class for expected, domain-level failures.

    Raise these from the service layer. Routes never build error responses by
    hand; the handlers below turn these into the envelope above.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "app_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class InvalidRequestError(AppError):
    """The request is well-formed but asks for something that is not allowed,
    such as a document readable by no group."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_request"


class ConfigurationError(AppError):
    """A required piece of configuration is missing or invalid.

    Example: the generation layer was called without ANTHROPIC_API_KEY set.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "configuration_error"


def _envelope(
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id_var.get(),
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json"), headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", code=exc.code, message=exc.message)
        return _envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Request validation failed.",
            details=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Headers carry protocol meaning (WWW-Authenticate on a 401), so they
        # survive the switch to the error envelope.
        return _envelope(
            exc.status_code, "http_error", str(exc.detail), headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback, return a generic message. Internal details never
        # leak to the client, but request_id makes them findable in the logs.
        logger.exception("unhandled_exception", error=str(exc))
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred. Reference the request_id when reporting this.",
        )
