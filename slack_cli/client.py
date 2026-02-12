"""HTTP client wrapper around Slack Web API methods."""

from __future__ import annotations

import time
from typing import Any, Iterable, Sequence

import httpx

from slack_cli.config import Settings
from slack_cli.errors import NotFoundError, SlackApiError, SlackCLIError


class SlackClient:
    """Small synchronous Slack Web API client."""

    def __init__(self, settings: Settings, verbose: bool = False) -> None:
        self.settings = settings
        self.verbose = verbose
        self.max_retries = 2
        self._http = httpx.Client(
            base_url=settings.api_base,
            timeout=settings.timeout_seconds,
            cookies={"d": settings.d_cookie},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
            },
        )
        self._users_cache: list[dict[str, Any]] | None = None
        self._users_map_cache: dict[str, dict[str, Any]] | None = None
        self._conversation_cache: dict[str, dict[str, Any]] = {}
        self._conversation_snapshot_cache: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        self._http.close()

    def api_url(self, endpoint: str) -> str:
        """Resolve method/path input into a full Slack API URL."""

        raw = endpoint.strip()
        if not raw:
            raise SlackCLIError("API endpoint cannot be empty")

        if raw.startswith("http://") or raw.startswith("https://"):
            return raw

        normalized = raw.lstrip("/")
        if normalized.startswith("api/"):
            normalized = normalized[4:]

        if not normalized:
            raise SlackCLIError("API endpoint cannot be empty")

        return f"{self.settings.api_base}/{normalized}"

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(params or {})
        payload.setdefault("token", self.settings.token)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.post(method, data=payload)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise SlackCLIError(f"Network error calling Slack API: {exc}") from exc

            if response.status_code == 429 and attempt < self.max_retries:
                retry_after = int(response.headers.get("Retry-After", "1"))
                time.sleep(max(retry_after, 1))
                continue

            if response.status_code >= 500 and attempt < self.max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code >= 400:
                raise SlackCLIError(
                    f"Slack HTTP error for {method}: {response.status_code}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise SlackCLIError(
                    f"Slack API returned invalid JSON for {method}"
                ) from exc

            if not data.get("ok", False):
                error = data.get("error", "unknown_error")
                raise SlackApiError(method, error, data)

            return data

        if last_error:
            raise SlackCLIError(str(last_error))
        raise SlackCLIError(f"Slack API request failed for {method}")

    def call_raw(
        self,
        endpoint: str,
        *,
        http_method: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Call a Slack API endpoint and return raw response body."""

        method = http_method.upper().strip() or "POST"
        url = self.api_url(endpoint)

        payload = dict(params or {})
        payload.setdefault("token", self.settings.token)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request_kwargs: dict[str, Any] = (
                {"params": payload} if method == "GET" else {"data": payload}
            )
            try:
                response = self._http.request(method, url, **request_kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise SlackCLIError(f"Network error calling Slack API: {exc}") from exc

            if response.status_code == 429 and attempt < self.max_retries:
                retry_after = int(response.headers.get("Retry-After", "1"))
                time.sleep(max(retry_after, 1))
                continue

            if response.status_code >= 500 and attempt < self.max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue

            return response.text

        if last_error:
            raise SlackCLIError(str(last_error))
        raise SlackCLIError(f"Slack API request failed for {endpoint}")

    def _paginate(
        self,
        method: str,
        params: dict[str, Any],
        item_key: str,
        *,
        max_pages: int | None = None,
    ) -> Iterable[dict[str, Any]]:
        cursor = ""
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            request_params = dict(params)
            if cursor:
                request_params["cursor"] = cursor
            payload = self.call(method, request_params)
            page_count += 1
            for item in payload.get(item_key, []):
                yield item
            next_cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if max_pages is not None and page_count >= max_pages:
                break

    def auth_test(self) -> dict[str, Any]:
        return self.call("auth.test")

    def user_info(self, user_id: str) -> dict[str, Any]:
        return self.call("users.info", {"user": user_id})

    def users_all(self) -> list[dict[str, Any]]:
        if self._users_cache is None:
            self._users_cache = list(
                self._paginate("users.list", {"limit": 200}, "members")
            )
        return list(self._users_cache)

    def users_map(self) -> dict[str, dict[str, Any]]:
        if self._users_map_cache is None:
            self._users_map_cache = {
                user["id"]: user for user in self.users_all() if user.get("id")
            }
        return dict(self._users_map_cache)

    def conversations_list(
        self,
        types: Sequence[str],
        *,
        exclude_archived: bool,
        max_items: int | None = None,
        max_pages: int | None = None,
        joined_only: bool = True,
    ) -> list[dict[str, Any]]:
        if not types:
            return []

        method = "users.conversations" if joined_only else "conversations.list"
        params = {
            "types": ",".join(types),
            "exclude_archived": 1 if exclude_archived else 0,
            "limit": 200,
        }
        channels: list[dict[str, Any]] = []
        for channel in self._paginate(
            method,
            params,
            "channels",
            max_pages=max_pages,
        ):
            channels.append(channel)
            if max_items is not None and len(channels) >= max_items:
                break

        for channel in channels:
            channel_id = channel.get("id")
            if channel_id:
                self._conversation_cache[channel_id] = channel
        return channels

    def find_conversations_by_name(
        self,
        name: str,
        *,
        types: Sequence[str],
        exclude_archived: bool,
        max_pages: int = 20,
        max_matches: int = 2,
        joined_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Scan conversations pages and return up to max_matches exact name matches."""

        needle = name.lower().strip()
        if not needle:
            return []

        method = "users.conversations" if joined_only else "conversations.list"
        cursor = ""
        seen_cursors: set[str] = set()
        page_count = 0
        matches: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {
                "types": ",".join(types),
                "exclude_archived": 1 if exclude_archived else 0,
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor

            payload = self.call(method, params)
            page_count += 1

            for channel in payload.get("channels", []):
                channel_id = channel.get("id")
                if channel_id:
                    self._conversation_cache[channel_id] = channel

                channel_name = (channel.get("name") or "").strip().lower()
                if channel_name == needle:
                    matches.append(channel)
                    if len(matches) >= max_matches:
                        return matches

            next_cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if page_count >= max_pages:
                break

        return matches

    def find_dm_by_user_id(
        self,
        user_id: str,
        *,
        max_pages: int = 20,
        joined_only: bool = True,
    ) -> dict[str, Any] | None:
        """Find the DM conversation for a user with bounded pagination."""

        method = "users.conversations" if joined_only else "conversations.list"
        cursor = ""
        seen_cursors: set[str] = set()
        page_count = 0

        while True:
            params: dict[str, Any] = {
                "types": "im",
                "exclude_archived": 0,
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor

            payload = self.call(method, params)
            page_count += 1

            for channel in payload.get("channels", []):
                channel_id = channel.get("id")
                if channel_id:
                    self._conversation_cache[channel_id] = channel
                if channel.get("user") == user_id:
                    return channel

            next_cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if page_count >= max_pages:
                break

        return None

    def conversation_info(self, channel_id: str) -> dict[str, Any]:
        payload = self.call("conversations.info", {"channel": channel_id})
        channel = payload.get("channel") or self._conversation_cache.get(channel_id, {})
        if channel.get("id"):
            self._conversation_cache[channel["id"]] = channel
        return channel

    def conversation_snapshot(self, channel_id: str) -> dict[str, Any]:
        """Return a conversation object enriched with latest/unread when possible."""

        cached = self._conversation_snapshot_cache.get(channel_id)
        if cached:
            return dict(cached)

        base = self.conversation_info(channel_id)
        snapshot = dict(base)
        snapshot.setdefault("id", channel_id)

        latest = snapshot.get("latest")
        latest_ts = (latest or {}).get("ts") if isinstance(latest, dict) else None
        if not latest_ts:
            history = self.conversation_history(
                channel_id,
                limit=1,
                oldest=None,
                latest=None,
            )
            if history:
                snapshot["latest"] = history[0]
                latest_ts = history[0].get("ts")

        unread = snapshot.get("unread_count_display")
        if unread is None:
            unread = snapshot.get("unread_count")
        if unread is None:
            last_read = snapshot.get("last_read")
            unread = _unread_fallback(last_read, latest_ts)
            snapshot["unread_count"] = unread
            snapshot["unread_count_display"] = unread

        self._conversation_snapshot_cache[channel_id] = snapshot
        return dict(snapshot)

    def conversation_history(
        self,
        channel_id: str,
        *,
        limit: int,
        oldest: float | None,
        latest: float | None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        cursor = ""

        while len(messages) < limit:
            batch_limit = min(200, limit - len(messages))
            params: dict[str, Any] = {
                "channel": channel_id,
                "limit": batch_limit,
            }
            if oldest is not None:
                params["oldest"] = oldest
            if latest is not None:
                params["latest"] = latest
            if cursor:
                params["cursor"] = cursor

            payload = self.call("conversations.history", params)
            batch = payload.get("messages", [])
            messages.extend(batch)

            cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            has_more = bool(payload.get("has_more"))
            if not cursor and not has_more:
                break
            if not batch:
                break

        return messages[:limit]

    def conversation_message(self, channel_id: str, ts: str) -> dict[str, Any]:
        payload = self.call(
            "conversations.history",
            {
                "channel": channel_id,
                "latest": ts,
                "oldest": ts,
                "inclusive": True,
                "limit": 1,
            },
        )
        messages = payload.get("messages") or []
        for message in messages:
            if message.get("ts") == ts:
                return message
        if messages:
            return messages[0]
        raise NotFoundError(f"Message not found in {channel_id} at ts={ts}")

    def conversation_replies(
        self,
        channel_id: str,
        thread_ts: str,
        *,
        limit: int | None = None,
        oldest: float | str | None = None,
        latest: float | str | None = None,
        inclusive: bool | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
        }
        if limit is not None:
            params["limit"] = limit
        if oldest is not None:
            params["oldest"] = oldest
        if latest is not None:
            params["latest"] = latest
        if inclusive is not None:
            params["inclusive"] = bool(inclusive)
        payload = self.call("conversations.replies", params)
        return payload.get("messages", [])


def _unread_fallback(last_read: Any, latest_ts: Any) -> int:
    try:
        if float(latest_ts) > float(last_read):
            return 1
    except (TypeError, ValueError):
        return 0
    return 0
