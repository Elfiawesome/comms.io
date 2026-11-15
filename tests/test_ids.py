from comms.ids import artist_id, normalize_handle, offering_id, stable_id, work_id


def test_stable_ids_are_deterministic() -> None:
    assert stable_id("a", "b") == stable_id("a", "b")
    assert stable_id("a", "b") != stable_id("a", "c")


def test_artist_id_prefers_site_user_id() -> None:
    first = artist_id("skeb", "123", "old_name")
    renamed = artist_id("skeb", "123", "new_name")
    assert first == renamed
    assert artist_id("skeb", None, "Mixed") == artist_id("skeb", None, "mixed")


def test_related_ids_are_stable() -> None:
    aid = artist_id("skeb", "123", "alice")
    assert offering_id("skeb", aid, None, "art") == offering_id("skeb", aid, None, "art")
    assert work_id("skeb", aid, "42", "path") == work_id("skeb", aid, "42", "other")


def test_normalize_handle() -> None:
    assert normalize_handle("  @Alice ") == "Alice"
