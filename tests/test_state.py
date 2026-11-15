import hashlib
from pathlib import Path

from comms.models import Artist, ArtistBundle, Offering
from comms.state import download_state, pack_state
from comms.store.sqlite import SQLiteStore


def _bundle() -> ArtistBundle:
    artist = Artist(
        artist_id="artist_state",
        site="skeb",
        site_user_id="1",
        handle="state_user",
    )
    offering = Offering(
        offering_id="offering_state",
        artist_id="artist_state",
        site="skeb",
        site_offering_id="art",
        title="art",
        kind="art",
        price_min=1000,
        price_max=1000,
        currency="JPY",
    )
    return ArtistBundle(artist=artist, offerings=[offering])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pack_and_download_state(tmp_path: Path) -> None:
    db = tmp_path / "work" / "comms.sqlite3"
    with SQLiteStore(db) as store:
        store.upsert_bundle(_bundle())

    state_dir = tmp_path / "snapshot" / "state"
    manifest = pack_state(db, state_dir, chunk_size_mb=1)
    assert manifest["format"] == "sqlite-gzip-chunks"
    assert manifest["counts"]["artists"] == 1
    assert (state_dir / "manifest.json").exists()
    assert all((state_dir / chunk["path"]).exists() for chunk in manifest["chunks"])

    restored = tmp_path / "restored" / "comms.sqlite3"
    downloaded = download_state(
        "owner/repo",
        "data",
        restored,
        data_base=(tmp_path / "snapshot").as_uri() + "/",
    )
    assert downloaded is not None
    assert _sha(restored) == manifest["uncompressed_sha256"]
