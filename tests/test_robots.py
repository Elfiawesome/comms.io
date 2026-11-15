from comms.http import RobotsRules

CREPE_ROBOTS = """
User-agent: Bytespider
Disallow: /

User-agent: *
Allow: /$
Allow: /ko$
Allow: /en$
Allow: /?source=header$
Disallow: /
Allow: /@
Allow: /ko/@
Allow: /en/@
Allow: /icons/icon.svg
Allow: /favicon.ico
"""


def test_longest_match_allow_wins_over_global_disallow() -> None:
    rules = RobotsRules(CREPE_ROBOTS)
    assert rules.can_fetch("https://crepe.cm/en")
    assert rules.can_fetch("https://crepe.cm/en/@QZcommission")
    assert rules.can_fetch("https://crepe.cm/en/@QZcommission/h7o0quz")
    assert not rules.can_fetch("https://crepe.cm/en/search?keyword=x")
    assert not rules.can_fetch("https://crepe.cm/ko/search")


def test_wildcard_and_exact_end_rules() -> None:
    rules = RobotsRules(
        """
        User-agent: *
        Disallow: /private/
        Allow: /private/public/
        Allow: /*.json$
        """
    )
    assert not rules.can_fetch("https://example.com/private/a")
    assert rules.can_fetch("https://example.com/private/public/a")
    assert rules.can_fetch("https://example.com/data.json")
    assert rules.can_fetch("https://example.com/data.json?x=1")
    assert not rules.can_fetch("https://example.com/private/a?x=1")
