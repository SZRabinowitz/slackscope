"""Configuration loading for the Slack CLI."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from slack_cli.errors import ConfigError

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import fallback
    load_dotenv = None


WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DEFAULT_ENV_FILE = Path.home() / ".config" / "slack" / "slack.env"
ENV_FILE_OVERRIDE_VAR = "SLACK_ENV_FILE"


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
        "Set it in your shell, in ~/.config/slack/slack.env, "
        "or in local ./slack.env or ./.env."
    )


def _load_env_files() -> None:
    if load_dotenv is None:
        return

    override = (os.getenv(ENV_FILE_OVERRIDE_VAR) or "").strip()
    if override:
        override_path = Path(override).expanduser()
        if not override_path.is_file():
            raise ConfigError(
                f"{ENV_FILE_OVERRIDE_VAR} points to a missing file: {override_path}"
            )
        load_dotenv(dotenv_path=override_path, override=False)
        return

    cwd = Path.cwd()
    candidates = [
        DEFAULT_ENV_FILE,
        cwd / "slack.env",
        cwd / ".env",
    ]

    for path in candidates:
        if path.is_file():
            load_dotenv(dotenv_path=path, override=False)
            if path == DEFAULT_ENV_FILE:
                return
            break


def load_settings() -> Settings:
    """Load and validate runtime settings from environment variables."""

    _load_env_files()

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
