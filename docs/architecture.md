# Architecture

## Branches

| Branch | Contents |
| --- | --- |
| `master` | Archiver app, shared schema, CLI, tests, Colab notebook, workflows |
| `data` | Generated Parquet database + manifest (single squashed snapshot) |
| `website` | Static frontend source, built into the Pages artifact |

`data` is an artifact branch, not a crawl log. The publisher replaces it with
a squashed snapshot by default. This is deliberate: the previous
`skeb-archiver` repository grew to roughly 34 GB because every crawl produced
new per-artist JSON history.

## Daily flow

```text
Colab / GitHub Actions
  -> import seeds (gallery-dl JSON, markdown albums, manual CSVs)
  -> discover a bounded number of new artists
  -> refresh due artists from SQLite frontier
  -> normalize into SQLite
  -> export deterministic Parquet shards
  -> validate manifest and checksums
  -> publish squashed data branch
  -> Pages workflow rebuilds website + data
```

The frontier and SQLite database are the resumable state. If Colab disconnects,
the next run continues from the same queue. Raw payloads are optional and are
compressed in SQLite for debugging; they are never exported.

## Sources

Built-in sources register through `comms.registry.register_source`:

- `skeb` — public profile API, cookie extraction, conservative adaptive rate
  limiting, skills as offerings, received works as works.
- `crepe` — public SSR profile pages. The page's `vike_pageContext` JSON is
  parsed directly, avoiding a browser. Commission type detail pages provide
  min/max prices.

Discovery is separate from fetching:

- Skeb listing pages (bounded by `discover_pages`).
- CREPE homepage (robots.txt allows `/en$` and profile pages `/en/@...`).
- gallery-dl JSON metadata from X, imported as seed handles.
- Markdown/CSV/JSON seed files, including the old `skeb_album.md` format.

Third-party sources can be installed as Python packages exposing the
`comms.sources` entry-point group, or dropped into the registry during local
development. The source contract is in `src/comms/sources/base.py`.

## Avoidance and compliance

- Per-domain token bucket with jitter.
- Low concurrency by default.
- Adaptive backoff on HTTP 429 and a hard stop after repeated 429s.
- Per-run request and time budgets.
- robots.txt checks are enabled by default and fail open only when robots.txt
  itself cannot be read; a successful deny always wins.
- `config/opt-out.txt` supports per-site handles and global handles, and the
  exporter removes opted-out artists, their offerings, works, and prices.
- Only public data is fetched. No authentication bypass, paywall bypass, or
  private endpoint enumeration.

## Scale

The archive is metadata-only. Images stay at the source URLs. For 500k+ rows:

- SQLite handles working state and incremental updates.
- Parquet is columnar and compresses well; DuckDB-WASM reads only required
  columns and row groups via HTTP range requests.
- Tables are partitioned by a stable hash of `artist_id`, so daily changes
  only rewrite affected shards.
- The data branch is replaced as a snapshot, not appended forever.
- Page assets must stay under GitHub Pages' 1 GB published-site and soft
  100 GB/month bandwidth limits. If data grows beyond that, the manifest can
  point to Cloudflare R2 or Hugging Face while the `data` branch keeps the
  manifest and schema.
