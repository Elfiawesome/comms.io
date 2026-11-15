from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from comms.timeutil import now_ts


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Seed(Model):
    site: str
    handle: str
    url: str | None = None
    source: str = "manual"
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PricePoint(Model):
    offering_id: str
    artist_id: str
    amount: int | None = None
    currency: str = "JPY"
    amount_usd: float | None = None
    observed_at: float = Field(default_factory=now_ts)


class Artist(Model):
    artist_id: str
    site: str
    site_user_id: str | None = None
    handle: str
    display_name: str | None = None
    profile_url: str | None = None
    avatar_url: str | None = None
    header_url: str | None = None
    bio: str | None = None
    tags: list[str] = Field(default_factory=list)
    nsfw: bool | None = None
    accepts_commissions: bool | None = None
    works_count: int | None = None
    followers_count: int | None = None
    rating: float | None = None
    first_seen: float = Field(default_factory=now_ts)
    last_updated: float = Field(default_factory=now_ts)
    last_seen: float = Field(default_factory=now_ts)
    status: str = "active"


class Offering(Model):
    offering_id: str
    artist_id: str
    site: str
    site_offering_id: str | None = None
    title: str | None = None
    kind: str | None = None
    description: str | None = None
    price_min: int | None = None
    price_max: int | None = None
    currency: str = "JPY"
    price_usd: float | None = None
    price_min_usd: float | None = None
    price_max_usd: float | None = None
    cover_url: str | None = None
    turnaround_days: int | None = None
    slots: int | None = None
    available: bool | None = None
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    first_seen: float = Field(default_factory=now_ts)
    last_updated: float = Field(default_factory=now_ts)
    active: bool = True


class Work(Model):
    work_id: str
    artist_id: str
    site: str
    site_work_id: str | None = None
    title: str | None = None
    thumb_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: float | None = None
    source_url: str | None = None
    first_seen: float = Field(default_factory=now_ts)
    last_updated: float = Field(default_factory=now_ts)


class ArtistBundle(Model):
    artist: Artist
    offerings: list[Offering] = Field(default_factory=list)
    works: list[Work] = Field(default_factory=list)
    price_points: list[PricePoint] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class FetchResult(Model):
    site: str
    handle: str
    status: str
    artists: int = 0
    offerings: int = 0
    works: int = 0
    prices: int = 0
    error: str | None = None


class RunStats(Model):
    started_at: float = Field(default_factory=now_ts)
    finished_at: float | None = None
    site: str | None = None
    discovered: int = 0
    queued: int = 0
    fetched: int = 0
    missing: int = 0
    failed: int = 0
    artists: int = 0
    offerings: int = 0
    works: int = 0
    prices: int = 0
    requests: int = 0
    rate_limited: int = 0
    stopped_reason: str | None = None
