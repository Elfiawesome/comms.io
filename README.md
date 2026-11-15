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

The GitHub Actions deploy workflow builds this branch, copies the `data` branch
to `dist/data/v1`, and publishes the combined artifact to GitHub Pages.

## Data layout

The site reads `data/v1/manifest.json`, then queries the Parquet files listed in
the manifest with DuckDB-WASM. It never downloads the whole database.

## Watchlists

Watchlists are local-first and stored in `localStorage`. Use the export/import
buttons to move them between browsers. Public curated albums will be compiled
from static files in a later step.
