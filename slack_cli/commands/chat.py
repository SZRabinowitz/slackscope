"""`slack chat ...` commands."""

from __future__ import annotations

from typing import Any

import click

from slack_cli.context import AppContext
from slack_cli.normalize import conversation_label, normalize_chat, normalize_message
from slack_cli.render import (
    emit_data,
    render_chat_list,
    render_chat_show,
    render_history,
    render_message_detail,
)
from slack_cli.resolve import resolve_conversation_id
from slack_cli.timeparse import parse_history_bounds


CHAT_TYPES = {
    "channel": ["public_channel"],
    "private": ["private_channel"],
    "dm": ["im"],
    "mpim": ["mpim"],
    "all": ["public_channel", "private_channel", "im", "mpim"],
}


@click.group("chat")
def chat_group() -> None:
    """List and read conversations."""


@chat_group.command("list")
@click.option(
    "--type",
    "chat_type",
    type=click.Choice(
        ["channel", "private", "dm", "mpim", "all"], case_sensitive=False
    ),
    default="all",
    show_default=True,
)
@click.option("--unread", is_flag=True, help="Show only chats with unread messages.")
@click.option("--limit", type=click.IntRange(1, 500), default=30, show_default=True)
@click.option(
    "--max-text", type=click.IntRange(20, 2000), default=100, show_default=True
)
@click.option("--full-text", is_flag=True, help="Disable truncation in pretty output.")
@click.pass_obj
def chat_list(
    app: AppContext,
    chat_type: str,
    unread: bool,
    limit: int,
    max_text: int,
    full_text: bool,
) -> None:
    """List chats with unread-first sorting."""

    requested_types = CHAT_TYPES[chat_type]
    scan_items = min(max(limit * 8, 120), 1200)
    scan_pages = max(8, min(30, (limit // 5) + 8))
    conversations = app.client.conversations_list(
        requested_types,
        exclude_archived=True,
        max_items=scan_items,
        max_pages=scan_pages,
    )
    users_map = app.client.users_map()

    records: list[dict[str, Any]] = []
    for conversation in conversations:
        enriched = dict(conversation)
        conversation_id = enriched.get("id")
        if conversation_id:
            enriched.update(app.client.conversation_snapshot(conversation_id))

        record = normalize_chat(enriched, users_map)
        if record["type"] in {"channel", "private"} and not record["is_member"]:
            continue
        if unread and int(record.get("unread") or 0) <= 0:
            continue
        records.append(record)

    records.sort(
        key=lambda item: (
            0 if int(item.get("unread") or 0) > 0 else 1,
            -_ts_as_float(item.get("last_ts")),
        )
    )

    total = len(records)
    shown_items = records[:limit]

    if app.output_format == "pretty":
        render_chat_list(
            app.console,
            shown_items,
            shown=len(shown_items),
            total=total,
            chat_type=chat_type,
            max_text=max_text,
            full_text=full_text,
            title="CHATS",
        )
    else:
        emit_data(
            app,
            shown_items,
            default_fields=[
                "id",
                "type",
                "name",
                "unread",
                "last_ts",
                "last_user",
                "last_text",
            ],
        )


@chat_group.command("show")
@click.argument("chat")
@click.pass_obj
def chat_show(app: AppContext, chat: str) -> None:
    """Show metadata for a conversation."""

    conversation_id = resolve_conversation_id(app.client, chat)
    conversation = app.client.conversation_snapshot(conversation_id)
    users_map = app.client.users_map()

    record = normalize_chat(conversation, users_map)

    if app.output_format == "pretty":
        render_chat_show(app.console, record)
    else:
        emit_data(
            app,
            record,
            default_fields=[
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
            ],
        )


@chat_group.command("history")
@click.argument("chat")
@click.option("--limit", type=click.IntRange(1, 500), default=30, show_default=True)
@click.option("--since", help="Oldest bound: unix ts or duration (e.g. 2h, 1d).")
@click.option("--until", help="Latest bound: unix ts or duration (e.g. 30m).")
@click.option(
    "--inline-replies", type=click.IntRange(0, 20), default=2, show_default=True
)
@click.option(
    "--max-inline-threads", type=click.IntRange(0, 50), default=8, show_default=True
)
@click.option(
    "--max-text", type=click.IntRange(20, 4000), default=180, show_default=True
)
@click.option("--full-text", is_flag=True, help="Disable truncation in pretty output.")
@click.pass_obj
def chat_history(
    app: AppContext,
    chat: str,
    limit: int,
    since: str | None,
    until: str | None,
    inline_replies: int,
    max_inline_threads: int,
    max_text: int,
    full_text: bool,
) -> None:
    """Show messages from a chat with optional inline thread previews."""

    oldest, latest = parse_history_bounds(since, until)
    conversation_id = resolve_conversation_id(app.client, chat)
    conversation = app.client.conversation_info(conversation_id)
    users_map = app.client.users_map()

    raw_messages = app.client.conversation_history(
        conversation_id,
        limit=limit,
        oldest=oldest,
        latest=latest,
    )
    messages = [
        normalize_message(msg, conversation_id, users_map) for msg in raw_messages
    ]
    messages.sort(key=lambda item: _ts_as_float(item.get("ts")))
    inline_map = _collect_inline_replies(
        app=app,
        messages=messages,
        conversation_id=conversation_id,
        users_map=users_map,
        inline_replies=inline_replies,
        max_inline_threads=max_inline_threads,
    )

    if app.output_format == "pretty":
        label = conversation_label(conversation, users_map)
        header = f"{label} ({conversation_id}) latest {len(messages)}"
        render_history(
            app.console,
            header=header,
            messages=messages,
            inline_replies=inline_map,
            max_text=max_text,
            full_text=full_text,
        )
    else:
        emit_data(
            app,
            _inject_inline_replies(messages, inline_map),
            default_fields=[
                "chat_id",
                "ts",
                "author",
                "text",
                "thread_ts",
                "reply_count",
                "subtype",
                "inline_replies",
                "inline_remaining",
            ],
        )


@chat_group.command("message")
@click.argument("chat")
@click.argument("ts")
@click.pass_obj
def chat_message(app: AppContext, chat: str, ts: str) -> None:
    """Fetch one specific message with full text."""

    conversation_id = resolve_conversation_id(app.client, chat)
    conversation = app.client.conversation_info(conversation_id)
    users_map = app.client.users_map()

    raw_message = app.client.conversation_message(conversation_id, ts)
    message = normalize_message(raw_message, conversation_id, users_map)

    if app.output_format == "pretty":
        label = conversation_label(conversation, users_map)
        header = f"{label} ({conversation_id})"
        render_message_detail(app.console, header=header, message=message)
    else:
        emit_data(
            app,
            message,
            default_fields=[
                "chat_id",
                "ts",
                "author",
                "author_id",
                "text",
                "thread_ts",
                "reply_count",
                "subtype",
                "edited",
            ],
        )


def _collect_inline_replies(
    *,
    app: AppContext,
    messages: list[dict[str, Any]],
    conversation_id: str,
    users_map: dict[str, dict[str, Any]],
    inline_replies: int,
    max_inline_threads: int,
) -> dict[str, dict[str, Any]]:
    inline_map: dict[str, dict[str, Any]] = {}
    if inline_replies <= 0 or max_inline_threads <= 0:
        return inline_map

    parents = [
        item
        for item in messages
        if item.get("is_thread_parent") and int(item.get("reply_count") or 0) > 0
    ]
    for parent in parents[:max_inline_threads]:
        thread_ts = parent.get("thread_ts")
        if not thread_ts:
            continue

        raw_replies = app.client.conversation_replies(
            conversation_id,
            thread_ts,
            limit=inline_replies,
            oldest=thread_ts,
            inclusive=True,
        )
        filtered = [
            reply for reply in raw_replies if reply.get("ts") != parent.get("ts")
        ]
        selected = [
            normalize_message(reply, conversation_id, users_map)
            for reply in filtered[:inline_replies]
        ]
        remaining = max(int(parent.get("reply_count") or 0) - len(selected), 0)
        inline_map[parent.get("ts") or ""] = {
            "replies": selected,
            "remaining": remaining,
        }

    return inline_map


def _inject_inline_replies(
    messages: list[dict[str, Any]],
    inline_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for message in messages:
        row = dict(message)
        thread = inline_map.get(message.get("ts") or "")
        if thread:
            row["inline_replies"] = thread.get("replies", [])
            row["inline_remaining"] = thread.get("remaining", 0)
        rows.append(row)
    return rows


def _ts_as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
