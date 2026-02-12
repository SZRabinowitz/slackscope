"""`slack auth ...` commands."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import click

from slack_cli.client import SlackClient
from slack_cli.config import DEFAULT_ENV_FILE, WORKSPACE_RE, Settings
from slack_cli.context import AppContext
from slack_cli.errors import ConfigError, SlackCLIError
from slack_cli.render import emit_data

try:
    from dotenv import dotenv_values  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import fallback
    dotenv_values = None


XOX_TOKEN_RE = re.compile(r"xox[a-z]-[A-Za-z0-9-]+")


@click.group("auth")
def auth_group() -> None:
    """Manage Slack credentials and login flow."""


@auth_group.command("status")
@click.pass_obj
def auth_status(app: AppContext) -> None:
    """Show credential file health and auth test status."""

    env_path = DEFAULT_ENV_FILE
    values = _read_env_values(env_path)

    workspace = (values.get("SLACK_WORKSPACE") or "").strip()
    token = (values.get("TOKEN") or "").strip()
    d_cookie = (values.get("D_COOKIE") or "").strip()

    payload: dict[str, Any] = {
        "env_file": str(env_path),
        "file_exists": env_path.is_file(),
        "workspace_present": bool(workspace),
        "token_present": bool(token),
        "d_cookie_present": bool(d_cookie),
        "auth_ok": False,
    }

    if workspace and token and d_cookie:
        try:
            settings = Settings(workspace=workspace, token=token, d_cookie=d_cookie)
            client = SlackClient(settings=settings)
            try:
                auth = client.auth_test()
            finally:
                client.close()

            payload["auth_ok"] = True
            payload["team"] = auth.get("team") or ""
            payload["team_id"] = auth.get("team_id") or ""
            payload["user"] = auth.get("user") or ""
            payload["user_id"] = auth.get("user_id") or ""
        except SlackCLIError as exc:
            payload["auth_error"] = str(exc)

    if app.output_format == "pretty":
        app.console.print(f"[bold]ENV FILE[/]    {env_path}")
        app.console.print(
            f"[bold]EXISTS[/]      {'yes' if payload['file_exists'] else 'no'}"
        )
        app.console.print(
            f"[bold]WORKSPACE[/]   {'present' if payload['workspace_present'] else 'missing'}"
        )
        app.console.print(
            f"[bold]TOKEN[/]       {'present' if payload['token_present'] else 'missing'}"
        )
        app.console.print(
            f"[bold]D_COOKIE[/]    {'present' if payload['d_cookie_present'] else 'missing'}"
        )

        if payload["auth_ok"]:
            app.console.print("[bold]AUTH TEST[/]   ok")
            app.console.print(
                f"[bold]IDENTITY[/]    @{payload.get('user', '')} ({payload.get('user_id', '')})"
            )
            app.console.print(
                f"[bold]WORKSPACE[/]   {payload.get('team', '')} ({payload.get('team_id', '')})"
            )
        elif payload.get("auth_error"):
            app.console.print(f"[bold]AUTH TEST[/]   failed: {payload['auth_error']}")
        else:
            app.console.print("[bold]AUTH TEST[/]   skipped (missing required values)")
        return

    emit_data(
        app,
        payload,
        default_fields=[
            "env_file",
            "file_exists",
            "workspace_present",
            "token_present",
            "d_cookie_present",
            "auth_ok",
            "team",
            "team_id",
            "user",
            "user_id",
            "auth_error",
        ],
    )


@auth_group.command("logout")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def auth_logout(app: AppContext, yes: bool) -> None:
    """Remove local Slack credential file."""

    env_path = DEFAULT_ENV_FILE
    if not env_path.exists():
        app.console.print(f"[dim]No auth file found at {env_path}.[/]")
        return

    if not yes:
        confirmed = click.confirm(
            f"Remove credentials at {env_path}?",
            default=False,
        )
        if not confirmed:
            app.console.print("[dim]Cancelled.[/]")
            return

    env_path.unlink()
    app.console.print(f"[green]Removed credentials:[/] {env_path}")


@auth_group.command("login")
@click.argument("workspace")
@click.pass_obj
def auth_login(app: AppContext, workspace: str) -> None:
    """Open browser login flow, capture credentials, validate, and save."""

    workspace_slug = _normalize_workspace(workspace)
    app.console.print(
        f"Opening browser for workspace [bold]{workspace_slug}[/]. "
        "Complete login, then return to the terminal."
    )

    token, d_cookie, observed_workspace = asyncio.run(
        _capture_auth_values(workspace_slug)
    )

    if observed_workspace and observed_workspace != workspace_slug:
        raise ConfigError(
            "Workspace mismatch during auth capture: "
            f"requested={workspace_slug}, observed={observed_workspace}"
        )

    missing: list[str] = []
    if not token:
        missing.append("TOKEN")
    if not d_cookie:
        missing.append("D_COOKIE")
    if missing:
        missing_text = ", ".join(missing)
        raise SlackCLIError(
            "Auto-capture failed for required value(s): "
            f"{missing_text}. "
            "Ensure Slack is fully loaded in the opened browser tab, then rerun "
            "`slack auth login <workspace>`."
        )

    settings = Settings(workspace=workspace_slug, token=token, d_cookie=d_cookie)
    validator = SlackClient(settings=settings)
    try:
        auth = validator.auth_test()
    finally:
        validator.close()

    _write_auth_file(
        DEFAULT_ENV_FILE,
        workspace=settings.workspace,
        token=settings.token,
        d_cookie=settings.d_cookie,
    )

    app.console.print(f"[green]Saved credentials:[/] {DEFAULT_ENV_FILE}")
    app.console.print(
        "[green]Auth verified:[/] "
        f"team={auth.get('team', '')} user=@{auth.get('user', '')}"
    )


async def _capture_auth_values(
    workspace: str,
) -> tuple[str | None, str | None, str | None]:
    """Open browser login and capture token/cookie from session artifacts."""

    try:
        from pydoll.browser.chromium import Chrome
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise SlackCLIError(
            "pydoll-python is required for `slack auth login`."
        ) from exc

    login_url = f"https://{workspace}.slack.com"
    browser = Chrome(connection_port=9222)

    try:
        if await browser._is_browser_running(2):
            tabs = await browser.get_opened_tabs()
            tab = tabs[0] if tabs else await browser.new_tab()
        else:
            tab = await browser.start()

        await tab.enable_network_events()
        await tab.go_to(login_url)

        click.prompt(
            "Press Enter here after Slack is fully logged in",
            default="",
            show_default=False,
        )

        token = None
        observed_workspace = None
        d_cookie = None

        for _ in range(30):
            logs = await tab.get_network_logs(filter=".slack.com/api/")
            token_candidate, workspace_candidate = _extract_token_and_workspace(logs)
            if token_candidate:
                token = token_candidate
            if workspace_candidate:
                observed_workspace = workspace_candidate

            cookies = await tab.get_cookies()
            d_cookie_candidate = _extract_d_cookie(cookies, workspace)
            if d_cookie_candidate:
                d_cookie = d_cookie_candidate

            if token and d_cookie:
                break
            await asyncio.sleep(1)
    finally:
        await browser.close()

    return token, d_cookie, observed_workspace


def _extract_token_and_workspace(
    logs: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    token = None
    observed_workspace = None

    for log in reversed(logs):
        params = log.get("params") or {}
        request = params.get("request") or {}

        url = request.get("url") or ""
        if not isinstance(url, str) or "/api/" not in url:
            continue

        workspace = _workspace_from_url(url)
        if workspace and observed_workspace is None:
            observed_workspace = workspace

        extracted = _extract_token_from_request(request)
        if extracted:
            token = extracted
            if workspace:
                observed_workspace = workspace
            break

    return token, observed_workspace


def _extract_token_from_request(request: dict[str, Any]) -> str | None:
    headers = request.get("headers")
    if isinstance(headers, dict):
        header_token = _extract_token_from_headers(headers)
        if header_token:
            return header_token

    post_data = request.get("postData")
    if not isinstance(post_data, str) or not post_data:
        return None

    # x-www-form-urlencoded
    parsed = parse_qs(post_data, keep_blank_values=True)
    values = parsed.get("token") or []
    if values and values[0]:
        return values[0]

    # multipart/form-data field: name="token"
    multipart_match = re.search(
        r'name="token"\s*\r?\n\r?\n(?P<token>xox[a-z]-[A-Za-z0-9-]+)',
        post_data,
    )
    if multipart_match:
        return multipart_match.group("token")

    # fallback: token=<xox...> anywhere in payload
    kv_match = re.search(
        r"(?:^|[&\s])token=(?P<token>xox[a-z]-[A-Za-z0-9-]+)", post_data
    )
    if kv_match:
        return kv_match.group("token")

    # final fallback: any xox* token in payload
    generic = XOX_TOKEN_RE.search(post_data)
    if generic:
        return generic.group(0)

    return None


def _extract_token_from_headers(headers: dict[str, Any]) -> str | None:
    for key, value in headers.items():
        if str(key).lower() != "authorization":
            continue
        if not isinstance(value, str):
            continue
        match = XOX_TOKEN_RE.search(value)
        if match:
            return match.group(0)
    return None


def _extract_d_cookie(cookies: list[dict[str, Any]], workspace: str) -> str | None:
    exact_domain = f"{workspace}.slack.com"

    for cookie in cookies:
        if cookie.get("name") != "d":
            continue
        domain = str(cookie.get("domain") or "")
        if domain.lstrip(".") == exact_domain:
            value = str(cookie.get("value") or "")
            if value:
                return value

    for cookie in cookies:
        if cookie.get("name") == "d":
            value = str(cookie.get("value") or "")
            if value:
                return value

    return None


def _workspace_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.endswith(".slack.com"):
        return host.split(".", 1)[0]
    return None


def _normalize_workspace(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ConfigError("Workspace cannot be empty")

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if not host.endswith(".slack.com"):
            raise ConfigError("Workspace URL must be a *.slack.com URL")
        raw = host.split(".", 1)[0]

    raw = raw.lower().removesuffix(".slack.com")
    if not WORKSPACE_RE.match(raw):
        raise ConfigError(
            "Workspace must be a valid Slack workspace slug "
            "(letters, numbers, hyphens)."
        )
    return raw


def _read_env_values(path: Path) -> dict[str, str]:
    if not path.is_file() or dotenv_values is None:
        return {}

    raw_values = dotenv_values(path)
    return {
        key: str(value)
        for key, value in raw_values.items()
        if isinstance(key, str) and value is not None
    }


def _write_auth_file(path: Path, *, workspace: str, token: str, d_cookie: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    lines = [
        f"SLACK_WORKSPACE={workspace}",
        f"TOKEN={token}",
        f"D_COOKIE={d_cookie}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
