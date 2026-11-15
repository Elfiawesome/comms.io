from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from comms.config import AppConfig
from comms.exporters.schema import QUERY_HINTS, TABLE_ORDER, TABLE_SCHEMAS
from comms.ids import normalize_text
from comms.logging import get_logger
from comms.store.sqlite import SQLiteStore
from comms.timeutil import iso_utc, now_ts

log = get_logger("export.parquet")

DATA_VERSION = 1
SCHEMA_VERSION = 1


class ParquetExporter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def export(
        self,
        store: SQLiteStore,
        *,
        opt_out_pairs: set[tuple[str, str]] | None = None,
    ) -> Path:
        target = self.config.export_path
        temp = target.with_name(target.name + ".tmp")
        if temp.exists():
            shutil.rmtree(temp)
        temp.mkdir(parents=True, exist_ok=True)

        opt_outs = opt_out_pairs or set()
        excluded_artist_ids: set[str] = set()
        tables: dict[str, dict[str, Any]] = {}

        all_rows: dict[str, list[dict[str, Any]]] = {}
        artists = list(self._artist_rows(store, opt_outs, excluded_artist_ids))
        all_rows["artists"] = artists
        all_rows["offerings"] = list(self._offering_rows(store, opt_outs, excluded_artist_ids))
        all_rows["works"] = list(self._work_rows(store, opt_outs, excluded_artist_ids))
        all_rows["price_history"] = list(self._price_rows(store, excluded_artist_ids))

        for table_name in TABLE_ORDER:
            rows = all_rows[table_name]
            table_dir = temp / table_name
            table_dir.mkdir(parents=True, exist_ok=True)
            partition_count = _partition_count(self.config, table_name)
            partitions = _partition_rows(table_name, rows, partition_count)
            files: list[dict[str, Any]] = []
            for part_index in sorted(partitions):
                part_rows = partitions[part_index]
                if not part_rows:
                    continue
                file_path = table_dir / f"part-{part_index:03d}.parquet"
                table = pa.Table.from_pylist(part_rows, schema=TABLE_SCHEMAS[table_name])
                files.append(_write_parquet(table, file_path, temp, self.config))
            if not files:
                # Empty tables still get a schema-carrying Parquet file so the
                # static site can always build a DuckDB view.
                file_path = table_dir / "part-000.parquet"
                empty = TABLE_SCHEMAS[table_name].empty_table()
                files.append(_write_parquet(empty, file_path, temp, self.config))
            tables[table_name] = {
                "rows": len(rows),
                "partitions": partition_count,
                "files": files,
            }
            log.info(
                "Exported %s rows to %s parquet file(s) for %s", len(rows), len(files), table_name
            )

        manifest = {
            "data_version": DATA_VERSION,
            "schema_version": SCHEMA_VERSION,
            "format": "parquet",
            "generated_at": iso_utc(),
            "generated_ts": now_ts(),
            "tables": tables,
            "counts": {name: tables[name]["rows"] for name in TABLE_ORDER},
            "currency": self.config.currency.model_dump(),
            "notes": (
                "Metadata only. Images and raw HTML are not stored in this branch. "
                "Queries should use the file lists in this manifest rather than guessing paths."
            ),
        }
        (temp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (temp / "schema.json").write_text(
            json.dumps(_schema_document(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (temp / "README.md").write_text(_data_readme(), encoding="utf-8")

        total_bytes = sum(file["bytes"] for table in tables.values() for file in table["files"])
        max_bytes = self.config.export.max_data_mb * 1024 * 1024
        if total_bytes > max_bytes:
            log.warning(
                "Data export is %.1f MB, above configured max_data_mb=%s. "
                "The publisher will refuse it unless --allow-large is used.",
                total_bytes / 1024 / 1024,
                self.config.export.max_data_mb,
            )

        if target.exists():
            shutil.rmtree(target)
        temp.rename(target)
        log.info("Data export ready at %s (%.1f MB)", target, total_bytes / 1024 / 1024)
        return target

    def _artist_rows(
        self,
        store: SQLiteStore,
        opt_outs: set[tuple[str, str]],
        excluded_artist_ids: set[str],
    ):
        for row in store.iter_artists_for_export():
            site = str(row["site"])
            handle = str(row["handle"])
            if _is_opted_out(site, handle, opt_outs):
                excluded_artist_ids.add(str(row["artist_id"]))
                continue
            tags = _json_list(row.get("tags_json"))
            yield {
                "artist_id": row["artist_id"],
                "site": site,
                "site_user_id": row.get("site_user_id"),
                "handle": handle,
                "display_name": row.get("display_name"),
                "profile_url": row.get("profile_url"),
                "avatar_url": row.get("avatar_url"),
                "header_url": row.get("header_url"),
                "bio": row.get("bio"),
                "tags": tags,
                "nsfw": _bool_or_none(row.get("nsfw")),
                "accepts_commissions": _bool_or_none(row.get("accepts_commissions")),
                "works_count": row.get("works_count"),
                "followers_count": row.get("followers_count"),
                "rating": row.get("rating"),
                "offerings_count": row.get("offerings_count"),
                "price_min_usd": row.get("price_min_usd"),
                "price_max_usd": row.get("price_max_usd"),
                "price_min_jpy": row.get("price_min_jpy"),
                "price_max_jpy": row.get("price_max_jpy"),
                "first_seen": row.get("first_seen"),
                "last_updated": row.get("last_updated"),
                "last_seen": row.get("last_seen"),
                "status": row.get("status"),
                "search_text": _search_text(
                    [
                        handle,
                        row.get("display_name"),
                        row.get("bio"),
                        site,
                        *tags,
                    ]
                ),
            }

    def _offering_rows(
        self,
        store: SQLiteStore,
        opt_outs: set[tuple[str, str]],
        excluded_artist_ids: set[str],
    ):
        for row in store.iter_offerings_for_export():
            if str(row["artist_id"]) in excluded_artist_ids:
                continue
            site = str(row["site"])
            handle = str(row["handle"])
            if _is_opted_out(site, handle, opt_outs):
                continue
            tags = _json_list(row.get("tags_json"))
            yield {
                "offering_id": row["offering_id"],
                "artist_id": row["artist_id"],
                "site": site,
                "handle": handle,
                "title": row.get("title"),
                "kind": row.get("kind"),
                "description": row.get("description"),
                "price_min": row.get("price_min"),
                "price_max": row.get("price_max"),
                "currency": row.get("currency"),
                "price_usd": row.get("price_usd"),
                "price_min_usd": row.get("price_min_usd"),
                "price_max_usd": row.get("price_max_usd"),
                "turnaround_days": row.get("turnaround_days"),
                "slots": row.get("slots"),
                "available": _bool_or_none(row.get("available")),
                "tags": tags,
                "source_url": row.get("source_url"),
                "first_seen": row.get("first_seen"),
                "last_updated": row.get("last_updated"),
                "active": _bool_or_none(row.get("active")),
                "search_text": _search_text(
                    [handle, row.get("title"), row.get("kind"), row.get("description"), *tags]
                ),
            }

    def _work_rows(
        self,
        store: SQLiteStore,
        opt_outs: set[tuple[str, str]],
        excluded_artist_ids: set[str],
    ):
        for row in store.iter_works_for_export():
            if str(row["artist_id"]) in excluded_artist_ids:
                continue
            site = str(row["site"])
            handle = str(row["handle"])
            if _is_opted_out(site, handle, opt_outs):
                continue
            yield {
                "work_id": row["work_id"],
                "artist_id": row["artist_id"],
                "site": site,
                "handle": handle,
                "title": row.get("title"),
                "thumb_url": row.get("thumb_url"),
                "image_urls": _json_list(row.get("image_urls_json")),
                "tags": _json_list(row.get("tags_json")),
                "created_at": row.get("created_at"),
                "source_url": row.get("source_url"),
                "first_seen": row.get("first_seen"),
                "last_updated": row.get("last_updated"),
            }

    def _price_rows(self, store: SQLiteStore, excluded_artist_ids: set[str]):
        for row in store.iter_price_history_for_export():
            if str(row["artist_id"]) in excluded_artist_ids:
                continue
            yield {
                "id": row["id"],
                "offering_id": row["offering_id"],
                "artist_id": row["artist_id"],
                "amount": row.get("amount"),
                "currency": row.get("currency"),
                "amount_usd": row.get("amount_usd"),
                "observed_at": row.get("observed_at"),
            }


def _data_readme() -> str:
    return (
        "# comms.io data branch\n\n"
        "This branch is generated by the archiver on `master`. Do not edit it by hand.\n\n"
        "- `manifest.json` is the source of truth for table files, row counts, and checksums.\n"
        "- `schema.json` describes the Parquet columns and query hints.\n"
        "- This branch is the current data version; the site mounts it at `/data/v1/`.\n\n"
        "Images, raw HTML, and per-artist JSON are intentionally not stored here.\n"
        "The website loads the manifest and queries the Parquet files with DuckDB-WASM.\n"
    )


def _write_parquet(
    table: pa.Table,
    file_path: Path,
    root: Path,
    config: AppConfig,
) -> dict[str, Any]:
    pq.write_table(
        table,
        file_path,
        compression=config.export.compression,
        row_group_size=config.export.row_group_size,
    )
    return {
        "path": file_path.relative_to(root).as_posix(),
        "rows": table.num_rows,
        "bytes": file_path.stat().st_size,
        "sha256": _sha256(file_path),
    }


def _partition_count(config: AppConfig, table_name: str) -> int:
    return {
        "artists": config.export.artist_partitions,
        "offerings": config.export.offering_partitions,
        "works": config.export.work_partitions,
        "price_history": config.export.price_history_partitions,
    }[table_name]


def _partition_rows(
    table_name: str,
    rows: list[dict[str, Any]],
    partition_count: int,
) -> dict[int, list[dict[str, Any]]]:
    partitions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    count = max(1, partition_count)
    for row in rows:
        key = str(
            row.get("artist_id")
            or row.get("offering_id")
            or row.get("work_id")
            or row.get("id")
            or ""
        )
        index = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) % count
        partitions[index].append(row)
    sort_key = {
        "artists": "artist_id",
        "offerings": "offering_id",
        "works": "work_id",
        "price_history": "id",
    }[table_name]
    for part_rows in partitions.values():
        part_rows.sort(
            key=lambda item: (str(item.get(sort_key) or ""), str(item.get("observed_at") or ""))
        )
    return partitions


def _schema_document() -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for name, schema in TABLE_SCHEMAS.items():
        tables[name] = {
            "columns": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in schema
            ]
        }
    return {
        "data_version": DATA_VERSION,
        "schema_version": SCHEMA_VERSION,
        "format": "parquet",
        "tables": tables,
        "query_hints": QUERY_HINTS,
    }


def _json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _search_text(parts: list[Any]) -> str:
    return normalize_text(" ".join(str(part) for part in parts if part))


def _is_opted_out(site: str, handle: str, opt_outs: set[tuple[str, str]]) -> bool:
    key = handle.casefold()
    return (site, key) in opt_outs or ("*", key) in opt_outs


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
