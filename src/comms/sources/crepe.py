from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from comms.config import CrepeConfig
from comms.fx import to_usd
from comms.http import BudgetExceeded, HttpClient, RateLimitError, RobotsDenied
from comms.ids import artist_id, normalize_handle, offering_id
from comms.logging import get_logger
from comms.models import Artist, ArtistBundle, Offering, PricePoint, Seed
from comms.ratelimit import AdaptiveRateLimiter
from comms.registry import register_source
from comms.sources.base import ArtistNotFound, Source, SourceContext, SourceError
from comms.timeutil import now_ts

log = get_logger("source.crepe")

BASE = "https://crepe.cm"
VIKE_RE = re.compile(
    r'<script id="vike_pageContext" type="application/json">(.*?)</script>',
    re.DOTALL,
)


@register_source("crepe")
class CrepeSource(Source):
    site = "crepe"

    def __init__(self, options: CrepeConfig, config) -> None:  # type: ignore[no-untyped-def]
        super().__init__(options, config)
        self.options: CrepeConfig = options
        self.client: HttpClient | None = None

    async def open(self, ctx: SourceContext) -> None:
        self.client = HttpClient(
            self.config.network,
            ctx.budget,
            AdaptiveRateLimiter(self.config.network.requests_per_second),
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None

    def _user_url(self, handle: str) -> str:
        return f"{BASE}/{self.options.language}/@{quote(handle, safe='')}"

    def _type_url(self, handle: str, slug: str) -> str:
        return f"{self._user_url(handle)}/{quote(slug, safe='')}"

    async def _get_page(self, url: str) -> str:
        if self.client is None:
            raise SourceError("CREPE client is not open")
        try:
            response = await self.client.get(url)
        except RobotsDenied as exc:
            raise SourceError(str(exc)) from exc
        if response.status_code == 404:
            raise ArtistNotFound(f"CREPE page not found: {url}", status_code=404)
        if response.status_code >= 400:
            raise SourceError(
                f"CREPE HTTP {response.status_code}: {url}", status_code=response.status_code
            )
        return response.text

    async def discover(self, ctx: SourceContext, limit: int) -> AsyncIterator[Seed]:
        if not self.options.discover_homepage or limit <= 0:
            return
        url = f"{BASE}/{self.options.language}"
        try:
            html = await self._get_page(url)
        except Exception as exc:
            log.warning("CREPE homepage discovery failed: %s", exc)
            return
        page = parse_vike_page(html)
        if page is None:
            log.warning("CREPE homepage did not contain vike_pageContext")
            return
        records = page.get("relayInitialData", {})
        seen: set[str] = set()
        for record in records.values():
            if not isinstance(record, dict) or record.get("__typename") != "User":
                continue
            username = record.get("username")
            if not username:
                continue
            handle = normalize_handle(str(username))
            if not handle or handle.casefold() in seen:
                continue
            seen.add(handle.casefold())
            yield Seed(
                site=self.site,
                handle=handle,
                url=self._user_url(handle),
                source="crepe:homepage",
                priority=4,
            )
            if len(seen) >= limit:
                return

    async def fetch(self, ctx: SourceContext, seed: Seed) -> ArtistBundle:
        handle = normalize_handle(seed.handle)
        user_url = self._user_url(handle)
        html = await self._get_page(user_url)
        page = parse_vike_page(html)
        if page is None:
            raise SourceError(f"CREPE page missing vike_pageContext: {user_url}")
        records = page.get("relayInitialData", {})
        user = _find_user(records, handle)
        if user is None:
            raise ArtistNotFound(f"CREPE user not found: {handle}", status_code=404)

        username = normalize_handle(str(user.get("username") or handle))
        site_user_id = str(user.get("_id") or user.get("id") or "")
        aid = artist_id(self.site, site_user_id or None, username)
        now = now_ts()
        stats = _resolve(records, user.get("statistics"))
        works_count = _optional_int(stats.get("workCount")) if isinstance(stats, dict) else None
        commission_records = _commission_records(records, user)
        tag_names = _unique(
            [tag for record in commission_records for tag in _tag_names(records, record)]
        )
        nsfw_values = [
            _sensitivity_is_nsfw(record.get("sensitivity")) for record in commission_records
        ]
        nsfw = (
            True
            if any(value is True for value in nsfw_values)
            else (False if nsfw_values else None)
        )
        accepts = (
            True
            if any(bool(record.get("inquiryAvailable")) for record in commission_records)
            else None
        )

        artist = Artist(
            artist_id=aid,
            site=self.site,
            site_user_id=site_user_id or None,
            handle=username,
            display_name=user.get("name") or username,
            profile_url=user_url,
            avatar_url=_clean_url(user.get("profileImageUrl")),
            header_url=_clean_url(user.get("headerImageUrl")),
            bio=_doc_text(user.get("bio")),
            tags=tag_names,
            nsfw=nsfw,
            accepts_commissions=accepts,
            works_count=works_count,
            followers_count=None,
            rating=None,
            first_seen=now,
            last_updated=now,
            last_seen=now,
            status="active",
        )

        offerings: list[Offering] = []
        price_points: list[PricePoint] = []
        for index, record in enumerate(commission_records):
            if index >= self.options.max_offerings_per_artist:
                break
            slug = str(record.get("slug") or "")
            detail_record = record
            if self.options.fetch_offering_details and slug:
                try:
                    detail_html = await self._get_page(self._type_url(username, slug))
                    detail_page = parse_vike_page(detail_html)
                    if detail_page is not None:
                        detail_records = detail_page.get("relayInitialData", {})
                        found = _find_commission_type(detail_records, str(record.get("id") or ""))
                        if found is not None:
                            detail_record = found
                            # Detail pages may have a richer tag list.
                            for tag in _tag_names(detail_records, found):
                                if tag not in tag_names:
                                    tag_names.append(tag)
                except (RateLimitError, BudgetExceeded):
                    raise
                except Exception as exc:
                    log.warning("CREPE type detail failed for %s/%s: %s", username, slug, exc)
            offering = _offering_from_record(
                records,
                detail_record,
                artist=artist,
                url=self._type_url(username, slug) if slug else user_url,
                now=now,
                config=self.config,
            )
            if offering is not None:
                offerings.append(offering)
                price_points.append(
                    PricePoint(
                        offering_id=offering.offering_id,
                        artist_id=aid,
                        amount=offering.price_min,
                        currency=offering.currency,
                        amount_usd=offering.price_usd,
                        observed_at=now,
                    )
                )

        # Keep the artist tag list in sync with all tags found on detail pages.
        artist.tags = _unique(tag_names)

        return ArtistBundle(
            artist=artist,
            offerings=offerings,
            works=[],
            price_points=price_points,
            raw=user,
        )


def parse_vike_page(html: str) -> dict[str, Any] | None:
    match = VIKE_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _find_user(records: dict[str, Any], handle: str) -> dict[str, Any] | None:
    root = records.get("client:root")
    if isinstance(root, dict):
        for key, value in root.items():
            if isinstance(key, str) and key.lower().startswith("user(username:"):
                resolved = _resolve(records, value)
                if isinstance(resolved, dict):
                    return resolved
    target = handle.casefold()
    for record in records.values():
        if (
            isinstance(record, dict)
            and record.get("__typename") == "User"
            and str(record.get("username", "")).casefold() == target
        ):
            return record
    return None


def _commission_records(records: dict[str, Any], user: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    refs = user.get("commissionTypes")
    if not isinstance(refs, dict):
        return result
    for ref in refs.get("__refs", []):
        record = records.get(ref)
        if isinstance(record, dict) and record.get("__typename") == "CommissionType":
            result.append(record)
    return result


def _find_commission_type(records: dict[str, Any], commission_id: str) -> dict[str, Any] | None:
    if commission_id:
        record = records.get(commission_id)
        if isinstance(record, dict) and record.get("__typename") == "CommissionType":
            return record
    for record in records.values():
        if (
            isinstance(record, dict)
            and record.get("__typename") == "CommissionType"
            and str(record.get("id")) == commission_id
        ):
            return record
    return None


def _resolve(records: dict[str, Any], value: Any) -> Any:
    if isinstance(value, dict) and "__ref" in value:
        return records.get(value["__ref"])
    return value


def _tag_names(records: dict[str, Any], record: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    refs = record.get("tags")
    if isinstance(refs, dict):
        for ref in refs.get("__refs", []):
            tag = records.get(ref)
            if isinstance(tag, dict):
                name = tag.get("name") or tag.get("key")
                if name:
                    tags.append(str(name))
    return _unique(tags)


def _offering_from_record(
    records: dict[str, Any],
    record: dict[str, Any],
    *,
    artist: Artist,
    url: str,
    now: float,
    config,
) -> Offering | None:  # type: ignore[no-untyped-def]
    commission_id = str(record.get("id") or record.get("slug") or "")
    if not commission_id:
        return None
    title = record.get("name")
    tags = _tag_names(records, record)
    kind = tags[0] if tags else "commission"
    price_min = _optional_int(record.get("minAmount"))
    price_max = _optional_int(record.get("maxAmount"))
    if price_min is None and price_max is not None:
        price_min = price_max
    if price_max is None and price_min is not None:
        price_max = price_min
    price_usd = to_usd(price_min, "KRW", config.currency)
    price_min_usd = to_usd(price_min, "KRW", config.currency)
    price_max_usd = to_usd(price_max, "KRW", config.currency)
    description = record.get("summary") or _doc_text(record.get("content"))
    oid = offering_id(artist.site, artist.artist_id, commission_id, kind)
    return Offering(
        offering_id=oid,
        artist_id=artist.artist_id,
        site=artist.site,
        site_offering_id=commission_id,
        title=str(title) if title else None,
        kind=kind,
        description=description,
        price_min=price_min,
        price_max=price_max,
        currency="KRW",
        price_usd=price_usd,
        price_min_usd=price_min_usd,
        price_max_usd=price_max_usd,
        cover_url=_clean_url(record.get("coverImageUrl")),
        turnaround_days=None,
        slots=None,
        available=_optional_bool(record.get("inquiryAvailable")),
        tags=tags,
        source_url=url,
        first_seen=now,
        last_updated=now,
        active=True,
    )


def _doc_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type in {"paragraph", "heading"} and parts:
                parts.append("\n")
            text = node.get("text")
            if isinstance(text, str):
                parts.append(text)
            content = node.get("content")
            if isinstance(content, list):
                for child in content:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    text = "".join(parts).strip()
    return text or None


def _sensitivity_is_nsfw(value: Any) -> bool:
    if not value:
        return False
    return str(value).upper() not in {"NONE", "SAFE", "GENERAL", "ALL"}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _clean_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.replace("\\/", "/")
