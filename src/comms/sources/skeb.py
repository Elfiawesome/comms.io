from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession

from comms.config import SkebConfig
from comms.fx import to_usd
from comms.http import BudgetExceeded, RateLimitError
from comms.ids import artist_id, normalize_handle, offering_id, stable_id, work_id
from comms.logging import get_logger
from comms.models import Artist, ArtistBundle, Offering, PricePoint, Seed, Work
from comms.ratelimit import AdaptiveRateLimiter
from comms.registry import register_source
from comms.sources.base import ArtistNotFound, Source, SourceContext, SourceError
from comms.timeutil import now_ts, parse_iso

log = get_logger("source.skeb")

BASE = "https://skeb.jp"
API = f"{BASE}/api"
COOKIE_RE = re.compile(r"request_key=([^;\"'\s]+)")
WORK_PATH_RE = re.compile(r"/@([^/]+)/works/(\d+)")


@register_source("skeb")
class SkebSource(Source):
    site = "skeb"

    def __init__(self, options: SkebConfig, config) -> None:  # type: ignore[no-untyped-def]
        super().__init__(options, config)
        self.options: SkebConfig = options
        self.session: AsyncSession | None = None
        self.limiter = AdaptiveRateLimiter(config.network.requests_per_second)

    async def open(self, ctx: SourceContext) -> None:
        self.session = AsyncSession(impersonate=self.options.impersonate)
        if self.options.extract_cookie:
            await self._extract_cookie(ctx)

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _extract_cookie(self, ctx: SourceContext) -> None:
        if self.session is None:
            return
        try:
            ctx.budget.check()
            await self.limiter.acquire()
            ctx.budget.record_request()
            response = await self.session.get(BASE, timeout=self.config.network.timeout_seconds)
            match = COOKIE_RE.search(response.text)
            if not match:
                log.warning(
                    "request_key cookie not found on homepage (HTTP %s)", response.status_code
                )
                return
            self.session.cookies.set("request_key", match.group(1), domain="skeb.jp")
            log.info("Skeb request_key cookie extracted")
        except Exception as exc:
            log.warning("Could not extract Skeb cookie: %s", exc)

    async def _refresh_cookie(self, ctx: SourceContext) -> None:
        log.info("Refreshing Skeb request_key cookie")
        await self._extract_cookie(ctx)

    def _headers(self, referer: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": "Bearer null",
            "Accept": "application/json, text/plain, */*",
            "Referer": referer or f"{BASE}/",
        }
        return headers

    async def _get(
        self, endpoint: str, *, referer: str | None = None, retry_auth: bool = True
    ) -> Any:
        if self.session is None:
            raise SourceError("Skeb session is not open")
        ctx = getattr(self, "_ctx", None)
        if ctx is None:
            raise SourceError("Skeb source context is not initialized")
        url = endpoint if endpoint.startswith("http") else f"{API}/{endpoint.lstrip('/')}"
        ctx.budget.check()
        await self.limiter.acquire()
        ctx.budget.record_request()
        try:
            response = await self.session.get(
                url,
                headers=self._headers(referer),
                timeout=self.config.network.timeout_seconds,
            )
        except Exception as exc:
            raise SourceError(f"Skeb request failed: {exc}") from exc

        if response.status_code == 429:
            self.limiter.report_429()
            raise RateLimitError(f"429 Too Many Requests: {url}")
        if response.status_code in (401, 403) and retry_auth:
            await self._refresh_cookie(ctx)
            return await self._get(endpoint, referer=referer, retry_auth=False)
        if response.status_code == 404:
            raise ArtistNotFound(f"Skeb profile not found: {url}", status_code=404)
        if response.status_code >= 400:
            raise SourceError(
                f"Skeb HTTP {response.status_code}: {url}", status_code=response.status_code
            )
        self.limiter.report_success()
        try:
            return response.json()
        except Exception as exc:
            raise SourceError(f"Skeb returned invalid JSON for {url}: {exc}") from exc

    async def discover(self, ctx: SourceContext, limit: int) -> AsyncIterator[Seed]:
        self._ctx = ctx
        if self.options.discover_pages <= 0 or limit <= 0:
            return
        seen: set[str] = set()
        for kind in ("users", "works"):
            referer = f"{BASE}/{kind}?sort=date&genre={self.options.discover_genre}"
            for page in range(self.options.discover_pages):
                offset = page * self.options.page_size
                endpoint = (
                    f"{kind}?sort=date&genre={self.options.discover_genre}"
                    f"&offset={offset}&limit={self.options.page_size}"
                )
                try:
                    data = await self._get(endpoint, referer=referer)
                except ArtistNotFound:
                    break
                except Exception as exc:
                    log.warning("Skeb discovery stopped at %s page %s: %s", kind, page, exc)
                    break
                if not isinstance(data, list) or not data:
                    break
                found = 0
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    handle: str | None = None
                    if kind == "users":
                        handle = item.get("screen_name")
                    else:
                        path = item.get("path", "")
                        match = WORK_PATH_RE.search(str(path))
                        if match:
                            handle = match.group(1)
                    if not handle:
                        continue
                    handle = normalize_handle(str(handle))
                    if not handle or handle.casefold() in seen:
                        continue
                    seen.add(handle.casefold())
                    found += 1
                    yield Seed(
                        site=self.site,
                        handle=handle,
                        url=f"{BASE}/@{handle}",
                        source=f"skeb:{kind}",
                        priority=5,
                    )
                    if len(seen) >= limit:
                        return
                log.info("Skeb discovery %s page %s: %s handles", kind, page, found)
                if found == 0:
                    break

    async def fetch(self, ctx: SourceContext, seed: Seed) -> ArtistBundle:
        self._ctx = ctx
        handle = normalize_handle(seed.handle)
        profile = await self._get(f"users/{handle}", referer=f"{BASE}/@{handle}")
        if not isinstance(profile, dict):
            raise SourceError(f"Unexpected Skeb profile response for {handle}")

        screen_name = normalize_handle(str(profile.get("screen_name") or handle))
        site_user_id = str(profile["id"]) if profile.get("id") is not None else None
        now = now_ts()
        aid = artist_id(self.site, site_user_id, screen_name)
        tags = _unique(
            [
                str(skill.get("genre"))
                for skill in profile.get("skills", [])
                if isinstance(skill, dict) and skill.get("genre")
            ]
        )
        artist = Artist(
            artist_id=aid,
            site=self.site,
            site_user_id=site_user_id,
            handle=screen_name,
            display_name=profile.get("name") or screen_name,
            profile_url=f"{BASE}/@{screen_name}",
            avatar_url=profile.get("avatar_url"),
            header_url=profile.get("header_url"),
            bio=profile.get("description") or profile.get("bio"),
            tags=tags,
            nsfw=_optional_bool(profile.get("nsfw_acceptable")),
            accepts_commissions=_optional_bool(profile.get("acceptable")),
            works_count=_optional_int(profile.get("received_works_count")),
            followers_count=_optional_int(profile.get("followers_count")),
            rating=_optional_float(profile.get("rating")),
            first_seen=now,
            last_updated=now,
            last_seen=now,
            status="active",
        )

        offerings: list[Offering] = []
        price_points: list[PricePoint] = []
        for skill in profile.get("skills", []):
            if not isinstance(skill, dict):
                continue
            genre = str(skill.get("genre") or "unknown")
            amount = _optional_int(skill.get("default_amount"))
            oid = offering_id(self.site, aid, None, genre)
            usd = to_usd(amount, "JPY", self.config.currency)
            offerings.append(
                Offering(
                    offering_id=oid,
                    artist_id=aid,
                    site=self.site,
                    site_offering_id=genre,
                    title=genre,
                    kind=genre,
                    description=None,
                    price_min=amount,
                    price_max=amount,
                    currency="JPY",
                    price_usd=usd,
                    price_min_usd=usd,
                    price_max_usd=usd,
                    tags=[genre],
                    source_url=f"{BASE}/@{screen_name}",
                    first_seen=now,
                    last_updated=now,
                    active=True,
                )
            )
            price_points.append(
                PricePoint(
                    offering_id=oid,
                    artist_id=aid,
                    amount=amount,
                    currency="JPY",
                    amount_usd=usd,
                    observed_at=now,
                )
            )

        works = await self._fetch_works(ctx, aid, screen_name, profile, now)

        return ArtistBundle(
            artist=artist,
            offerings=offerings,
            works=works,
            price_points=price_points,
            raw=profile,
        )

    async def _fetch_works(
        self,
        ctx: SourceContext,
        aid: str,
        handle: str,
        profile: dict[str, Any],
        now: float,
    ) -> list[Work]:
        works: dict[str, Work] = {}
        raw_works = profile.get("received_works")
        if isinstance(raw_works, list):
            for item in raw_works:
                work = _parse_work(self.site, aid, handle, item, now)
                if work is not None:
                    works[work.work_id] = work

        existing = ctx.store.existing_work_ids(aid)
        expected = _optional_int(profile.get("received_works_count"))
        needs_backfill = expected is not None and len(existing) < expected
        offset = 0
        page = 0
        page_size = max(1, self.options.work_page_size)
        try:
            while True:
                endpoint = (
                    f"users/{handle}/works?role=creator&sort=date&offset={offset}&limit={page_size}"
                )
                data = await self._get(endpoint, referer=f"{BASE}/@{handle}/works")
                if not isinstance(data, list) or not data:
                    break
                page += 1
                new_in_page = 0
                for item in data:
                    work = _parse_work(self.site, aid, handle, item, now)
                    if work is None:
                        continue
                    if work.work_id not in existing:
                        new_in_page += 1
                    works.setdefault(work.work_id, work)
                if existing and new_in_page == 0 and not needs_backfill:
                    break
                if self.options.max_work_pages > 0 and page >= self.options.max_work_pages:
                    break
                if len(data) < page_size:
                    break
                offset += page_size
        except (RateLimitError, BudgetExceeded):
            raise
        except Exception as exc:
            log.warning("Skeb works pagination failed for %s: %s", handle, exc)

        limit = self.options.max_works_per_artist
        ordered = sorted(works.values(), key=lambda item: item.created_at or 0, reverse=True)
        return ordered[:limit] if limit > 0 else ordered


def _parse_work(site: str, aid: str, handle: str, item: Any, now: float) -> Work | None:
    if not isinstance(item, dict):
        return None
    if item.get("private") is True:
        return None
    path = str(item.get("path") or "")
    match = WORK_PATH_RE.search(path)
    site_work_id = match.group(2) if match else None
    if not site_work_id:
        site_work_id = (
            str(item.get("id")) if item.get("id") is not None else stable_id("skeb", handle, path)
        )
    thumb = _image_url(item.get("thumbnail_image_urls")) or _image_url(
        item.get("censored_thumbnail_image_urls")
    )
    images = _image_urls(item)
    created = parse_iso(item.get("created_at") or item.get("delivered_at") or item.get("date"))
    source_url = urljoin(BASE, path) if path else f"{BASE}/@{handle}"
    return Work(
        work_id=work_id(site, aid, site_work_id, path),
        artist_id=aid,
        site=site,
        site_work_id=site_work_id,
        title=item.get("title"),
        thumb_url=thumb,
        image_urls=images,
        tags=_unique([str(tag) for tag in item.get("tags", []) if tag])
        if isinstance(item.get("tags"), list)
        else [],
        created_at=created,
        source_url=source_url,
        first_seen=now,
        last_updated=now,
    )


def _image_url(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    src = value.get("src")
    srcset = value.get("srcset")
    if isinstance(srcset, str) and srcset:
        parts = [part.strip() for part in srcset.split(",") if part.strip()]
        for target in ("3x", "2x", "1x"):
            for part in parts:
                tokens = part.rsplit(None, 1)
                if len(tokens) == 2 and tokens[1] == target:
                    return tokens[0]
        if parts:
            return parts[0].split()[0]
    return str(src) if src else None


def _image_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("image_urls", "image_url", "thumbnail_image_urls", "censored_thumbnail_image_urls"):
        value = item.get(key)
        if isinstance(value, str):
            urls.append(value)
        elif isinstance(value, dict):
            found = _image_url(value)
            if found:
                urls.append(found)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    urls.append(entry)
                elif isinstance(entry, dict):
                    found = _image_url(entry)
                    if found:
                        urls.append(found)
    return _unique(urls)


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


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)
