"""`slack thread ...` commands."""

from __future__ import annotations

from typing import Any

import click

from slack_cli.context import AppContext
from slack_cli.normalize import conversation_label, normalize_message
from slack_cli.render import emit_data, render_thread
from slack_cli.resolve import resolve_conversation_id


def _ts_as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@click.group("thread")
def thread_group() -> None:
    """Read thread replies."""


@thread_group.command("show")
@click.argument("chat")
@click.argument("ts")
@click.option(
    "--max-text", type=click.IntRange(20, 4000), default=180, show_default=True
)
@click.option("--full-text", is_flag=True, help="Disable truncation in pretty output.")
@click.pass_obj
def thread_show(
    app: AppContext, chat: str, ts: str, max_text: int, full_text: bool
) -> None:
    """Show one full thread (root + replies)."""

    conversation_id = resolve_conversation_id(app.client, chat)
    conversation = app.client.conversation_info(conversation_id)
    users_map = app.client.users_map()

    raw_messages = app.client.conversation_replies(conversation_id, ts)
    if not raw_messages:
        payload = {
            "chat_id": conversation_id,
            "thread_ts": ts,
            "root": None,
            "replies": [],
        }
        if app.output_format == "pretty":
            app.console.print("[dim]No thread messages found.[/]")
        else:
            emit_data(app, payload)
        return

    normalized = [
        normalize_message(message, conversation_id, users_map)
        for message in raw_messages
    ]
    root = normalized[0]
    replies = normalized[1:]
    replies.sort(key=lambda item: _ts_as_float(item.get("ts")))

    if app.output_format == "pretty":
        label = conversation_label(conversation, users_map)
        header = f"THREAD {label} {ts} replies:{len(replies)}"
        render_thread(
            app.console,
            header=header,
            root=root,
            replies=replies,
            max_text=max_text,
            full_text=full_text,
        )
    else:
        emit_data(
            app,
            {
                "chat_id": conversation_id,
                "thread_ts": ts,
                "root": root,
                "replies": replies,
            },
        )
