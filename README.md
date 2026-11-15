# comms.io website

Static frontend for the `data` branch. It uses Svelte + Vite + DuckDB-WASM.

## Local development

From the archiver repo, generate a data snapshot:

```powershell
.\.venv\Scripts\comms.exe export
```

Then from this branch:

```powershell
$env:COMMS_WEBSITE_DATA = "C:\path\to\comms.io\dist\data\v1"
npm.cmd install
npm.cmd run dev
```

`npm run dev` copies the snapshot into `public/data/v1` (ignored by git).

## Build

```powershell
npm.cmd run build
```

A successful `website-ci` run triggers `deploy-on-website` on `master`, which
calls the reusable Pages workflow. It builds this branch and writes a
`data-config.json` that points at:

```text
https://raw.githubusercontent.com/Elfiawesome/comms.io/data/
```

The Pages artifact contains only the frontend. The database stays in the
`data` branch and is read directly through raw.githubusercontent.com.

## Data layout

On boot the site resolves the data base in this order:

1. `?data=<url>` query parameter
2. `data-config.json` next to the deployed site
3. same-origin `data/v1/` (local development fallback)

It then reads `manifest.json` and queries the Parquet files listed in it with
DuckDB-WASM. Parquet URLs are cache-busted with the manifest `build_id`.

## Watchlists and lists

Watchlists are local-first and stored in `localStorage`. You can create named
lists (for example `Favorites`, `Historical`, `Gift ideas`), move saved artists
between them, and export/import the whole collection as JSON. Public curated
albums can be compiled from static files in a later step.
