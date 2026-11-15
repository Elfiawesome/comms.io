from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ConfigBase(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PathsConfig(ConfigBase):
    database: str = "work/comms.sqlite3"
    export_dir: str = "dist/data/v1"
    seed_dir: str = "seeds"


class NetworkConfig(ConfigBase):
    user_agent: str = "comms.io/0.1 (+https://github.com/Elfiawesome/comms.io)"
    respect_robots: bool = True
    timeout_seconds: int = 30
    max_retries: int = 3
    requests_per_second: float = 1.0
    max_concurrency: int = 2


class RunConfig(ConfigBase):
    max_runtime_minutes: float = 180.0
    max_requests: int = 2000
    max_new_artists: int = 500
    max_refresh_artists: int = 2000
    refresh_stale_hours: float = 20.0
    rate_limit_stop_after: int = 5


class SkebConfig(ConfigBase):
    enabled: bool = True
    discover_pages: int = 2
    discover_genre: str = "art"
    page_size: int = 90
    max_works_per_artist: int = 0
    # Skeb caps this endpoint at 30 even when a larger limit is requested.
    work_page_size: int = 30
    # 0 = fetch all pages. Daily refreshes stop early once a page contains no
    # works that are not already in SQLite.
    max_work_pages: int = 0
    extract_cookie: bool = True
    impersonate: str = "chrome120"


class CrepeConfig(ConfigBase):
    enabled: bool = True
    discover_homepage: bool = True
    language: str = "en"
    max_offerings_per_artist: int = 30
    fetch_offering_details: bool = True
    impersonate: str = "chrome120"


class TwitterConfig(ConfigBase):
    enabled: bool = True
    metadata_dir: str = "work/gallery-dl"
    run_gallery_dl: bool = False
    gallery_dl_config: str = "config/gallery-dl.example.json"
    gallery_dl_url: str = "https://x.com/search?q=skeb&f=live"
    gallery_dl_sleep: float = 3.0
    cookies_file: str = "cookies.txt"


class SourcesConfig(ConfigBase):
    skeb: SkebConfig = Field(default_factory=SkebConfig)
    crepe: CrepeConfig = Field(default_factory=CrepeConfig)
    twitter: TwitterConfig = Field(default_factory=TwitterConfig)


class ExportConfig(ConfigBase):
    format: str = "parquet"
    compression: str = "zstd"
    row_group_size: int = 50000
    artist_partitions: int = 8
    offering_partitions: int = 16
    work_partitions: int = 32
    price_history_partitions: int = 32
    max_data_mb: int = 900


class PublishConfig(ConfigBase):
    branch: str = "data"
    remote: str = "origin"
    squash: bool = True
    backup_dir: str = "work/data-backups"
    repo: str = "Elfiawesome/comms.io"
    trigger_deploy: bool = True
    deploy_workflow: str = "deploy-site.yml"
    deploy_ref: str = "master"


class ComplianceConfig(ConfigBase):
    opt_out_file: str = "config/opt-out.txt"


class CurrencyConfig(ConfigBase):
    usd_per_jpy: float = 0.0067
    usd_per_krw: float = 0.00075
    usd_per_usd: float = 1.0


class AppConfig(ConfigBase):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)
    currency: CurrencyConfig = Field(default_factory=CurrencyConfig)

    @property
    def database_path(self) -> Path:
        return Path(self.paths.database)

    @property
    def export_path(self) -> Path:
        return Path(self.paths.export_dir)


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    _apply_env_overrides(data)
    return AppConfig.model_validate(data)


def _apply_env_overrides(data: dict) -> None:
    """Small, explicit env overrides for Colab/CI without committing a config."""
    mappings = {
        "COMMS_DATABASE": ("paths", "database"),
        "COMMS_EXPORT_DIR": ("paths", "export_dir"),
        "COMMS_SEED_DIR": ("paths", "seed_dir"),
        "COMMS_GALLERY_DL_DIR": ("sources", "twitter", "metadata_dir"),
        "COMMS_OPT_OUT_FILE": ("compliance", "opt_out_file"),
        "COMMS_DATA_BRANCH": ("publish", "branch"),
        "COMMS_REMOTE": ("publish", "remote"),
        "COMMS_MAX_DATA_MB": ("export", "max_data_mb"),
        "COMMS_TRIGGER_DEPLOY": ("publish", "trigger_deploy"),
    }
    for env_name, path in mappings.items():
        value = os.environ.get(env_name)
        if value is None:
            continue
        target = data
        for part in path[:-1]:
            target = target.setdefault(part, {})
        if path[-1] == "max_data_mb":
            target[path[-1]] = int(value)
        elif path[-1] == "trigger_deploy":
            target[path[-1]] = value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            target[path[-1]] = value


def apply_overrides(config: AppConfig, **overrides: object) -> AppConfig:
    data = config.model_dump()
    for key, value in overrides.items():
        if value is None:
            continue
        parts = key.split("__")
        target = data
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return AppConfig.model_validate(data)
