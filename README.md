# COMMS.IO

A static, modular commission archive for Skeb, CREPE, and other artist
commission platforms.

The project has three branches:

| Branch | Purpose |
| --- | --- |
| `master` | Archiver application, shared schema, CLI, tests, Colab notebook |
| `data` | Generated database snapshot (Parquet + chunked SQLite state) |
| `website` | Static frontend, deployed to GitHub Pages |

## How it fits together

```text
data branch (raw.githubusercontent.com)
  ├── v1 Parquet + manifest  ──> website (DuckDB-WASM in the browser)
  └── state/ chunks           ──> Colab download, crawl, republish

master branch = archiver, schema, CLI, tests, notebook, docs
website branch = static frontend source
```

The archiver never commits raw images, HTML, or per-artist JSON. The `data`
branch is a generated artifact containing:

- normalized Parquet shards and `manifest.json` for the website
- a compressed, chunked snapshot of the SQLite working database in `state/`

The site reads the data branch through `raw.githubusercontent.com`, so data
updates appear without a Pages rebuild. The frontend is small; the 1 GB Pages
limit is not used for the database.

GitHub repositories are **not unlimited**: files are blocked above 100 MiB and
GitHub recommends staying under 1–5 GB. The state snapshot is chunked below
40 MiB, and the publisher force-pushes a squashed `data` snapshot to avoid
history growth.

## Repository setup

1. Set the default branch to `master`.
2. Open **Settings → Pages** and set **Source: GitHub Actions**.
3. Add `GITHUB_TOKEN` as a Colab secret with `contents: write`.
4. Run the Colab notebook. It downloads the state snapshot, crawls, exports,
   and publishes the updated `data` branch. No Drive mount is used.
5. Run **Actions → deploy-site → Run workflow** once to publish the frontend
   after Pages is enabled. Later website-branch pushes deploy automatically.

The `data` branch currently contains a two-artist smoke test from a tiny,
rate-limited run. The daily crawler replaces it with the full snapshot.

`getter/` is a local scratch folder and is intentionally ignored. Its discovery
logic (gallery-dl JSON → Skeb/CREPE seeds) is reimplemented in
`src/comms/seeds.py` and the optional Twitter seed import.

## Quick start (local)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\comms.exe --help
```

Create a local config:

```powershell
Copy-Item config\comms.example.toml config\comms.toml
```

Run a very small, rate-limited Skeb refresh:

```powershell
.\.venv\Scripts\comms.exe crawl --config config\comms.toml --site skeb --refresh 5 --limit 5
```

Export and inspect:

```powershell
.\.venv\Scripts\comms.exe export --config config\comms.toml
.\.venv\Scripts\comms.exe validate --data-dir dist\data\v1
```

## Google Colab

Open `notebooks/comms_colab.ipynb`. It runs in a fresh VM with no Drive mount:

1. `comms state unpack` downloads the compressed SQLite state from the `data`
   branch through raw.githubusercontent.com.
2. The crawler resumes from that frontier and updates SQLite locally in
   `/content`.
3. `comms crawl --publish` exports Parquet, packs a new chunked state snapshot,
   and force-pushes both to `data`.
4. The website immediately reads the new raw snapshot.

Required Colab secrets:

- `GITHUB_TOKEN` — fine-grained token with `contents: write` for the repository
- `SKEB_COOKIE` — optional; the Skeb source can extract `request_key` itself
- `CREPE_COOKIE` — optional; only needed if a future Crepe endpoint requires it

GitHub Pages must be configured with **Source: GitHub Actions** in repository
Settings → Pages.

## Safety and scale

Default settings are deliberately conservative: one request per second per
site, low concurrency, jitter, adaptive backoff on HTTP 429, and hard run
budgets. Do not disable these on shared IPs such as Colab or CI.

The archive stores metadata only. Images are referenced by URL, not copied.
See `docs/architecture.md` and `docs/data-format.md` for the full design.

## Branch workflow

```text
master   archiver + docs + CI + Colab notebook
website  Svelte/Vite frontend; deploys Pages on push
data     generated Parquet + state snapshot; force-pushed by the publisher
```

Do not edit the `data` branch by hand. The publisher replaces it with a
squashed snapshot. The site reads it from raw.githubusercontent.com; the Pages
artifact contains only the frontend and a `data-config.json` pointer.

## Useful commands

```powershell
# Import old markdown albums / seed lists without fetching
.\.venv\Scripts\comms.exe seed --file seeds\skeb_album.md --site skeb

# Import gallery-dl metadata from the old getter workflow
.\.venv\Scripts\comms.exe seed --gallery-dl-dir work\gallery-dl

# Small manual run
.\.venv\Scripts\comms.exe crawl --limit 5 --no-discover --no-refresh --file seeds\smoke.md

# Export Parquet + state, validate, publish
.\.venv\Scripts\comms.exe export
.\.venv\Scripts\comms.exe validate
.\.venv\Scripts\comms.exe publish

# State snapshot management
.\.venv\Scripts\comms.exe state pack
.\.venv\Scripts\comms.exe state unpack --repo Elfiawesome/comms.io --branch data
.\.venv\Scripts\comms.exe state status
```
