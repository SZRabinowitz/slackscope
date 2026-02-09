"""Helpers for parsing CLI time flags."""

from __future__ import annotations

import re
import time

from slack_cli.errors import SlackCLIError


NUMERIC_TS_RE = re.compile(r"^\d+(?:\.\d+)?$")
DURATION_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[smhdw])$")

UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_time_value(value: str | None, flag_name: str) -> float | None:
    """Parse timestamp or simple duration syntax into epoch seconds."""

    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    if NUMERIC_TS_RE.match(raw):
        return float(raw)

    match = DURATION_RE.match(raw)
    if match:
        amount = int(match.group("amount"))
        unit = match.group("unit")
        return time.time() - (amount * UNIT_SECONDS[unit])

    raise SlackCLIError(
        f"Invalid value for {flag_name}: {value!r}. "
        "Use unix ts (e.g. 1739051292.0042) or duration like 30m, 2h, 1d."
    )


def parse_history_bounds(
    since: str | None, until: str | None
) -> tuple[float | None, float | None]:
    """Parse --since/--until into Slack oldest/latest parameters."""

    oldest = parse_time_value(since, "--since")
    latest = parse_time_value(until, "--until")
    if oldest is not None and latest is not None and oldest > latest:
        raise SlackCLIError("--since cannot be later than --until")
    return oldest, latest
