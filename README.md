# COMMS.IO

A static, modular commission archive for Skeb, CREPE, and other artist
commission platforms.

The project has three branches:

| Branch | Purpose |
| --- | --- |
| `master` | Archiver application, shared schema, CLI, tests, Colab notebook |
| `data` | Generated static database (Parquet + manifest), published by the archiver |
| `website` | Static frontend, built and deployed with the `data` branch |

## How it fits together

```text
gallery-dl / seeds -> site discovery -> SQLite working DB -> Parquet -> data branch
                                                                  |
                                                  website build + data -> GitHub Pages
```

The archiver never commits raw images, HTML, or per-artist JSON. The `data`
branch is a generated artifact containing normalized Parquet files and a
manifest. The site queries those files in the browser with DuckDB-WASM.

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

Open `notebooks/comms_colab.ipynb`. It mounts Google Drive for the SQLite
checkpoint, reads secrets from `google.colab.userdata`, runs an incremental
crawl, exports, and optionally publishes the `data` branch.

Required Colab secrets:

- `GITHUB_TOKEN` — fine-grained token with `contents: write` and `actions: write`
  for the repository. `contents: write` publishes the data branch; `actions:
  write` lets the publisher trigger the Pages deploy workflow.
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
