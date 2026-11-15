from __future__ import annotations

import hashlib
import re
import unicodedata

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def stable_id(*parts: object, length: int = 20) -> str:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def prefixed(kind: str, *parts: object, length: int = 20) -> str:
    return f"{kind}_{stable_id(*parts, length=length)}"


def normalize_handle(value: str) -> str:
    return value.strip().lstrip("@").strip()


def safe_filename(value: str, max_length: int = 80) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    text = _SAFE_RE.sub("_", text).strip("._")
    return (text or "item")[:max_length]


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def artist_id(site: str, site_user_id: str | None, handle: str) -> str:
    identity = site_user_id or normalize_handle(handle).casefold()
    return prefixed("artist", site, identity)


def offering_id(site: str, artist: str, site_offering_id: str | None, kind: str) -> str:
    identity = site_offering_id or f"{artist}:{kind}"
    return prefixed("offering", site, identity)


def work_id(site: str, artist: str, site_work_id: str | None, fallback: str) -> str:
    identity = site_work_id or f"{artist}:{fallback}"
    return prefixed("work", site, identity)
