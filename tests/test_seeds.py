import json
from pathlib import Path

from comms.pipeline import load_opt_outs
from comms.seeds import extract_seeds_from_text, import_gallery_dl_metadata, load_seed_file


def test_extract_urls_and_plain_handles() -> None:
    text = """
    # https://skeb.jp/@Alice
    https://crepe.cm/en/@Bob/abc123
    @Carol
    """
    seeds = extract_seeds_from_text(text, default_site="skeb")
    pairs = {(seed.site, seed.handle) for seed in seeds}
    assert ("skeb", "Alice") in pairs
    assert ("crepe", "Bob") in pairs
    assert ("skeb", "Carol") in pairs


def test_load_markdown_album(tmp_path: Path) -> None:
    path = tmp_path / "album.md"
    path.write_text("# https://skeb.jp/@artist_one\n  art: ¥1,000\n", encoding="utf-8")
    seeds = load_seed_file(path)
    assert seeds[0].site == "skeb"
    assert seeds[0].handle == "artist_one"


def test_load_seed_url(tmp_path: Path) -> None:
    path = tmp_path / "remote-album.md"
    path.write_text("# https://skeb.jp/@url_artist\n", encoding="utf-8")
    seeds = load_seed_file(path.as_uri())
    assert seeds[0].site == "skeb"
    assert seeds[0].handle == "url_artist"


def test_load_csv(tmp_path: Path) -> None:
    path = tmp_path / "users.csv"
    path.write_text("skeb_handle,crepe_handle\nskeb_user,crepe_user\n", encoding="utf-8")
    seeds = load_seed_file(path)
    assert {(seed.site, seed.handle) for seed in seeds} == {
        ("skeb", "skeb_user"),
        ("crepe", "crepe_user"),
    }


def test_gallery_dl_metadata_import(tmp_path: Path) -> None:
    path = tmp_path / "tweet.json"
    path.write_text(
        json.dumps(
            {
                "content": "commission info https://skeb.jp/@from_tweet",
                "author": {"description": "also https://crepe.cm/en/@from_bio"},
            }
        ),
        encoding="utf-8",
    )
    seeds = import_gallery_dl_metadata(tmp_path)
    assert {(seed.site, seed.handle) for seed in seeds} == {
        ("skeb", "from_tweet"),
        ("crepe", "from_bio"),
    }


def test_opt_out_file(tmp_path: Path) -> None:
    path = tmp_path / "opt-out.txt"
    path.write_text(
        "# comment\nskeb:blocked\nhttps://skeb.jp/@url_blocked\nbare\n",
        encoding="utf-8",
    )
    result = load_opt_outs(path)
    assert "blocked" in result["skeb"]
    assert "url_blocked" in result["skeb"]
    assert "bare" in result["*"]
