"""Output rendering for pretty and structured CLI formats."""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import click
from rich.markdown import Markdown
from rich.markup import escape

from slack_cli.context import AppContext
from slack_cli.normalize import preview_text


def emit_data(
    app: AppContext,
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    default_fields: list[str] | None = None,
) -> None:
    """Emit payload in json/jsonl/tsv depending on global format."""

    if app.output_format == "json":
        click.echo(
            json.dumps(_apply_fields(payload, app.fields, default_fields), indent=2)
        )
        return

    if app.output_format == "jsonl":
        if isinstance(payload, list):
            rows = _apply_fields(payload, app.fields, default_fields)
            for row in rows:
                click.echo(json.dumps(row, separators=(",", ":")))
        else:
            row = _apply_fields(payload, app.fields, default_fields)
            click.echo(json.dumps(row, separators=(",", ":")))
        return

    if app.output_format == "tsv":
        _emit_tsv(payload, app.fields, default_fields)
        return

    raise RuntimeError(f"emit_data called for unsupported format: {app.output_format}")


def render_me(console, item: dict[str, Any]) -> None:
    console.print(
        f"[bold]WORKSPACE[/]  [cyan]{escape(item.get('workspace', ''))}[/] ({item.get('team_id', '')})"
    )
    console.print(f"[bold]TEAM[/]       {escape(item.get('team', ''))}")
    console.print(
        f"[bold]USER[/]       [green]{escape(item.get('user', ''))}[/] ({item.get('user_id', '')})"
    )
    if item.get("email"):
        console.print(f"[bold]EMAIL[/]      {escape(item['email'])}")
    if item.get("tz"):
        console.print(f"[bold]TZ[/]         {escape(item['tz'])}")
    console.print("[bold]AUTH[/]       token:ok cookie_d:ok")


def render_users(
    console, users: list[dict[str, Any]], *, shown: int, total: int
) -> None:
    console.print(f"[bold]USERS[/] [dim](showing {shown} of {total})[/]")
    if not users:
        console.print("[dim]No users found.[/]")
        return

    for user in users:
        status = user.get("status", "")
        status_color = (
            "green" if status == "active" else "yellow" if status == "away" else "red"
        )
        console.print(
            f"[cyan]{user.get('id', '')}[/]  "
            f"[bold]{escape(user.get('handle', ''))}[/]  "
            f"{escape(user.get('name', ''))}  "
            f"[{status_color}]{status}[/]"
        )


def render_chat_list(
    console,
    chats: list[dict[str, Any]],
    *,
    shown: int,
    total: int,
    chat_type: str,
    max_text: int,
    full_text: bool,
    title: str,
) -> None:
    console.print(
        f"[bold]{title}[/] [dim](showing {shown} of {total}, type={chat_type}, archived=no)[/]"
    )
    if not chats:
        console.print("[dim]No conversations found.[/]")
        return

    name_width = _chat_name_width(chats)

    for chat in chats:
        unread = int(chat.get("unread") or 0)
        marker = "[red]![/]" if unread > 0 else " "
        text = preview_text(
            _slack_to_plain(chat.get("last_text") or ""),
            max_text,
            full_text,
        )
        last_time = _activity_time(chat.get("last_ts") or "")
        kind = _clip_and_pad(str(chat.get("type") or ""), 7)
        chat_id = _clip_and_pad(str(chat.get("id") or ""), 11)
        name = _clip_and_pad(str(chat.get("name") or ""), name_width)
        unread_color = "red" if unread > 0 else "green"
        line = (
            f"{marker} "
            f"[magenta]{escape(kind)}[/] "
            f"[cyan]{escape(chat_id)}[/] "
            f"[bold]{escape(name)}[/] "
            f"[{unread_color}]u:{unread:>2}[/] "
            f"[dim]{escape(last_time)}[/]"
        )
        if text:
            line = f"{line}    {escape(text)}"
        console.print(line)


def render_chat_show(console, chat: dict[str, Any]) -> None:
    order = [
        "id",
        "type",
        "name",
        "is_member",
        "is_archived",
        "members",
        "unread",
        "last_ts",
        "last_user",
        "last_text",
        "topic",
        "purpose",
    ]
    for key in order:
        if key in chat and chat[key] not in (None, ""):
            console.print(f"[bold]{key:<10}[/] {escape(str(chat[key]))}")


def render_history(
    console,
    *,
    header: str,
    messages: list[dict[str, Any]],
    inline_replies: dict[str, dict[str, Any]],
    max_text: int,
    full_text: bool,
) -> None:
    if header:
        console.print(f"[bold]{escape(header)}[/]")
    if not messages:
        console.print("[dim]No messages found.[/]")
        return

    ts_width, author_width, meta_width = _history_column_widths(
        messages, inline_replies
    )
    current_day: date | None = None

    for message in messages:
        message_ts = str(message.get("ts") or "")
        message_day = _day_for_ts(message_ts)
        if message_day != current_day:
            if current_day is not None:
                console.print("")
            console.print(f"[bold]{_day_label(message_day)}[/]")
            current_day = message_day

        text = preview_text(
            _slack_to_plain(message.get("text") or ""), max_text, full_text
        )
        suffix_bits: list[str] = []
        if message.get("is_thread_parent") and message.get("reply_count"):
            suffix_bits.append(f"{message['reply_count']} replies")
        if message.get("edited"):
            suffix_bits.append("edited")
        subtype = str(message.get("subtype") or "")
        if subtype and (not text or subtype not in {"bot_message"}):
            suffix_bits.append(subtype)
        suffix = f" [dim]({' | '.join(suffix_bits)})[/]" if suffix_bits else ""

        meta = _render_meta(
            clock=_clock_time(message_ts),
            ts=message_ts,
            author=str(message.get("author") or ""),
            ts_width=ts_width,
            author_width=author_width,
        )

        console.print(f"  {meta}    {escape(text)}{suffix}")

        thread = inline_replies.get(message_ts)
        if not thread:
            continue

        for reply in thread.get("replies", []):
            reply_ts = str(reply.get("ts") or "")
            reply_text = preview_text(
                _slack_to_plain(reply.get("text") or ""),
                max_text,
                full_text,
            )
            reply_meta = _render_meta(
                clock=_clock_time(reply_ts),
                ts=reply_ts,
                author=str(reply.get("author") or ""),
                ts_width=ts_width,
                author_width=author_width,
            )
            console.print(
                f"     [dim]┃[/] [dim]↳[/] {reply_meta}    {escape(reply_text)}"
            )

        remaining = int(thread.get("remaining") or 0)
        if remaining > 0:
            console.print(
                f"     [dim]┃[/] [dim]↳[/] {' ' * meta_width}    "
                f"[dim]... +{remaining} more (use thread show)[/]"
            )


def render_message_detail(console, *, header: str, message: dict[str, Any]) -> None:
    console.print(f"[bold]{escape(header)}[/]")

    ts = str(message.get("ts") or "")
    author = str(message.get("author") or "")
    meta = _render_meta(
        clock=_clock_time(ts),
        ts=ts,
        author=author,
        ts_width=max(16, len(ts)),
        author_width=max(16, min(30, len(author))),
    )
    console.print(f"  {meta}")
    if message.get("thread_ts"):
        console.print(f"[bold]thread_ts[/] {message.get('thread_ts', '')}")
    if message.get("subtype"):
        console.print(f"[bold]subtype[/] {escape(message.get('subtype', ''))}")
    if message.get("edited"):
        console.print("[bold]edited[/] true")

    console.print("")
    text = message.get("text") or ""
    if text:
        console.print(Markdown(_slack_to_markdown(text), hyperlinks=True))
    else:
        console.print("[dim](no text content)[/]")


def render_thread(
    console,
    *,
    header: str,
    root: dict[str, Any],
    replies: list[dict[str, Any]],
    max_text: int,
    full_text: bool,
) -> None:
    root_ts = str(root.get("ts") or "")
    render_history(
        console,
        header=header,
        messages=[root],
        inline_replies={root_ts: {"replies": replies, "remaining": 0}},
        max_text=max_text,
        full_text=full_text,
    )


def render_candidates(console, candidates: Iterable[dict[str, Any]]) -> None:
    console.print("[bold]Candidates:[/]")
    for item in candidates:
        bits = [
            str(item.get("id", "")),
            str(item.get("name", "")),
            str(item.get("type", "")),
        ]
        cleaned = [bit for bit in bits if bit]
        console.print(f"  - {escape('  '.join(cleaned))}")


SLACK_LINK_WITH_LABEL_RE = re.compile(r"<([^|>]+)\|([^>]+)>")
SLACK_PLAIN_LINK_RE = re.compile(r"<(https?://[^>]+)>")
SLACK_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")
SLACK_SPECIAL_RE = re.compile(r"<!([a-zA-Z0-9_]+)>")
SLACK_CHANNEL_RE = re.compile(r"<#([A-Z0-9]+)\|([^>]+)>")


def _history_column_widths(
    messages: list[dict[str, Any]],
    inline_replies: dict[str, dict[str, Any]],
) -> tuple[int, int, int]:
    ts_len = 16
    author_len = 16

    for message in messages:
        ts_len = max(ts_len, len(str(message.get("ts") or "")))
        author_len = max(author_len, len(str(message.get("author") or "")))
        thread = inline_replies.get(str(message.get("ts") or "")) or {}
        for reply in thread.get("replies", []):
            ts_len = max(ts_len, len(str(reply.get("ts") or "")))
            author_len = max(author_len, len(str(reply.get("author") or "")))

    ts_width = min(max(ts_len, 16), 20)
    author_width = min(max(author_len, 16), 28)
    meta_width = 5 + 1 + ts_width + 1 + author_width
    return ts_width, author_width, meta_width


def _render_meta(
    *,
    clock: str,
    ts: str,
    author: str,
    ts_width: int,
    author_width: int,
) -> str:
    author_block = _clip_and_pad(author, author_width)
    ts_block = _clip_and_pad(ts, ts_width)
    return (
        f"[dim]{clock:>5}[/] "
        f"[cyan]{escape(ts_block)}[/] "
        f"[bold]{escape(author_block)}[/]"
    )


def _clip_and_pad(value: str, width: int) -> str:
    if len(value) <= width:
        return value.ljust(width)
    if width <= 3:
        return value[:width]
    return f"{value[: width - 3]}..."


def _day_for_ts(ts: str) -> date | None:
    try:
        return datetime.fromtimestamp(float(ts)).date()
    except (TypeError, ValueError):
        return None


def _day_label(day: date | None) -> str:
    if day is None:
        return "Unknown Day"
    today = datetime.now().date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return day.strftime("%b %d")


def _clock_time(ts: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except (TypeError, ValueError):
        return "--:--"


def _slack_to_plain(text: str) -> str:
    if not text:
        return ""
    output = html.unescape(text)
    output = SLACK_CHANNEL_RE.sub(r"#\2", output)
    output = SLACK_LINK_WITH_LABEL_RE.sub(_replace_link_plain, output)
    output = SLACK_PLAIN_LINK_RE.sub(r"\1", output)
    output = SLACK_MENTION_RE.sub(r"@\1", output)
    output = SLACK_SPECIAL_RE.sub(_replace_special, output)
    return output


def _slack_to_markdown(text: str) -> str:
    if not text:
        return ""
    output = html.unescape(text)
    output = SLACK_CHANNEL_RE.sub(r"#\2", output)
    output = SLACK_LINK_WITH_LABEL_RE.sub(_replace_link_markdown, output)
    output = SLACK_PLAIN_LINK_RE.sub(r"\1", output)
    output = SLACK_MENTION_RE.sub(r"@\1", output)
    output = SLACK_SPECIAL_RE.sub(_replace_special, output)
    return _normalize_code_fences(output)


def _normalize_code_fences(text: str) -> str:
    parts = text.split("```")
    if len(parts) < 3 or len(parts) % 2 == 0:
        return text

    output: list[str] = [parts[0]]
    for index, part in enumerate(parts[1:], start=1):
        if index % 2 == 1:
            code = part
            if code and not code.startswith("\n"):
                code = f"\n{code}"
            if code and not code.endswith("\n"):
                code = f"{code}\n"
            output.append(f"```{code}```")
            continue
        output.append(part)
    return "".join(output)


def _replace_link_plain(match: re.Match[str]) -> str:
    target = match.group(1)
    label = match.group(2)
    if target.startswith("http://") or target.startswith("https://"):
        return label
    return label


def _replace_link_markdown(match: re.Match[str]) -> str:
    target = match.group(1)
    label = match.group(2)
    if target.startswith("http://") or target.startswith("https://"):
        return f"[{label}]({target})"
    return label


def _replace_special(match: re.Match[str]) -> str:
    token = match.group(1).lower()
    if token in {"here", "channel", "everyone"}:
        return f"@{token}"
    if token.startswith("subteam^"):
        return "@group"
    return f"!{token}"


def _chat_name_width(chats: list[dict[str, Any]]) -> int:
    width = 18
    for chat in chats:
        width = max(width, len(str(chat.get("name") or "")))
    return min(width, 34)


def _activity_time(ts: str) -> str:
    try:
        stamp = float(ts)
    except (TypeError, ValueError):
        return "-- -- --:--"

    dt = datetime.fromtimestamp(stamp)
    now = datetime.now()
    if dt.date() == now.date():
        return f"Today {dt.strftime('%H:%M')}"
    return dt.strftime("%m-%d %H:%M")


def _apply_fields(
    payload: dict[str, Any] | list[dict[str, Any]],
    selected_fields: list[str] | None,
    default_fields: list[str] | None,
) -> dict[str, Any] | list[dict[str, Any]]:
    fields = selected_fields or default_fields
    if not fields:
        return payload

    if isinstance(payload, list):
        return [{field: row.get(field) for field in fields} for row in payload]
    return {field: payload.get(field) for field in fields}


def _emit_tsv(
    payload: dict[str, Any] | list[dict[str, Any]],
    selected_fields: list[str] | None,
    default_fields: list[str] | None,
) -> None:
    rows = payload if isinstance(payload, list) else [payload]
    if not rows:
        return

    fields = selected_fields or default_fields or list(rows[0].keys())
    click.echo("\t".join(fields))

    for row in rows:
        values = [_tsv_cell(row.get(field)) for field in fields]
        click.echo("\t".join(values))


def _tsv_cell(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value)
    return raw.replace("\t", " ").replace("\n", " ")
