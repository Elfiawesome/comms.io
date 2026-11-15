from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import typer

from comms.bio_links import follow_bio_links
from comms.config import AppConfig, load_config
from comms.exporters.parquet import ParquetExporter
from comms.logging import get_logger, setup_logging
from comms.models import Seed
from comms.pipeline import Pipeline, load_opt_outs
from comms.publish.github import GitPublisher, PublishError
from comms.registry import available_sources
from comms.seeds import (
    import_gallery_dl_metadata,
    load_seed_dir,
    load_seed_file,
    run_gallery_dl,
    scan_gallery_dl_bio_links,
)
from comms.state import (
    StateError,
    download_state,
    fetch_state_manifest,
    pack_state,
)
from comms.store.sqlite import SQLiteStore
from comms.validate import ValidationError, validate_data_dir

app = typer.Typer(
    name="comms",
    help="Static commission archive for Skeb, CREPE, and other platforms.",
    no_args_is_help=True,
    add_completion=False,
)
state_app = typer.Typer(help="Manage the SQLite state snapshot stored in the data branch.")
app.add_typer(state_app, name="state")
log = get_logger("cli")

DEFAULT_CONFIG = Path("config/comms.example.toml")
LOCAL_CONFIG = Path("config/comms.toml")


def _load(config_path: str | None, log_level: str = "INFO") -> AppConfig:
    path = (
        Path(config_path)
        if config_path
        else (LOCAL_CONFIG if LOCAL_CONFIG.exists() else DEFAULT_CONFIG)
    )
    config = load_config(path)
    log_file = Path("work/logs/comms.log")
    setup_logging(log_level, log_file)
    return config


def _open_store(config: AppConfig) -> SQLiteStore:
    return SQLiteStore(
        config.database_path,
        save_raw_payloads=config.storage.save_raw_payloads,
    )


@app.command()
def init() -> None:
    """Create local config and working directories."""
    Path("work").mkdir(exist_ok=True)
    Path("seeds").mkdir(exist_ok=True)
    if not LOCAL_CONFIG.exists():
        shutil.copy2(DEFAULT_CONFIG, LOCAL_CONFIG)
        typer.echo(f"Created {LOCAL_CONFIG}")
    else:
        typer.echo(f"Already exists: {LOCAL_CONFIG}")
    typer.echo("Next: edit config/comms.toml, then run `comms crawl --limit 5`.")


@app.command()
def sites() -> None:
    """List registered source plugins."""
    for name in available_sources():
        typer.echo(name)


@app.command()
def seed(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    files: list[str] | None = typer.Option(
        None, "--file", "-f", help="Seed file (.md/.txt/.csv/.json)"
    ),
    directories: list[str] | None = typer.Option(
        None, "--dir", "-d", help="Directory of seed files"
    ),
    gallery_dl_dir: str | None = typer.Option(
        None, "--gallery-dl-dir", help="gallery-dl JSON metadata directory"
    ),
    site: str | None = typer.Option(None, "--site", help="Default site for plain handles"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Import seed files into the frontier without fetching anything."""
    config = _load(config_path, log_level)
    seeds: list[Seed] = []
    for file_name in files or []:
        seeds.extend(load_seed_file(file_name, default_site=site, priority=100))
    for directory in directories or []:
        seeds.extend(load_seed_dir(directory, priority=100))
    if gallery_dl_dir:
        seeds.extend(import_gallery_dl_metadata(gallery_dl_dir))
    seeds.extend(_seed_dir_from_config(config))
    if not seeds:
        typer.echo("No seeds found.", err=True)
        raise typer.Exit(1)
    with _open_store(config) as store:
        for item in _dedupe_seeds(seeds):
            store.enqueue(
                item.site, item.handle, priority=item.priority, source=item.source, reset=True
            )
        store.conn.commit()
        typer.echo(f"Queued {len(_dedupe_seeds(seeds))} seed(s).")
        typer.echo(json.dumps(store.queued_count(), indent=2))


@app.command()
def crawl(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    site: list[str] | None = typer.Option(None, "--site", help="Limit to one or more sources"),
    files: list[str] | None = typer.Option(None, "--file", "-f", help="Extra seed file"),
    directories: list[str] | None = typer.Option(None, "--dir", "-d", help="Extra seed directory"),
    gallery_dl_dir: str | None = typer.Option(
        None, "--gallery-dl-dir", help="gallery-dl JSON metadata directory"
    ),
    run_gallery_dl_now: bool = typer.Option(
        False, "--run-gallery-dl", help="Run gallery-dl before importing"
    ),
    discover: bool = typer.Option(True, "--discover/--no-discover"),
    refresh: bool = typer.Option(True, "--refresh/--no-refresh"),
    refresh_all: bool = typer.Option(
        False,
        "--refresh-all",
        help="Refresh every artist, ignoring refresh_stale_hours",
    ),
    limit: int = typer.Option(
        0, "--limit", help="Max artists fetched per site (0 = until frontier empty)"
    ),
    max_runtime: float | None = typer.Option(
        None, "--max-runtime", help="Override max runtime in minutes"
    ),
    sync_state: bool = typer.Option(
        False,
        "--sync-state",
        help="Download the latest SQLite state snapshot from the data branch before crawling",
    ),
    publish: bool = typer.Option(
        False, "--publish/--no-publish", help="Export and publish data after crawling"
    ),
    allow_large: bool = typer.Option(
        False, "--allow-large", help="Allow publishing above max_data_mb"
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run a resumable, rate-limited crawl."""
    config = _load(config_path, log_level)
    if max_runtime is not None:
        config.run.max_runtime_minutes = max_runtime
    if refresh_all:
        config.run.refresh_stale_hours = 0.0

    if sync_state:
        try:
            state_manifest = download_state(
                config.publish.repo,
                config.publish.branch,
                config.database_path,
            )
        except StateError as exc:
            typer.echo(f"Could not download state: {exc}", err=True)
            raise typer.Exit(1) from exc
        if state_manifest:
            typer.echo(json.dumps({"state_restored": state_manifest.get("counts", {})}, indent=2))
        else:
            typer.echo("No state snapshot found; starting with an empty database.")

    seeds: list[Seed] = []
    for file_name in files or []:
        seeds.extend(load_seed_file(file_name, priority=100))
    for directory in directories or []:
        seeds.extend(load_seed_dir(directory, priority=100))
    metadata_dirs: list[Path] = []
    if run_gallery_dl_now:
        output = run_gallery_dl(
            config.sources.twitter, workspace=Path(config.sources.twitter.metadata_dir)
        )
        metadata_dirs.append(output)
    if gallery_dl_dir:
        metadata_dirs.append(Path(gallery_dl_dir))
    if config.sources.twitter.enabled and Path(config.sources.twitter.metadata_dir).exists():
        metadata_dirs.append(Path(config.sources.twitter.metadata_dir))
    for metadata_dir in dict.fromkeys(metadata_dirs):
        seeds.extend(import_gallery_dl_metadata(metadata_dir))

    if config.sources.twitter.follow_bio_links and metadata_dirs:
        bio_links: list[str] = []
        for metadata_dir in dict.fromkeys(metadata_dirs):
            bio_links.extend(
                scan_gallery_dl_bio_links(
                    metadata_dir,
                    limit=config.sources.twitter.max_bio_links,
                )
            )
        bio_links = list(dict.fromkeys(bio_links))[: config.sources.twitter.max_bio_links]
        if bio_links:
            typer.echo(f"Following {len(bio_links)} bio link(s)…")
            seeds.extend(
                asyncio.run(
                    follow_bio_links(
                        bio_links,
                        config,
                        max_links=config.sources.twitter.max_bio_links,
                    )
                )
            )

    seeds.extend(_seed_dir_from_config(config))

    with _open_store(config) as store:
        pipeline = Pipeline(config, store)
        stats = asyncio.run(
            pipeline.run(
                sites=site,
                seeds=_dedupe_seeds(seeds),
                discover=discover,
                refresh=refresh,
                limit=limit,
            )
        )
        typer.echo(json.dumps([item.model_dump() for item in stats], indent=2))
        typer.echo(json.dumps({"counts": store.counts(), "queue": store.queued_count()}, indent=2))

    if publish:
        _export_and_publish(config, allow_large=allow_large)


@app.command()
def export(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Override export directory"),
    state: bool = typer.Option(
        True, "--state/--no-state", help="Include the chunked SQLite state snapshot"
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Export the SQLite archive to static Parquet files."""
    config = _load(config_path, log_level)
    if data_dir:
        config.paths.export_dir = data_dir
    _export(config, include_state=state)


@app.command()
def publish(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    data_dir: str | None = typer.Option(None, "--data-dir"),
    message: str | None = typer.Option(None, "--message", "-m"),
    allow_large: bool = typer.Option(False, "--allow-large"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Publish the generated data directory to the data branch."""
    config = _load(config_path, log_level)
    source = Path(data_dir) if data_dir else config.export_path
    try:
        result = GitPublisher(config).publish(
            source,
            message=message,
            allow_large=allow_large,
            dry_run=dry_run,
        )
    except PublishError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command()
def validate(
    data_dir: str | None = typer.Option(None, "--data-dir"),
    max_data_mb: int = typer.Option(4096, "--max-data-mb"),
    config_path: str | None = typer.Option(None, "--config", "-c"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Validate a generated data directory."""
    config = _load(config_path, log_level)
    source = Path(data_dir) if data_dir else config.export_path
    try:
        report = validate_data_dir(source, max_data_mb=max_data_mb)
    except ValidationError as exc:
        typer.echo(f"INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(report, indent=2))


@app.command()
def status(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Show archive and frontier counts."""
    config = _load(config_path, log_level)
    if not config.database_path.exists():
        typer.echo(f"Database not found: {config.database_path}", err=True)
        raise typer.Exit(1)
    with _open_store(config) as store:
        typer.echo(json.dumps({"counts": store.counts(), "queue": store.queued_count()}, indent=2))


@app.command()
@state_app.command("pack")
def state_pack(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    database: str | None = typer.Option(None, "--database", help="SQLite database to snapshot"),
    output: str | None = typer.Option(
        None, "--output", help="State directory (default: <export>/state)"
    ),
    chunk_mb: int | None = typer.Option(None, "--chunk-mb"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Compress and chunk the SQLite database into the data snapshot."""
    config = _load(config_path, log_level)
    db_path = Path(database) if database else config.database_path
    target = Path(output) if output else config.export_path / "state"
    try:
        manifest = pack_state(
            db_path,
            target,
            chunk_size_mb=chunk_mb or config.storage.state_chunk_mb,
        )
    except Exception as exc:
        typer.echo(f"State pack failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(manifest, indent=2))


@state_app.command("unpack")
def state_unpack(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    repo: str | None = typer.Option(None, "--repo", help="owner/repo"),
    branch: str | None = typer.Option(None, "--branch"),
    data_base: str | None = typer.Option(None, "--data-base", help="Override raw data base URL"),
    database: str | None = typer.Option(None, "--database", help="Destination SQLite path"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Download the latest SQLite state snapshot from the data branch."""
    config = _load(config_path, log_level)
    try:
        manifest = download_state(
            repo or config.publish.repo,
            branch or config.publish.branch,
            Path(database) if database else config.database_path,
            data_base=data_base,
        )
    except StateError as exc:
        typer.echo(f"State unpack failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if manifest is None:
        typer.echo("No state snapshot found; nothing was downloaded.")
        return
    typer.echo(json.dumps(manifest, indent=2))


@state_app.command("status")
def state_status(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    repo: str | None = typer.Option(None, "--repo"),
    branch: str | None = typer.Option(None, "--branch"),
    data_base: str | None = typer.Option(None, "--data-base"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Show the remote state snapshot metadata."""
    config = _load(config_path, log_level)
    try:
        manifest = fetch_state_manifest(
            repo or config.publish.repo,
            branch or config.publish.branch,
            data_base=data_base,
        )
    except StateError as exc:
        typer.echo(f"State status failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if manifest is None:
        typer.echo("No remote state snapshot found.")
        raise typer.Exit(1)
    typer.echo(json.dumps(manifest, indent=2))


def doctor(
    config_path: str | None = typer.Option(None, "--config", "-c"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Check local setup and print effective paths."""
    config = _load(config_path, log_level)
    report = {
        "python": sys.version.split()[0],
        "config": str(
            Path(config_path)
            if config_path
            else (LOCAL_CONFIG if LOCAL_CONFIG.exists() else DEFAULT_CONFIG)
        ),
        "database": str(config.database_path),
        "export_dir": str(config.export_path),
        "sources": available_sources(),
        "gallery_dl_metadata_dir": config.sources.twitter.metadata_dir,
        "opt_out_file": config.compliance.opt_out_file,
        "state_enabled": config.storage.state_enabled,
        "state_chunk_mb": config.storage.state_chunk_mb,
        "save_raw_payloads": config.storage.save_raw_payloads,
        "publish_repo": config.publish.repo,
        "publish_branch": config.publish.branch,
    }
    typer.echo(json.dumps(report, indent=2))


def _export_and_publish(config: AppConfig, *, allow_large: bool) -> None:
    target = _export(config)
    try:
        result = GitPublisher(config).publish(target, allow_large=allow_large)
    except PublishError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, indent=2))


def _export(config: AppConfig, *, include_state: bool = True) -> Path:
    opt_outs = load_opt_outs(config.compliance.opt_out_file)
    pairs: set[tuple[str, str]] = set()
    for site, handles in opt_outs.items():
        for handle in handles:
            pairs.add((site, handle))
    with _open_store(config) as store:
        exporter = ParquetExporter(config)
        target = exporter.export(store, opt_out_pairs=pairs)

    state_report = None
    if include_state and config.storage.state_enabled and config.database_path.exists():
        try:
            state_manifest = pack_state(
                config.database_path,
                target / "state",
                chunk_size_mb=config.storage.state_chunk_mb,
            )
            state_report = {
                "chunks": len(state_manifest["chunks"]),
                "compressed_bytes": state_manifest["compressed_bytes"],
                "uncompressed_bytes": state_manifest["uncompressed_bytes"],
                "counts": state_manifest["counts"],
            }
        except Exception as exc:
            typer.echo(f"State snapshot failed: {exc}", err=True)
            raise typer.Exit(1) from exc

    try:
        report = validate_data_dir(target, max_data_mb=config.export.max_data_mb)
    except ValidationError as exc:
        typer.echo(f"Export validation failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    payload = {"export": str(target), "validation": report}
    if state_report is not None:
        payload["state"] = state_report
    typer.echo(json.dumps(payload, indent=2))
    return target


def _seed_dir_from_config(config: AppConfig) -> list[Seed]:
    directory = Path(config.paths.seed_dir)
    return load_seed_dir(directory, priority=100) if directory.exists() else []


def _dedupe_seeds(seeds: list[Seed]) -> list[Seed]:
    result: dict[tuple[str, str], Seed] = {}
    for item in seeds:
        key = (item.site, item.handle.casefold())
        existing = result.get(key)
        if existing is None:
            result[key] = item
        else:
            existing.priority = max(existing.priority, item.priority)
            if not existing.url and item.url:
                existing.url = item.url
    return sorted(
        result.values(), key=lambda item: (-item.priority, item.site, item.handle.casefold())
    )


if __name__ == "__main__":
    app()
