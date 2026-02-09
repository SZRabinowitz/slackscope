"""`slack users ...` commands."""

from __future__ import annotations

import click

from slack_cli.context import AppContext
from slack_cli.normalize import normalize_user
from slack_cli.render import emit_data, render_users


@click.group("users")
def users_group() -> None:
    """List and inspect users."""


@users_group.command("list")
@click.option("--query", help="Filter users by id, handle, name, or email.")
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
@click.pass_obj
def users_list(app: AppContext, query: str | None, limit: int) -> None:
    """List workspace users."""

    normalized = [
        normalize_user(user)
        for user in app.client.users_all()
        if not user.get("deleted")
    ]
    normalized.sort(key=lambda item: (item.get("handle") or "").lower())

    if query:
        needle = query.lower().strip()

        def _matches(user: dict) -> bool:
            haystack = " ".join(
                [
                    user.get("id") or "",
                    user.get("handle") or "",
                    user.get("name") or "",
                    user.get("email") or "",
                ]
            ).lower()
            return needle in haystack

        normalized = [user for user in normalized if _matches(user)]

    total = len(normalized)
    shown_items = normalized[:limit]

    if app.output_format == "pretty":
        render_users(app.console, shown_items, shown=len(shown_items), total=total)
    else:
        emit_data(
            app,
            shown_items,
            default_fields=["id", "handle", "name", "email", "status"],
        )
