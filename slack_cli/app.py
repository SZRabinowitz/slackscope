"""Click application entrypoint for Slack CLI."""

from __future__ import annotations

import os
import sys
from typing import cast

import click
from rich.console import Console

from slack_cli.client import SlackClient
from slack_cli.commands.api import api_group
from slack_cli.commands.auth import auth_group
from slack_cli.commands.chat import chat_group
from slack_cli.commands.dm import dm_group
from slack_cli.commands.me import me_command
from slack_cli.commands.thread import thread_group
from slack_cli.commands.users import users_group
from slack_cli.config import load_settings
from slack_cli.context import AppContext, OutputFormat
from slack_cli.errors import AmbiguousTargetError, SlackCLIError
from slack_cli.render import render_candidates


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["pretty", "json", "jsonl", "tsv"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--fields",
    help="Comma-separated fields to include in structured outputs.",
)
@click.option("--verbose", is_flag=True, help="Show extra error context.")
@click.pass_context
def main(
    ctx: click.Context, output_format: str, fields: str | None, verbose: bool
) -> None:
    """Read-first Slack CLI bridge."""

    auth_mode = _first_resource_arg(sys.argv) == "auth"

    parsed_fields = [
        part.strip() for part in (fields or "").split(",") if part.strip()
    ] or None
    settings = None
    client = None

    if not auth_mode:
        settings = load_settings()
        client = SlackClient(settings=settings, verbose=verbose)

    console = Console(soft_wrap=True)
    normalized_output = cast(OutputFormat, output_format.lower())

    app_context = AppContext(
        settings=settings,
        client=client,
        console=console,
        output_format=normalized_output,
        fields=parsed_fields,
        verbose=verbose,
    )

    ctx.obj = app_context
    if client is not None:
        ctx.call_on_close(client.close)


@main.result_callback()
def _handle_result(*_: object, **__: object) -> None:
    return None


main.add_command(me_command)
main.add_command(users_group)
main.add_command(chat_group)
main.add_command(dm_group)
main.add_command(thread_group)
main.add_command(api_group)
main.add_command(auth_group)


def run() -> None:
    """CLI entrypoint with user-friendly error handling."""

    if "--help" in sys.argv or "-h" in sys.argv:
        os.environ.setdefault("SLACK_WORKSPACE", "workspace")
        os.environ.setdefault("TOKEN", "help-token")
        os.environ.setdefault("D_COOKIE", "help-cookie")

    try:
        main(standalone_mode=False)
    except AmbiguousTargetError as exc:
        console = Console(stderr=True, soft_wrap=True)
        console.print(f"[red]{exc}[/]")
        render_candidates(console, exc.candidates)
        raise SystemExit(exc.exit_code)
    except SlackCLIError as exc:
        console = Console(stderr=True, soft_wrap=True)
        console.print(f"[red]{exc}[/]")
        raise SystemExit(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code)


def _first_resource_arg(argv: list[str]) -> str | None:
    """Return first non-option CLI token after executable name."""

    for token in argv[1:]:
        if token == "--":
            break
        if token.startswith("-"):
            continue
        return token
    return None
