"""Domain exception hierarchy.

Services raise these; the API layer is the only place that knows about HTTP.
That separation keeps the domain reusable from workers and CLI entrypoints,
where raising ``HTTPException`` would be meaningless.
"""

from __future__ import annotations

from typing import Any


class SecondBrainError(Exception):
    """Base class for every expected failure in the application."""

    status_code: int = 500
    error_code: str = "internal_error"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.error_code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(SecondBrainError):
    status_code = 404
    error_code = "not_found"
    default_message = "The requested resource was not found."


class ValidationError(SecondBrainError):
    status_code = 422
    error_code = "validation_error"
    default_message = "The request payload failed validation."


class ConflictError(SecondBrainError):
    status_code = 409
    error_code = "conflict"
    default_message = "The resource already exists or is in a conflicting state."


class AuthenticationError(SecondBrainError):
    status_code = 401
    error_code = "unauthenticated"
    default_message = "Authentication is required."


class InvalidSessionError(AuthenticationError):
    """The refresh session is unusable and its cookie must be discarded.

    Distinct from a plain ``AuthenticationError`` so the API layer knows to
    clear the refresh cookie; without that, a client holding a dead token
    retries with it indefinitely.
    """

    error_code = "invalid_session"
    default_message = "Your session is no longer valid. Please sign in again."


class AuthorizationError(SecondBrainError):
    status_code = 403
    error_code = "forbidden"
    default_message = "You do not have access to this resource."


class RateLimitError(SecondBrainError):
    status_code = 429
    error_code = "rate_limited"
    default_message = "Too many requests."


class PayloadTooLargeError(SecondBrainError):
    status_code = 413
    error_code = "payload_too_large"
    default_message = "The uploaded file exceeds the configured size limit."


class UnsupportedMediaTypeError(SecondBrainError):
    status_code = 415
    error_code = "unsupported_media_type"
    default_message = "This file type is not supported."


class ExternalServiceError(SecondBrainError):
    """A dependency we do not control failed (LLM API, Qdrant, object storage)."""

    status_code = 502
    error_code = "external_service_error"
    default_message = "An upstream service failed."


class ServiceUnavailableError(SecondBrainError):
    status_code = 503
    error_code = "service_unavailable"
    default_message = "The service is temporarily unavailable."


class ConfigurationError(SecondBrainError):
    """Raised at startup for an invalid or incomplete deployment configuration."""

    status_code = 500
    error_code = "configuration_error"
    default_message = "The application is misconfigured."
