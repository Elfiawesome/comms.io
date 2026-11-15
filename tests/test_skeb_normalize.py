from comms.sources.skeb import _image_url, _parse_work


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
