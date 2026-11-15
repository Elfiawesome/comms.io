# Google Colab workflow

1. Open `notebooks/comms_colab.ipynb`.
2. Add these secrets in Colab's key panel:
   - `GITHUB_TOKEN` — fine-grained token with `contents: write` on the repo
   - `SKEB_COOKIE` — optional, only if you want a pre-supplied `request_key`
   - `CREPE_COOKIE` — optional
3. Run all cells.

The notebook:

- clones/updates the repo in `/content/comms.io`
- creates a local venv and installs the package
- runs `comms state unpack`, which downloads the chunked SQLite snapshot from
  the `data` branch through raw.githubusercontent.com
- crawls with conservative budgets, updates SQLite in `/content`, exports
  Parquet, packs the new state snapshot, validates, and publishes `data`
- does **not** mount Google Drive; every run can use a fresh Colab VM

Data updates appear on the website immediately because the frontend reads the
`data` branch through raw.githubusercontent.com. A Pages redeploy is only
needed when the `website` branch changes.

A normal daily run should use conservative limits. If the session disconnects
before publishing, the next run resumes from the last published state snapshot.

The notebook does not store tokens in the repository or print them.
