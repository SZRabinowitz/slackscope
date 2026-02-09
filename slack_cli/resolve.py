"""Helpers for resolving human-friendly CLI targets to Slack IDs."""

from __future__ import annotations

import re
from typing import Any

from slack_cli.client import SlackClient
from slack_cli.errors import AmbiguousTargetError, NotFoundError


CONVERSATION_ID_RE = re.compile(r"^[CDG][A-Z0-9]+$")
USER_ID_RE = re.compile(r"^U[A-Z0-9]+$")


def resolve_conversation_id(client: SlackClient, target: str) -> str:
    """Resolve #channel, @user DM, or raw conversation ID into channel ID."""

    raw = target.strip()
    if CONVERSATION_ID_RE.match(raw):
        return raw
    if raw.startswith("@"):
        return resolve_dm_id(client, raw)

    needle = raw.removeprefix("#").strip().lower()
    if not needle:
        raise NotFoundError("Conversation name cannot be empty")

    exact = client.find_conversations_by_name(
        needle,
        types=["public_channel", "private_channel"],
        exclude_archived=False,
        max_pages=20,
        max_matches=2,
    )

    if not exact:
        try:
            return resolve_dm_id(client, raw)
        except NotFoundError:
            raise NotFoundError(f"No conversation found for target: {target}")
    if len(exact) > 1:
        candidates = [
            {
                "id": item.get("id"),
                "name": f"#{item.get('name') or item.get('id')}",
                "type": "private" if item.get("is_private") else "channel",
            }
            for item in exact[:8]
        ]
        raise AmbiguousTargetError(
            f"Multiple conversations match {target!r}. Use a conversation ID.",
            candidates,
        )

    resolved = exact[0].get("id")
    if not resolved:
        raise NotFoundError(f"Conversation found for {target} but missing ID")
    return resolved


def resolve_user_id(client: SlackClient, target: str) -> str:
    """Resolve @handle or user ID into Slack user ID."""

    raw = target.strip()
    if USER_ID_RE.match(raw):
        return raw

    needle = raw.removeprefix("@").lower().strip()
    if not needle:
        raise NotFoundError("User handle cannot be empty")

    users = client.users_all()
    exact: list[dict[str, Any]] = []
    for user in users:
        if user.get("deleted"):
            continue
        handle = (user.get("name") or "").lower()
        display = ((user.get("profile") or {}).get("display_name") or "").lower()
        real_name = ((user.get("profile") or {}).get("real_name") or "").lower()
        if needle in {handle, display, real_name}:
            exact.append(user)

    if not exact:
        raise NotFoundError(f"No user found for target: {target}")
    if len(exact) > 1:
        candidates = [
            {
                "id": item.get("id"),
                "handle": f"@{item.get('name')}",
                "name": ((item.get("profile") or {}).get("real_name") or ""),
            }
            for item in exact[:8]
        ]
        raise AmbiguousTargetError(
            f"Multiple users match {target!r}. Use a user ID.",
            candidates,
        )

    user_id = exact[0].get("id")
    if not user_id:
        raise NotFoundError(f"User found for {target} but missing ID")
    return user_id


def resolve_dm_id(client: SlackClient, target: str) -> str:
    """Resolve @user, U*, or D* into a DM conversation ID."""

    raw = target.strip()
    if raw.startswith("D"):
        return raw

    user_id = resolve_user_id(client, raw)
    dm = client.find_dm_by_user_id(user_id, max_pages=20)
    if not dm:
        raise NotFoundError(f"No DM conversation found for user: {target}")

    dm_id = dm.get("id")
    if not dm_id:
        raise NotFoundError(f"DM found for {target} but missing ID")
    return dm_id
