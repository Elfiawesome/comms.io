import json

from comms.sources.crepe import (
    _clean_url,
    _commission_records,
    _doc_text,
    _find_user,
    _tag_names,
    parse_vike_page,
)


def _page() -> dict:
    return {
        "relayInitialData": {
            "client:root": {'user(username:"alice")': {"__ref": "user_1"}},
            "user_1": {
                "__id": "user_1",
                "__typename": "User",
                "_id": "internal_1",
                "username": "alice",
                "name": "Alice",
                "commissionTypes": {"__refs": ["ct_1"]},
                "statistics": {"__ref": "stats_1"},
                "bio": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}
                    ],
                },
            },
            "ct_1": {
                "__id": "ct_1",
                "__typename": "CommissionType",
                "id": "ct_1",
                "slug": "art",
                "name": "Art commission",
                "inquiryAvailable": True,
                "tags": {"__refs": ["tag_1"]},
            },
            "tag_1": {
                "__id": "tag_1",
                "__typename": "Tag",
                "name": "Illustration",
                "key": "illustration",
            },
            "stats_1": {"__id": "stats_1", "__typename": "UserStatistics", "workCount": 12},
        }
    }


def test_parse_vike_page() -> None:
    payload = json.dumps(_page(), ensure_ascii=False)
    html = f'<html><script id="vike_pageContext" type="application/json">{payload}</script></html>'
    parsed = parse_vike_page(html)
    assert parsed is not None
    records = parsed["relayInitialData"]
    user = _find_user(records, "alice")
    assert user is not None
    assert user["name"] == "Alice"
    commissions = _commission_records(records, user)
    assert len(commissions) == 1
    assert _tag_names(records, commissions[0]) == ["Illustration"]
    assert _doc_text(user["bio"]) == "hello"
    assert _clean_url("https:\\/\\/crepe.land\\/image.png") == "https://crepe.land/image.png"
    assert _clean_url(None) is None
