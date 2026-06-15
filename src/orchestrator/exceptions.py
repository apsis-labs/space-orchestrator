"""Custom exceptions for the orchestrator.

A well-defined hierarchy lets callers catch specific failure modes
(transient network errors vs. configuration mistakes vs. provider
booking failures) and react appropriately.
"""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base exception for all orchestrator errors."""

    pass


# ---------------------------------------------------------------------------
# Provider / Adapter layer
# ---------------------------------------------------------------------------


class ProviderError(OrchestratorError):
    """Base for all provider adapter errors."""

    pass


class BookingError(ProviderError):
    """Failed to book a contact with a provider."""

    def __init__(
        self, provider: str, message: str, cause: Exception | None = None
    ) -> None:
        self.provider = provider
        self.cause = cause
        super().__init__(f"[{provider}] {message}")


class PollError(ProviderError):
    """Failed to poll contact status from a provider."""

    def __init__(
        self, provider: str, message: str, cause: Exception | None = None
    ) -> None:
        self.provider = provider
        self.cause = cause
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailableError(ProviderError):
    """Provider is temporarily unavailable (retry may help).

    Raised for transient errors like throttling, timeouts, or temporary
    service outages. Callers should catch this and retry with backoff.
    """

    pass


# ---------------------------------------------------------------------------
# Configuration / Validation
# ---------------------------------------------------------------------------


class ConfigurationError(OrchestratorError):
    """Invalid configuration (SLO bounds, missing adapters, etc.)."""

    pass


class ValidationError(OrchestratorError):
    """Input validation failed."""

    pass


# ---------------------------------------------------------------------------
# TLE / Visibility
# ---------------------------------------------------------------------------


class TLEError(OrchestratorError):
    """TLE loading or parsing failed."""

    pass


class VisibilityError(OrchestratorError):
    """Pass computation failed."""

    pass
