# Seeds

Drop small seed lists here. The crawler reads this directory by default.

Supported formats:

- Plain text or Markdown with `skeb.jp/@handle` / `crepe.cm/@handle` links
- The old `skeb_album.md` format
- CSV with `skeb_handle` / `crepe_handle` columns
- JSON or JSONL; any string containing a profile link is scanned

Examples:

```text
skeb:@some_artist
crepe:@some_artist
```

Use `comms seed --file <path>` to import without fetching, or
`comms crawl --file <path>` to import and fetch in one run.

Do not put cookies or tokens here.
