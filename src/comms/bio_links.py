from __future__ import annotations

from urllib.parse import urlparse

from comms.config import AppConfig
from comms.http import HttpClient, RunBudget
from comms.logging import get_logger
from comms.models import Seed
from comms.seeds import extract_seeds_from_text

log = get_logger("bio-links")


async def follow_bio_links(
    links: list[str],
    config: AppConfig,
    *,
    max_links: int = 200,
) -> list[Seed]:
    """Visit link-in-bio pages and extract Skeb/CREPE profile links.

    This is intentionally optional and rate-limited. It exists because many X
    creators link their commission profile through lit.link, linktree, etc.
    """
    unique_links = list(dict.fromkeys(link for link in links if link))
    if max_links > 0:
        unique_links = unique_links[:max_links]
    if not unique_links:
        return []

    budget = RunBudget(
        max_requests=len(unique_links),
        max_runtime_seconds=config.run.max_runtime_minutes * 60.0,
    )
    client = HttpClient(config.network, budget)
    seeds: list[Seed] = []
    try:
        for index, link in enumerate(unique_links, start=1):
            try:
                response = await client.get(link)
            except Exception as exc:
                log.warning("Bio link failed %s: %s", link, exc)
                continue
            if response.status_code >= 400:
                continue
            source = f"bio:{urlparse(link).netloc}"
            seeds.extend(extract_seeds_from_text(response.text, source=source, priority=15))
            if index % 25 == 0:
                log.info(
                    "Followed %s/%s bio links (%s seeds)", index, len(unique_links), len(seeds)
                )
    finally:
        await client.close()

    deduped: dict[tuple[str, str], Seed] = {}
    for seed in seeds:
        key = (seed.site, seed.handle.casefold())
        deduped.setdefault(key, seed)
    return list(deduped.values())
