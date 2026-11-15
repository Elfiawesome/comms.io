from __future__ import annotations

from datetime import UTC, datetime


def now_ts() -> float:
    return datetime.now(tz=UTC).timestamp()


def iso_utc(ts: float | None = None) -> str:
    value = now_ts() if ts is None else ts
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def parse_date(value: str | None) -> float | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
    return parse_iso(value)


def human_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    return iso_utc(ts)
