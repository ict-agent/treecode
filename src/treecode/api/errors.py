"""API error types for TreeCode."""

from __future__ import annotations


class TreeCodeApiError(RuntimeError):
    """Base class for upstream API failures."""


class AuthenticationFailure(TreeCodeApiError):
    """Raised when the upstream service rejects the provided credentials."""


class RateLimitFailure(TreeCodeApiError):
    """Raised when the upstream service rejects the request due to rate limits."""


class RequestFailure(TreeCodeApiError):
    """Raised for generic request or transport failures."""
