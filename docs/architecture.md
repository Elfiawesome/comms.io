# Architecture

## Branches

| Branch | Contents |
| --- | --- |
| `master` | Archiver app, shared schema, CLI, tests, Colab notebook, workflows |
| `data` | Generated Parquet + chunked SQLite state (single squashed snapshot) |
| `website` | Static frontend source, built into the Pages artifact |

`data` is an artifact branch, not a crawl log. The publisher replaces it with
a squashed snapshot by default. This is deliberate: the previous
`skeb-archiver` repository grew to roughly 34 GB because every crawl produced
new per-artist JSON history.

## Daily flow

```text
Colab / GitHub Actions
  -> download state/ chunks from the data branch (raw.githubusercontent.com)
  -> import seeds (gallery-dl JSON, markdown albums, manual CSVs)
  -> discover a bounded number of new artists
  -> refresh due artists from the restored SQLite frontier
  -> normalize into SQLite
  -> export deterministic Parquet shards
  -> pack the SQLite database into state/ chunks
  -> validate manifest and checksums
  -> publish squashed data branch
  -> website reads the new raw Parquet immediately
```

The frontier and SQLite database are the resumable state. It lives in the
`data` branch, so a fresh Colab VM or runner can resume without Drive. Raw
source payloads are disabled by default because they can grow very large; the
normalized SQLite database is the archive. If Colab disconnects before it
publishes, the next run resumes from the last published state snapshot.

## Sources

Built-in sources register through `comms.registry.register_source`:

- `skeb` — public profile API, cookie extraction, conservative adaptive rate
  limiting, skills as offerings, and the paginated creator works endpoint.
  The works endpoint returns at most 30 items per request, so the source pages
  through it. After the first full crawl it stops as soon as a page contains no
  works that are not already in SQLite.
- `crepe` — public SSR profile pages. The page's `vike_pageContext` JSON is
  parsed directly, avoiding a browser. Commission type detail pages provide
  min/max prices.

Discovery is separate from fetching:

- Skeb listing pages (bounded by `discover_pages`).
- CREPE homepage (robots.txt allows `/en$` and profile pages `/en/@...`).
- gallery-dl JSON metadata from X, imported as seed handles.
- Optional link-in-bio resolver for lit.link/linktree/carrd/etc. pages found in
  X metadata. It is rate-limited and disabled by default.
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
- Parquet is columnar and compresses well. The site reads it from
  `raw.githubusercontent.com`, and DuckDB-WASM fetches the shards listed in
  the manifest. Raw GitHub does not guarantee HTTP range reads, so keep
  individual Parquet shards reasonably small.
- Tables are partitioned by a stable hash of `artist_id`.
- The SQLite database is gzip-compressed and chunked below 40 MiB per file in
  `state/`, avoiding GitHub's 100 MiB file block.
- The data branch is replaced as a snapshot, not appended forever.
- The Pages artifact contains only the frontend (plus a `data-config.json`
  pointer), so the 1 GB Pages data limit does not apply.
- GitHub repositories are not unlimited: files are capped at 100 MiB and
  GitHub recommends staying under 1–5 GB. If the archive outgrows that, move
  Parquet/state to R2 or Hugging Face and keep the manifest in `data`.
