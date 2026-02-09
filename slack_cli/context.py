"""Shared runtime context passed to Click commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from rich.console import Console

from slack_cli.config import Settings

if TYPE_CHECKING:
    from slack_cli.client import SlackClient


OutputFormat = Literal["pretty", "json", "jsonl", "tsv"]


@dataclass
class AppContext:
    """Container for shared runtime objects."""

    settings: Settings
    client: "SlackClient"
    console: Console
    output_format: OutputFormat
    fields: list[str] | None
    verbose: bool = False
