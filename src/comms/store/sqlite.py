from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from comms.ids import normalize_handle
from comms.logging import get_logger
from comms.models import Artist, ArtistBundle, Offering, PricePoint, Work
from comms.timeutil import now_ts

log = get_logger("store")

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "1"

TABLE_NAMES = ("artists", "offerings", "works", "price_history")


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def _initialize(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,),
        )
        # A process that died mid-fetch leaves rows in 'running'. Retry them.
        self.conn.execute(
            "UPDATE frontier SET status = 'retry', next_run_at = 0 WHERE status = 'running'"
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def resolve_artist_id(self, site: str, handle: str, site_user_id: str | None) -> str | None:
        if site_user_id:
            row = self.conn.execute(
                "SELECT artist_id FROM artists WHERE site = ? AND site_user_id = ?",
                (site, site_user_id),
            ).fetchone()
            if row:
                return str(row["artist_id"])
        row = self.conn.execute(
            "SELECT artist_id FROM artists WHERE site = ? AND handle = ? COLLATE NOCASE",
            (site, normalize_handle(handle)),
        ).fetchone()
        return str(row["artist_id"]) if row else None

    def get_artist(self, artist_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM artists WHERE artist_id = ?", (artist_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_artist_by_handle(self, site: str, handle: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM artists WHERE site = ? AND handle = ? COLLATE NOCASE",
            (site, normalize_handle(handle)),
        ).fetchone()
        return dict(row) if row else None

    def upsert_bundle(self, bundle: ArtistBundle) -> str:
        artist = bundle.artist
        existing_id = self.resolve_artist_id(artist.site, artist.handle, artist.site_user_id)
        if existing_id and existing_id != artist.artist_id:
            old_id = artist.artist_id
            artist.artist_id = existing_id
            for offering in bundle.offerings:
                offering.artist_id = existing_id
            for work in bundle.works:
                work.artist_id = existing_id
            for point in bundle.price_points:
                point.artist_id = existing_id
            log.info("Reusing existing artist id %s (was %s)", existing_id, old_id)

        with self.transaction() as conn:
            self._upsert_artist(conn, artist)
            for offering in bundle.offerings:
                self._upsert_offering(conn, offering)
            for work in bundle.works:
                self._upsert_work(conn, work)
            for point in bundle.price_points:
                self._record_price(conn, point)
            self._record_handle(conn, artist)
            if bundle.raw is not None:
                self._save_raw(conn, artist.site, "artist", artist.handle, bundle.raw)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('last_successful_fetch', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(now_ts()),),
            )
        return artist.artist_id

    def _upsert_artist(self, conn: sqlite3.Connection, artist: Artist) -> None:
        row = conn.execute(
            "SELECT first_seen FROM artists WHERE artist_id = ?", (artist.artist_id,)
        ).fetchone()
        first_seen = float(row["first_seen"]) if row else artist.first_seen
        conn.execute(
            """
            INSERT INTO artists (
                artist_id, site, site_user_id, handle, display_name, profile_url,
                avatar_url, header_url, bio, tags_json, nsfw, accepts_commissions,
                works_count, followers_count, rating, first_seen, last_updated,
                last_seen, status, raw_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artist_id) DO UPDATE SET
                site_user_id = COALESCE(excluded.site_user_id, artists.site_user_id),
                handle = excluded.handle,
                display_name = COALESCE(excluded.display_name, artists.display_name),
                profile_url = COALESCE(excluded.profile_url, artists.profile_url),
                avatar_url = COALESCE(excluded.avatar_url, artists.avatar_url),
                header_url = COALESCE(excluded.header_url, artists.header_url),
                bio = COALESCE(excluded.bio, artists.bio),
                tags_json = excluded.tags_json,
                nsfw = COALESCE(excluded.nsfw, artists.nsfw),
                accepts_commissions = COALESCE(excluded.accepts_commissions, artists.accepts_commissions),
                works_count = COALESCE(excluded.works_count, artists.works_count),
                followers_count = COALESCE(excluded.followers_count, artists.followers_count),
                rating = COALESCE(excluded.rating, artists.rating),
                last_updated = excluded.last_updated,
                last_seen = excluded.last_seen,
                status = excluded.status,
                raw_hash = COALESCE(excluded.raw_hash, artists.raw_hash)
            """,
            (
                artist.artist_id,
                artist.site,
                artist.site_user_id,
                normalize_handle(artist.handle),
                artist.display_name,
                artist.profile_url,
                artist.avatar_url,
                artist.header_url,
                artist.bio,
                json.dumps(artist.tags, ensure_ascii=False),
                _bool_to_int(artist.nsfw),
                _bool_to_int(artist.accepts_commissions),
                artist.works_count,
                artist.followers_count,
                artist.rating,
                first_seen,
                artist.last_updated,
                artist.last_seen,
                artist.status,
                None,
            ),
        )

    def _upsert_offering(self, conn: sqlite3.Connection, offering: Offering) -> None:
        row = conn.execute(
            "SELECT first_seen FROM offerings WHERE offering_id = ?", (offering.offering_id,)
        ).fetchone()
        first_seen = float(row["first_seen"]) if row else offering.first_seen
        conn.execute(
            """
            INSERT INTO offerings (
                offering_id, artist_id, site, site_offering_id, title, kind,
                description, price_min, price_max, currency, price_usd,
                price_min_usd, price_max_usd, turnaround_days, slots, available,
                tags_json, source_url, first_seen, last_updated, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offering_id) DO UPDATE SET
                site_offering_id = COALESCE(excluded.site_offering_id, offerings.site_offering_id),
                title = COALESCE(excluded.title, offerings.title),
                kind = COALESCE(excluded.kind, offerings.kind),
                description = COALESCE(excluded.description, offerings.description),
                price_min = excluded.price_min,
                price_max = excluded.price_max,
                currency = excluded.currency,
                price_usd = excluded.price_usd,
                price_min_usd = excluded.price_min_usd,
                price_max_usd = excluded.price_max_usd,
                turnaround_days = COALESCE(excluded.turnaround_days, offerings.turnaround_days),
                slots = excluded.slots,
                available = excluded.available,
                tags_json = excluded.tags_json,
                source_url = COALESCE(excluded.source_url, offerings.source_url),
                last_updated = excluded.last_updated,
                active = excluded.active
            """,
            (
                offering.offering_id,
                offering.artist_id,
                offering.site,
                offering.site_offering_id,
                offering.title,
                offering.kind,
                offering.description,
                offering.price_min,
                offering.price_max,
                offering.currency,
                offering.price_usd,
                offering.price_min_usd,
                offering.price_max_usd,
                offering.turnaround_days,
                offering.slots,
                _bool_to_int(offering.available),
                json.dumps(offering.tags, ensure_ascii=False),
                offering.source_url,
                first_seen,
                offering.last_updated,
                int(offering.active),
            ),
        )

    def _upsert_work(self, conn: sqlite3.Connection, work: Work) -> None:
        row = conn.execute(
            "SELECT first_seen FROM works WHERE work_id = ?", (work.work_id,)
        ).fetchone()
        first_seen = float(row["first_seen"]) if row else work.first_seen
        conn.execute(
            """
            INSERT INTO works (
                work_id, artist_id, site, site_work_id, title, thumb_url,
                image_urls_json, tags_json, created_at, source_url, first_seen,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_id) DO UPDATE SET
                site_work_id = COALESCE(excluded.site_work_id, works.site_work_id),
                title = COALESCE(excluded.title, works.title),
                thumb_url = COALESCE(excluded.thumb_url, works.thumb_url),
                image_urls_json = excluded.image_urls_json,
                tags_json = excluded.tags_json,
                created_at = COALESCE(excluded.created_at, works.created_at),
                source_url = COALESCE(excluded.source_url, works.source_url),
                last_updated = excluded.last_updated
            """,
            (
                work.work_id,
                work.artist_id,
                work.site,
                work.site_work_id,
                work.title,
                work.thumb_url,
                json.dumps(work.image_urls, ensure_ascii=False),
                json.dumps(work.tags, ensure_ascii=False),
                work.created_at,
                work.source_url,
                first_seen,
                work.last_updated,
            ),
        )

    def _record_price(self, conn: sqlite3.Connection, point: PricePoint) -> None:
        latest = conn.execute(
            "SELECT amount, currency FROM price_history "
            "WHERE offering_id = ? ORDER BY observed_at DESC, id DESC LIMIT 1",
            (point.offering_id,),
        ).fetchone()
        if latest and latest["amount"] == point.amount and latest["currency"] == point.currency:
            return
        conn.execute(
            "INSERT INTO price_history(offering_id, artist_id, amount, currency, amount_usd, observed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                point.offering_id,
                point.artist_id,
                point.amount,
                point.currency,
                point.amount_usd,
                point.observed_at,
            ),
        )

    def _record_handle(self, conn: sqlite3.Connection, artist: Artist) -> None:
        conn.execute(
            "INSERT INTO artist_handles(artist_id, handle, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(artist_id, handle) DO UPDATE SET last_seen = excluded.last_seen",
            (
                artist.artist_id,
                normalize_handle(artist.handle),
                artist.first_seen,
                artist.last_seen,
            ),
        )

    def _save_raw(
        self,
        conn: sqlite3.Connection,
        site: str,
        kind: str,
        key: str,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        conn.execute(
            "INSERT OR IGNORE INTO raw_payloads(site, kind, key, fetched_at, content_hash, body) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (site, kind, key, now_ts(), digest, zlib.compress(body, 6)),
        )

    def mark_missing(self, site: str, handle: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE artists SET status = 'missing', last_seen = last_seen "
                "WHERE site = ? AND handle = ? COLLATE NOCASE",
                (site, normalize_handle(handle)),
            )
            conn.execute(
                "UPDATE frontier SET status = 'missing', last_run_at = ? "
                "WHERE site = ? AND handle = ? COLLATE NOCASE",
                (now_ts(), site, normalize_handle(handle)),
            )

    def enqueue(
        self,
        site: str,
        handle: str,
        *,
        priority: int = 0,
        source: str = "manual",
        next_run_at: float = 0.0,
        reset: bool = False,
    ) -> None:
        handle = normalize_handle(handle)
        if not handle:
            return
        if reset:
            self.conn.execute(
                """
                INSERT INTO frontier(site, handle, priority, source, status, next_run_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(site, handle) DO UPDATE SET
                    priority = MAX(frontier.priority, excluded.priority),
                    source = COALESCE(excluded.source, frontier.source),
                    status = 'pending',
                    next_run_at = 0,
                    last_error = NULL
                """,
                (site, handle, priority, source, next_run_at),
            )
            return
        self.conn.execute(
            """
            INSERT INTO frontier(site, handle, priority, source, status, next_run_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(site, handle) DO UPDATE SET
                priority = MAX(frontier.priority, excluded.priority),
                source = COALESCE(frontier.source, excluded.source)
            """,
            (site, handle, priority, source, next_run_at),
        )

    def enqueue_stale_artists(
        self,
        site: str,
        *,
        stale_hours: float,
        limit: int,
        source: str = "refresh",
    ) -> int:
        cutoff = now_ts() - max(0.0, stale_hours) * 3600.0
        rows = self.conn.execute(
            """
            SELECT handle FROM artists
            WHERE site = ? AND status = 'active' AND last_updated <= ?
            ORDER BY last_updated ASC
            LIMIT ?
            """,
            (site, cutoff, limit),
        ).fetchall()
        for row in rows:
            self.enqueue(site, str(row["handle"]), priority=10, source=source)
        self.conn.commit()
        return len(rows)

    def pop_due(self, site: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM frontier
            WHERE site = ?
              AND status IN ('pending', 'retry')
              AND next_run_at <= ?
            ORDER BY priority DESC, next_run_at ASC, rowid ASC
            LIMIT 1
            """,
            (site, now_ts()),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "UPDATE frontier SET status = 'running', last_run_at = ?, attempts = attempts + 1 "
            "WHERE site = ? AND handle = ?",
            (now_ts(), site, row["handle"]),
        )
        self.conn.commit()
        return dict(row)

    def complete_frontier(self, site: str, handle: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE frontier SET status = 'done', last_error = NULL, next_run_at = 0 "
                "WHERE site = ? AND handle = ?",
                (site, normalize_handle(handle)),
            )

    def fail_frontier(
        self,
        site: str,
        handle: str,
        error: str,
        *,
        retry_after_seconds: float = 3600.0,
        missing: bool = False,
    ) -> None:
        status = "missing" if missing else "retry"
        with self.transaction() as conn:
            conn.execute(
                "UPDATE frontier SET status = ?, last_error = ?, next_run_at = ? "
                "WHERE site = ? AND handle = ?",
                (
                    status,
                    error[:2000],
                    now_ts() + retry_after_seconds,
                    site,
                    normalize_handle(handle),
                ),
            )

    def queued_count(self, site: str | None = None) -> dict[str, int]:
        if site:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM frontier WHERE site = ? GROUP BY status",
                (site,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM frontier GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in TABLE_NAMES:
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            result[table] = int(row["n"]) if row else 0
        return result

    def iter_export_rows(self, table: str) -> Iterator[dict[str, Any]]:
        if table not in TABLE_NAMES:
            raise ValueError(f"Unsupported export table: {table}")
        cursor = self.conn.execute(f"SELECT * FROM {table}")
        for row in cursor:
            yield dict(row)

    def iter_artists_for_export(self) -> Iterator[dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT
                a.*,
                (SELECT COUNT(*) FROM offerings o WHERE o.artist_id = a.artist_id AND o.active = 1)
                    AS offerings_count,
                (SELECT MIN(o.price_min_usd) FROM offerings o
                    WHERE o.artist_id = a.artist_id AND o.active = 1)
                    AS price_min_usd,
                (SELECT MAX(o.price_max_usd) FROM offerings o
                    WHERE o.artist_id = a.artist_id AND o.active = 1)
                    AS price_max_usd,
                (SELECT MIN(o.price_min) FROM offerings o
                    WHERE o.artist_id = a.artist_id AND o.active = 1 AND o.currency = 'JPY')
                    AS price_min_jpy,
                (SELECT MAX(o.price_max) FROM offerings o
                    WHERE o.artist_id = a.artist_id AND o.active = 1 AND o.currency = 'JPY')
                    AS price_max_jpy
            FROM artists a
            """
        )
        for row in cursor:
            yield dict(row)

    def iter_offerings_for_export(self) -> Iterator[dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT o.*, a.handle
            FROM offerings o
            JOIN artists a ON a.artist_id = o.artist_id
            """
        )
        for row in cursor:
            yield dict(row)

    def iter_works_for_export(self) -> Iterator[dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT w.*, a.handle
            FROM works w
            JOIN artists a ON a.artist_id = w.artist_id
            """
        )
        for row in cursor:
            yield dict(row)

    def iter_price_history_for_export(self) -> Iterator[dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM price_history")
        for row in cursor:
            yield dict(row)

    def opt_out_handles(self, site: str | None = None) -> set[str]:
        """Handles explicitly excluded from exports."""
        if site:
            rows = self.conn.execute(
                "SELECT handle FROM artists WHERE status = 'opted_out' AND site = ?", (site,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT handle FROM artists WHERE status = 'opted_out'"
            ).fetchall()
        return {normalize_handle(str(row["handle"])).casefold() for row in rows}


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)
