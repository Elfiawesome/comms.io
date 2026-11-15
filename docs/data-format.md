# Data format

The `data` branch contains only generated files. `manifest.json` is the
source of truth; clients must not guess file paths.

The site fetches the branch root from `raw.githubusercontent.com` and reads
`manifest.json` from there.

```text
manifest.json
schema.json
README.md
artists/part-000.parquet ...
offerings/part-000.parquet ...
works/part-000.parquet ...
price_history/part-000.parquet ...
state/manifest.json
state/part-00000.bin ...
```

## Manifest

```json
{
  "data_version": 1,
  "schema_version": 1,
  "format": "parquet",
  "build_id": "1794728665",
  "generated_at": "2026-11-15T00:00:00Z",
  "tables": {
    "artists": {
      "rows": 123,
      "partitions": 8,
      "files": [
        {
          "path": "artists/part-000.parquet",
          "rows": 20,
          "bytes": 1234,
          "sha256": "..."
        }
      ]
    }
  },
  "counts": {"artists": 123, "offerings": 456, "works": 789, "price_history": 1000},
  "currency": {"usd_per_jpy": 0.0067, "usd_per_krw": 0.00075, "usd_per_usd": 1.0}
}
```

## Tables

- `artists` — one row per artist. Includes sorted-filter helpers
  `price_min_usd`, `price_max_usd`, `price_min_jpy`, `price_max_jpy`,
  `offerings_count`, `last_updated`, and `search_text`.
- `offerings` — one row per commission type/skill. Prices are stored in the
  original currency (`price_min`, `price_max`, `currency`) and normalized USD
  fields for sorting.
- `works` — optional work/portfolio metadata and thumbnail URLs. No images are
  stored in Git.
- `price_history` — append-only observations. A new row is written only when
  the amount or currency changes.

## Website querying

The site should:

1. Fetch `manifest.json` from the configured raw data base.
2. Build explicit file URL lists from `manifest.tables.<name>.files`.
3. Append `?v=<build_id>` to each Parquet URL so a force-pushed snapshot
   invalidates browser/CDN caches.
4. Use `read_parquet([...])` with DuckDB-WASM rather than globbing a remote
   directory.
5. Select only the columns needed for the current view.
6. Use parameter binding for search and filter values.

Same-origin data is still supported for local development. The production
deploy writes `data-config.json` with:

```json
{"base":"https://raw.githubusercontent.com/Elfiawesome/comms.io/data/"}
```

A `?data=<url>` query parameter can override the data source at runtime.

## State snapshot

`state/manifest.json` describes a gzip-compressed SQLite database split into
chunks smaller than 40 MiB. The Colab notebook downloads the chunks, verifies
their checksums, joins and decompresses them, and replaces its local
`work/comms.sqlite3`. After crawling, the exporter packs a fresh snapshot.
Only the latest state is kept in the squashed data branch; old snapshots are
not retained in Git history.

## Schema changes

- Additive nullable columns can stay in the same `data_version`.
- Renames, type changes, or removed columns require a new `data_version`
  directory (`v2/`) and a site that can read both while the branch migrates.
- `schema.json` is the machine-readable contract for both the exporter and the
  frontend.
