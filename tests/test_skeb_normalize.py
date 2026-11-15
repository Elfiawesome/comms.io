from pathlib import Path

import pytest

from comms.config import AppConfig
from comms.http import RunBudget
from comms.sources.base import SourceContext, SourceError
from comms.sources.skeb import SkebSource, _image_url, _parse_work
from comms.store.sqlite import SQLiteStore
from comms.timeutil import now_ts


def test_image_url_prefers_high_resolution() -> None:
    value = {
        "src": "https://example.invalid/1x.jpg",
        "srcset": "https://example.invalid/1x.jpg 1x, https://example.invalid/2x.jpg 2x, https://example.invalid/3x.jpg 3x",
    }
    assert _image_url(value) == "https://example.invalid/3x.jpg"


def test_parse_work() -> None:
    work = _parse_work(
        "skeb",
        "artist_1",
        "alice",
        {
            "path": "/@alice/works/12345",
            "title": "sample",
            "thumbnail_image_urls": {"src": "https://example.invalid/thumb.jpg"},
            "created_at": "2025-01-02T03:04:05Z",
        },
        1.0,
    )
    assert work is not None
    assert work.site_work_id == "12345"
    assert work.source_url == "https://skeb.jp/@alice/works/12345"
    assert work.created_at is not None


def test_parse_work_rejects_other_artist_path() -> None:
    work = _parse_work(
        "skeb",
        "artist_1",
        "alice",
        {
            "path": "/@bob/works/12345",
            "thumbnail_image_urls": {"src": "https://example.invalid/x.jpg"},
        },
        1.0,
    )
    assert work is None


@pytest.mark.asyncio
async def test_fetch_works_propagates_source_errors(tmp_path: Path) -> None:
    config = AppConfig()
    source = SkebSource(config.sources.skeb, config)

    async def fail(*args, **kwargs):
        raise SourceError("HTTP 403", status_code=403)

    source._get = fail  # type: ignore[method-assign]
    with SQLiteStore(tmp_path / "archive.sqlite") as store:
        ctx = SourceContext(config=config, store=store, budget=RunBudget(10, 60))
        with pytest.raises(SourceError):
            await source._fetch_works(
                ctx,
                "artist_1",
                "alice",
                {"received_works": []},
                now_ts(),
            )
