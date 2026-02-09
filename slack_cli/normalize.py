"""Normalization helpers for Slack payloads."""

from __future__ import annotations

from typing import Any


def collapse_text(text: str) -> str:
    """Convert multiline message text into a compact single-line preview."""

    normalized = text.replace("\r", "\n")
    pieces = [part.strip() for part in normalized.split("\n") if part.strip()]
    return " ".join(pieces)


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate with ellipsis while avoiding tiny negative slices."""

    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3].rstrip()}..."


def preview_text(text: str, max_chars: int, full_text: bool) -> str:
    """Return either full text or compact preview according to flags."""

    if full_text:
        return text
    return truncate_text(collapse_text(text), max_chars)


def extract_message_text(message: dict[str, Any]) -> str:
    """Extract best-effort textual content from Slack message payloads."""

    attachment_preview = _format_file_fallback(message.get("files"))

    text = message.get("text")
    if isinstance(text, str) and text.strip():
        if attachment_preview:
            return f"{text}\n{attachment_preview}"
        return text

    block_text: list[str] = []
    for block in message.get("blocks") or []:
        maybe_text = _extract_block_text(block)
        if maybe_text:
            block_text.append(maybe_text)

    if block_text:
        body = "\n".join(block_text)
        if attachment_preview:
            return f"{body}\n{attachment_preview}"
        return body

    return attachment_preview


def _extract_block_text(block: dict[str, Any]) -> str:
    text_node = block.get("text")
    if isinstance(text_node, dict):
        value = text_node.get("text")
        if isinstance(value, str):
            return value

    pieces: list[str] = []
    for field in block.get("fields") or []:
        if isinstance(field, dict):
            maybe_text = field.get("text")
            if isinstance(maybe_text, str):
                pieces.append(maybe_text)
    return " ".join(pieces)


def _format_file_fallback(files: Any) -> str:
    if not isinstance(files, list) or not files:
        return ""

    first = files[0] if isinstance(files[0], dict) else {}
    title = str(first.get("title") or first.get("name") or "file")
    pretty_type = str(first.get("pretty_type") or first.get("filetype") or "file")

    size = first.get("size")
    size_label = _human_bytes(size) if isinstance(size, (int, float)) else ""
    details = pretty_type
    if size_label:
        details = f"{details}, {size_label}"

    extra_count = max(len(files) - 1, 0)
    extra_suffix = ""
    if extra_count:
        plural = "s" if extra_count != 1 else ""
        extra_suffix = f" +{extra_count} more file{plural}"

    return f"📎 {title} ({details}){extra_suffix}"


def _human_bytes(size: int | float) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024.0
        index += 1

    if index == 0:
        return f"{int(value)} {units[index]}"
    if value >= 10:
        return f"{value:.0f} {units[index]}"
    return f"{value:.1f} {units[index]}"


def conversation_kind(conversation: dict[str, Any]) -> str:
    if conversation.get("is_im"):
        return "dm"
    if conversation.get("is_mpim"):
        return "mpdm"
    if conversation.get("is_private"):
        return "private"
    return "channel"


def user_label(user_id: str | None, users_map: dict[str, dict[str, Any]]) -> str:
    if not user_id:
        return "@unknown"
    user = users_map.get(user_id)
    if not user:
        return f"@{user_id}"
    handle = user.get("name") or user_id
    return f"@{handle}"


def conversation_label(
    conversation: dict[str, Any], users_map: dict[str, dict[str, Any]]
) -> str:
    kind = conversation_kind(conversation)
    if kind == "dm":
        return user_label(conversation.get("user"), users_map)

    name = conversation.get("name") or conversation.get("id") or "unknown"
    if kind in {"channel", "private"}:
        return f"#{name}"
    return name


def normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    profile = user.get("profile") or {}
    return {
        "id": user.get("id"),
        "handle": f"@{user.get('name') or user.get('id')}",
        "name": profile.get("real_name")
        or profile.get("display_name")
        or user.get("name")
        or "",
        "email": profile.get("email") or "",
        "status": "deleted"
        if user.get("deleted")
        else "bot"
        if user.get("is_bot")
        else "away"
        if user.get("presence") == "away"
        else "active",
    }


def normalize_chat(
    conversation: dict[str, Any], users_map: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    latest = conversation.get("latest") or {}
    unread = conversation.get("unread_count_display")
    if unread is None:
        unread = conversation.get("unread_count")
    if unread is None:
        unread = 0

    topic = conversation.get("topic") or {}
    purpose = conversation.get("purpose") or {}

    return {
        "id": conversation.get("id"),
        "type": conversation_kind(conversation),
        "name": conversation_label(conversation, users_map),
        "is_member": bool(conversation.get("is_member", True)),
        "is_archived": bool(conversation.get("is_archived", False)),
        "unread": int(unread),
        "last_ts": latest.get("ts") or conversation.get("last_read") or "",
        "last_text": extract_message_text(latest),
        "last_user": user_label(latest.get("user"), users_map),
        "members": conversation.get("num_members"),
        "topic": topic.get("value") or "",
        "purpose": purpose.get("value") or "",
    }


def normalize_message(
    message: dict[str, Any],
    chat_id: str,
    users_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ts = message.get("ts") or ""
    thread_ts = message.get("thread_ts") or ts
    text = extract_message_text(message)
    reply_count = int(message.get("reply_count") or 0)

    author_id = message.get("user")
    author = user_label(author_id, users_map)
    if not author_id and message.get("bot_id"):
        author = f"bot:{message['bot_id']}"

    return {
        "chat_id": chat_id,
        "ts": ts,
        "thread_ts": thread_ts,
        "author": author,
        "author_id": author_id or message.get("bot_id") or "",
        "text": text,
        "subtype": message.get("subtype") or "",
        "reply_count": reply_count,
        "is_thread_parent": bool(reply_count and ts == thread_ts),
        "edited": bool(message.get("edited")),
    }


def normalize_me(
    auth_payload: dict[str, Any], user_payload: dict[str, Any], workspace: str
) -> dict[str, Any]:
    user = user_payload.get("user") or {}
    profile = user.get("profile") or {}
    return {
        "workspace": workspace,
        "team": auth_payload.get("team") or "",
        "team_id": auth_payload.get("team_id") or "",
        "user": f"@{user.get('name') or auth_payload.get('user') or auth_payload.get('user_id') or ''}",
        "user_id": auth_payload.get("user_id") or "",
        "email": profile.get("email") or "",
        "tz": user.get("tz") or "",
        "token_ok": True,
        "cookie_ok": True,
    }
