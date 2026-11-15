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
- mounts Drive and stores the SQLite checkpoint in
  `/content/drive/MyDrive/comms.io/comms.sqlite3`
- copies the `data` branch to a local worktree
- runs a bounded crawl, exports Parquet, validates, and publishes

A normal daily run should use conservative limits. If the session disconnects,
rerun the notebook; the frontier and SQLite database resume where they stopped.

The notebook does not store tokens in the repository or print them.
