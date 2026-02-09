"""Configuration loading for the Slack CLI."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from slack_cli.errors import ConfigError

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import fallback
    load_dotenv = None


WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    workspace: str
    token: str
    d_cookie: str
    timeout_seconds: float = 20.0

    @property
    def api_base(self) -> str:
        return f"https://{self.workspace}.slack.com/api"


def _required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    raise ConfigError(
        f"Missing required environment variable: {name}. "
        "Set it in your shell or .env file."
    )


def load_settings() -> Settings:
    """Load and validate runtime settings from environment variables."""

    if load_dotenv is not None:
        load_dotenv()

    workspace = _required("SLACK_WORKSPACE")
    if not WORKSPACE_RE.match(workspace):
        raise ConfigError(
            "SLACK_WORKSPACE must look like a Slack workspace slug "
            "(letters, numbers, hyphens)."
        )

    return Settings(
        workspace=workspace,
        token=_required("TOKEN"),
        d_cookie=_required("D_COOKIE"),
    )
