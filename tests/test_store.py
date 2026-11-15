from pathlib import Path

from comms.models import Artist, ArtistBundle, Offering, PricePoint, Work
from comms.store.sqlite import SQLiteStore


def make_bundle(price: int = 5000) -> ArtistBundle:
    artist = Artist(
        artist_id="artist_test",
        site="skeb",
        site_user_id="123",
        handle="alice",
        display_name="Alice",
        tags=["art"],
        works_count=1,
    )
    offering = Offering(
        offering_id="offering_test",
        artist_id="artist_test",
        site="skeb",
        site_offering_id="art",
        title="art",
        kind="art",
        price_min=price,
        price_max=price,
        currency="JPY",
        price_usd=price * 0.0067,
        price_min_usd=price * 0.0067,
        price_max_usd=price * 0.0067,
        tags=["art"],
    )
    work = Work(
        work_id="work_test",
        artist_id="artist_test",
        site="skeb",
        site_work_id="42",
        title="sample",
        thumb_url="https://example.invalid/thumb.jpg",
    )
    point = PricePoint(
        offering_id="offering_test",
        artist_id="artist_test",
        amount=price,
        currency="JPY",
        amount_usd=price * 0.0067,
    )
    return ArtistBundle(artist=artist, offerings=[offering], works=[work], price_points=[point])


def test_upsert_and_price_history(tmp_path: Path) -> None:
    db = tmp_path / "archive.sqlite"
    with SQLiteStore(db) as store:
        store.upsert_bundle(make_bundle(5000))
        assert store.counts()["artists"] == 1
        assert store.counts()["offerings"] == 1
        assert store.counts()["works"] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 1

        store.upsert_bundle(make_bundle(5000))
        assert store.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 1

        store.upsert_bundle(make_bundle(6000))
        assert store.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 2


def test_frontier_lifecycle(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "archive.sqlite") as store:
        store.enqueue("skeb", "@alice", priority=5)
        row = store.pop_due("skeb")
        assert row is not None
        assert row["handle"] == "alice"
        store.complete_frontier("skeb", "alice")
        assert store.pop_due("skeb") is None
        assert store.queued_count("skeb") == {"done": 1}


def test_stale_refresh_resets_completed_frontier(tmp_path: Path) -> None:
    bundle = make_bundle()
    bundle.artist.last_updated = 1.0
    with SQLiteStore(tmp_path / "archive.sqlite") as store:
        store.upsert_bundle(bundle)
        store.enqueue("skeb", "alice")
        assert store.pop_due("skeb") is not None
        store.complete_frontier("skeb", "alice")
        assert store.pop_due("skeb") is None

        queued = store.enqueue_stale_artists("skeb", stale_hours=0, limit=10)
        assert queued == 1
        row = store.pop_due("skeb")
        assert row is not None
        assert row["handle"] == "alice"
