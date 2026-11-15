import json
from pathlib import Path

from comms.config import AppConfig
from comms.exporters.parquet import ParquetExporter
from comms.models import Artist, ArtistBundle, Offering, PricePoint, Work
from comms.publish.github import GitPublisher
from comms.store.sqlite import SQLiteStore
from comms.validate import validate_data_dir


def _bundle() -> ArtistBundle:
    artist = Artist(
        artist_id="artist_export",
        site="skeb",
        site_user_id="999",
        handle="export_user",
        display_name="Export User",
        tags=["art"],
    )
    offering = Offering(
        offering_id="offering_export",
        artist_id="artist_export",
        site="skeb",
        site_offering_id="art",
        title="art",
        kind="art",
        price_min=5000,
        price_max=5000,
        currency="JPY",
        price_usd=33.5,
        price_min_usd=33.5,
        price_max_usd=33.5,
        cover_url="https://example.invalid/cover.png",
        tags=["art"],
    )
    work = Work(
        work_id="work_export",
        artist_id="artist_export",
        site="skeb",
        site_work_id="1",
        title="work",
        thumb_url="https://example.invalid/thumb.jpg",
    )
    point = PricePoint(
        offering_id="offering_export",
        artist_id="artist_export",
        amount=5000,
        currency="JPY",
        amount_usd=33.5,
    )
    return ArtistBundle(artist=artist, offerings=[offering], works=[work], price_points=[point])


def test_export_and_validate(tmp_path: Path) -> None:
    config = AppConfig()
    config.paths.export_dir = str(tmp_path / "data")
    config.export.artist_partitions = 2
    config.export.offering_partitions = 2
    config.export.work_partitions = 2
    config.export.price_history_partitions = 2
    with SQLiteStore(tmp_path / "archive.sqlite") as store:
        store.upsert_bundle(_bundle())
        target = ParquetExporter(config).export(store)

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["artists"] == 1
    assert manifest["counts"]["offerings"] == 1
    assert (target / "artists").exists()
    report = validate_data_dir(target, max_data_mb=10)
    assert report["tables"]["artists"]["rows"] == 1

    import pyarrow.parquet as pq

    artists = pq.read_table(next((target / "artists").glob("*.parquet"))).to_pylist()
    assert artists[0]["latest_thumbnails"] == [
        "https://example.invalid/thumb.jpg",
        "https://example.invalid/cover.png",
    ]
    offerings = pq.read_table(next((target / "offerings").glob("*.parquet"))).to_pylist()
    assert offerings[0]["cover_url"] == "https://example.invalid/cover.png"


def test_publish_dry_run(tmp_path: Path) -> None:
    config = AppConfig()
    data = tmp_path / "data"
    data.mkdir()
    (data / "manifest.json").write_text("{}", encoding="utf-8")
    result = GitPublisher(config).publish(data, dry_run=True)
    assert result["pushed"] is False
    assert result["dry_run"] is True
