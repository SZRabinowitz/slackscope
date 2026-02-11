"""`slack api ...` expert passthrough commands."""

from __future__ import annotations

import shlex
import subprocess

import click
from rich.markup import escape

from slack_cli.context import AppContext
from slack_cli.errors import SlackCLIError


@click.group("api")
def api_group() -> None:
    """Call Slack API methods directly with raw output."""


@api_group.command("call")
@click.argument("endpoint")
@click.option(
    "-X",
    "--method",
    "http_method",
    default="POST",
    show_default=True,
    help="HTTP method for the request.",
)
@click.option(
    "-p",
    "--param",
    "raw_params",
    multiple=True,
    help="Request parameter in key=value form. Repeat as needed.",
)
@click.pass_obj
def api_call(
    app: AppContext,
    endpoint: str,
    http_method: str,
    raw_params: tuple[str, ...],
) -> None:
    """Call a Slack API endpoint and emit the raw response body."""

    params = _parse_params(raw_params)
    body = app.client.call_raw(endpoint, http_method=http_method, params=params)
    click.echo(body, nl=False)


@api_group.command("curl")
@click.argument("endpoint")
@click.option(
    "--print-command",
    is_flag=True,
    help="Print the redacted curl command before executing.",
)
@click.option(
    "--print-only",
    is_flag=True,
    help="Print the redacted curl command and exit.",
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_obj
def api_curl(
    app: AppContext,
    endpoint: str,
    print_command: bool,
    print_only: bool,
    extra_args: tuple[str, ...],
) -> None:
    """Run a curl command pre-wired for Slack API auth."""

    url = app.client.api_url(endpoint)
    command = [
        "curl",
        "-sS",
        "-X",
        "POST",
        "-H",
        f"Cookie: d={app.settings.d_cookie}",
        "--data-urlencode",
        f"token={app.settings.token}",
        *list(extra_args),
        url,
    ]

    rendered = shlex.join(command)
    redacted = _redact_command(rendered, app.settings.token, app.settings.d_cookie)
    if print_command or print_only:
        app.console.print(f"[dim cyan]{escape(redacted)}[/]")

    if print_only:
        return

    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SlackCLIError(
            f"curl command failed with exit code {completed.returncode}",
            exit_code=completed.returncode,
        )


def _parse_params(raw_params: tuple[str, ...]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in raw_params:
        if "=" not in item:
            raise SlackCLIError(
                f"Invalid --param value: {item!r}. Use key=value format."
            )
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SlackCLIError("Parameter key cannot be empty")
        params[key] = value
    return params


def _redact_command(command: str, token: str, d_cookie: str) -> str:
    redacted = command
    if token:
        redacted = redacted.replace(token, "<TOKEN_REDACTED>")
    if d_cookie:
        redacted = redacted.replace(d_cookie, "<D_COOKIE_REDACTED>")
    return redacted
