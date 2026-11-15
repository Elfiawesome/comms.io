import json
from pathlib import Path

from comms.seeds import extract_bio_links, scan_gallery_dl_bio_links


def test_extract_bio_links() -> None:
    text = """
    My links: https://lit.link/artist/abc and https://linktr.ee/other.
    Also https:\\/\\/carrd.co\\/x
    """
    links = extract_bio_links(text)
    assert links == [
        "https://lit.link/artist/abc",
        "https://linktr.ee/other",
        "https://carrd.co/x",
    ]


def test_scan_gallery_dl_bio_links(tmp_path: Path) -> None:
    path = tmp_path / "tweet.json"
    path.write_text(
        json.dumps(
            {
                "author": {"description": "https://lit.link/one"},
                "content": "https://linktr.ee/two and https://skeb.jp/@direct",
            }
        ),
        encoding="utf-8",
    )
    links = scan_gallery_dl_bio_links(tmp_path, limit=10)
    assert links == ["https://lit.link/one", "https://linktr.ee/two"]
