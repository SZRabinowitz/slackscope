"""Domain-specific exceptions for the Slack CLI."""

from __future__ import annotations


class SlackCLIError(Exception):
    """Base exception for expected CLI errors."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(SlackCLIError):
    """Raised when required configuration is missing or invalid."""


class SlackApiError(SlackCLIError):
    """Raised for Slack API responses where ok=false."""

    def __init__(self, method: str, error: str, details: dict | None = None) -> None:
        super().__init__(f"Slack API error for {method}: {error}")
        self.method = method
        self.error = error
        self.details = details or {}


class NotFoundError(SlackCLIError):
    """Raised when target entities cannot be resolved."""


class AmbiguousTargetError(SlackCLIError):
    """Raised when a non-unique target is provided by name."""

    def __init__(self, message: str, candidates: list[dict]) -> None:
        super().__init__(message)
        self.candidates = candidates
