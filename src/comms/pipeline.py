from __future__ import annotations

import asyncio
import re
from pathlib import Path

from comms.config import AppConfig
from comms.http import BudgetExceeded, RateLimitError, RunBudget
from comms.ids import normalize_handle
from comms.logging import get_logger
from comms.models import RunStats, Seed
from comms.registry import available_sources, create_source
from comms.sources.base import ArtistNotFound, SourceContext, SourceError
from comms.store.sqlite import SQLiteStore
from comms.timeutil import now_ts

log = get_logger("pipeline")

SKEB_URL_RE = re.compile(r"skeb\.jp/@([A-Za-z0-9_]+)", re.IGNORECASE)
CREPE_URL_RE = re.compile(r"crepe\.cm/(?:[a-z]{2}/)?@([^/\s?#]+)", re.IGNORECASE)


class Pipeline:
    def __init__(self, config: AppConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store
        self.opt_outs = load_opt_outs(config.compliance.opt_out_file)

    async def run(
        self,
        *,
        sites: list[str] | None = None,
        seeds: list[Seed] | None = None,
        discover: bool = True,
        refresh: bool = True,
        limit: int = 0,
    ) -> list[RunStats]:
        selected = sites or [
            name for name in available_sources() if _source_enabled(self.config, name)
        ]
        budget = RunBudget(
            max_requests=self.config.run.max_requests,
            max_runtime_seconds=self.config.run.max_runtime_minutes * 60.0,
        )
        all_stats: list[RunStats] = []
        for site in selected:
            if not _source_enabled(self.config, site):
                log.warning("Source %s is disabled in config; skipping", site)
                continue
            stats = await self._run_site(
                site,
                seeds=[seed for seed in (seeds or []) if seed.site == site],
                discover=discover,
                refresh=refresh,
                limit=limit,
                budget=budget,
            )
            all_stats.append(stats)
            if budget.stop_reason:
                break
        return all_stats

    async def _run_site(
        self,
        site: str,
        *,
        seeds: list[Seed],
        discover: bool,
        refresh: bool,
        limit: int,
        budget: RunBudget,
    ) -> RunStats:
        stats = RunStats(site=site)
        source = create_source(site, self.config)
        ctx = SourceContext(config=self.config, store=self.store, budget=budget)

        log.info(
            "Starting %s source (discover=%s refresh=%s limit=%s)", site, discover, refresh, limit
        )
        try:
            await source.open(ctx)
        except Exception as exc:
            stats.failed += 1
            stats.stopped_reason = "open_failed"
            stats.finished_at = now_ts()
            log.exception("Could not open %s source: %s", site, exc)
            return stats

        try:
            queued = 0
            for seed in seeds:
                if self._is_opted_out(site, seed.handle):
                    continue
                self.store.enqueue(site, seed.handle, priority=100, source=seed.source, reset=True)
                queued += 1
            stats.queued += queued

            if refresh and self.config.run.max_refresh_artists > 0:
                refreshed = self.store.enqueue_stale_artists(
                    site,
                    stale_hours=self.config.run.refresh_stale_hours,
                    limit=self.config.run.max_refresh_artists,
                )
                stats.queued += refreshed

            if discover and self.config.run.max_new_artists > 0:
                try:
                    async for seed in source.discover(ctx, self.config.run.max_new_artists):
                        if self._is_opted_out(site, seed.handle):
                            continue
                        self.store.enqueue(
                            site, seed.handle, priority=seed.priority, source=seed.source
                        )
                        stats.discovered += 1
                        stats.queued += 1
                        if budget.stop_reason:
                            break
                except BudgetExceeded:
                    pass
                except Exception as exc:
                    log.warning("Discovery failed for %s: %s", site, exc)

            self.store.conn.commit()
            stats.requests = budget.requests
            await self._process_frontier(source, ctx, site, stats, limit, budget)
        finally:
            await source.close()
            stats.requests = budget.requests
            stats.finished_at = now_ts()
            self._log_stats(stats)
        return stats

    async def _process_frontier(
        self,
        source,  # type: ignore[no-untyped-def]
        ctx: SourceContext,
        site: str,
        stats: RunStats,
        limit: int,
        budget: RunBudget,
    ) -> None:
        fetched = 0
        while True:
            if limit > 0 and fetched >= limit:
                stats.stopped_reason = "limit"
                break
            if budget.stop_reason:
                stats.stopped_reason = budget.stop_reason
                break
            if stats.rate_limited >= self.config.run.rate_limit_stop_after:
                stats.stopped_reason = "rate_limit"
                break

            try:
                budget.check()
            except BudgetExceeded as exc:
                stats.stopped_reason = str(exc)
                break

            row = self.store.pop_due(site)
            if row is None:
                stats.stopped_reason = stats.stopped_reason or "frontier_empty"
                break

            handle = normalize_handle(str(row["handle"]))
            if self._is_opted_out(site, handle):
                self.store.complete_frontier(site, handle)
                continue

            seed = Seed(
                site=site,
                handle=handle,
                source=str(row.get("source") or "frontier"),
                priority=int(row.get("priority") or 0),
            )
            try:
                bundle = await source.fetch(ctx, seed)
                self.store.upsert_bundle(bundle)
                self.store.complete_frontier(site, handle)
                fetched += 1
                stats.fetched += 1
                stats.artists += 1
                stats.offerings += len(bundle.offerings)
                stats.works += len(bundle.works)
                stats.prices += len(bundle.price_points)
                if stats.fetched % 25 == 0:
                    log.info(
                        "%s progress: fetched=%s artists=%s offerings=%s works=%s queue=%s",
                        site,
                        stats.fetched,
                        stats.artists,
                        stats.offerings,
                        stats.works,
                        self.store.queued_count(site),
                    )
            except ArtistNotFound:
                self.store.mark_missing(site, handle)
                stats.missing += 1
                log.info("%s artist missing: %s", site, handle)
            except RateLimitError as exc:
                stats.rate_limited += 1
                self.store.fail_frontier(
                    site,
                    handle,
                    str(exc),
                    retry_after_seconds=3600.0,
                )
                log.warning(
                    "%s rate limited on %s (%s/%s)",
                    site,
                    handle,
                    stats.rate_limited,
                    self.config.run.rate_limit_stop_after,
                )
                if stats.rate_limited >= self.config.run.rate_limit_stop_after:
                    stats.stopped_reason = "rate_limit"
                    break
            except BudgetExceeded as exc:
                self.store.fail_frontier(site, handle, str(exc), retry_after_seconds=0.0)
                stats.stopped_reason = str(exc)
                break
            except SourceError as exc:
                stats.failed += 1
                attempts = int(row.get("attempts") or 0) + 1
                self.store.fail_frontier(
                    site,
                    handle,
                    str(exc),
                    retry_after_seconds=min(86400.0, 300.0 * 2 ** min(attempts, 6)),
                )
                log.warning("%s failed on %s: %s", site, handle, exc)
            except Exception as exc:
                stats.failed += 1
                attempts = int(row.get("attempts") or 0) + 1
                self.store.fail_frontier(
                    site,
                    handle,
                    repr(exc),
                    retry_after_seconds=min(86400.0, 300.0 * 2 ** min(attempts, 6)),
                )
                log.exception("%s unexpected failure on %s: %s", site, handle, exc)

            if budget.stop_reason:
                stats.stopped_reason = budget.stop_reason
                break
            await asyncio.sleep(0)

    def _is_opted_out(self, site: str, handle: str) -> bool:
        key = normalize_handle(handle).casefold()
        return key in self.opt_outs.get("*", set()) or key in self.opt_outs.get(site, set())

    def _log_stats(self, stats: RunStats) -> None:
        log.info(
            "%s finished: fetched=%s missing=%s failed=%s artists=%s offerings=%s works=%s prices=%s requests=%s reason=%s",
            stats.site,
            stats.fetched,
            stats.missing,
            stats.failed,
            stats.artists,
            stats.offerings,
            stats.works,
            stats.prices,
            stats.requests,
            stats.stopped_reason,
        )


def load_opt_outs(path: str | Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    file_path = Path(path)
    if not file_path.exists():
        return result
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        skeb = SKEB_URL_RE.search(line)
        if skeb:
            result.setdefault("skeb", set()).add(skeb.group(1).casefold())
            continue
        crepe = CREPE_URL_RE.search(line)
        if crepe:
            result.setdefault("crepe", set()).add(crepe.group(1).casefold())
            continue
        if ":" in line:
            site, _, handle = line.partition(":")
            if site.strip().lower() in {"skeb", "crepe"}:
                result.setdefault(site.strip().lower(), set()).add(
                    normalize_handle(handle).casefold()
                )
                continue
        result.setdefault("*", set()).add(normalize_handle(line).casefold())
    return result


def _source_enabled(config: AppConfig, name: str) -> bool:
    options = getattr(config.sources, name, None)
    return bool(getattr(options, "enabled", True)) if options is not None else False
