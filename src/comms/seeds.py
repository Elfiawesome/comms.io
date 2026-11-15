from __future__ import annotations

import csv
import json
import re
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from comms.config import TwitterConfig
from comms.ids import normalize_handle
from comms.logging import get_logger
from comms.models import Seed

log = get_logger("seeds")

SKEB_URL_RE = re.compile(r"https?://(?:www\.)?skeb\.jp/@([A-Za-z0-9_]+)", re.IGNORECASE)
CREPE_URL_RE = re.compile(
    r"https?://(?:www\.)?crepe\.cm/(?:[a-z]{2}/)?@([^/\s?#\"'<>]+)",
    re.IGNORECASE,
)
PLAIN_HANDLE_RE = re.compile(r"^@?([A-Za-z0-9_.-]{2,80})$")
SUPPORTED_SUFFIXES = {".json", ".jsonl", ".csv", ".md", ".txt", ".list"}


def extract_seeds_from_text(
    text: str,
    *,
    default_site: str | None = None,
    source: str = "text",
    priority: int = 0,
) -> list[Seed]:
    seeds: list[Seed] = []
    for match in SKEB_URL_RE.finditer(text):
        seeds.append(
            Seed(
                site="skeb",
                handle=match.group(1),
                url=match.group(0),
                source=source,
                priority=priority,
            )
        )
    for match in CREPE_URL_RE.finditer(text):
        seeds.append(
            Seed(
                site="crepe",
                handle=match.group(1),
                url=match.group(0),
                source=source,
                priority=priority,
            )
        )
    if default_site:
        for line in text.splitlines():
            line = line.strip().strip(",;")
            match = PLAIN_HANDLE_RE.match(line)
            if match:
                seeds.append(
                    Seed(site=default_site, handle=match.group(1), source=source, priority=priority)
                )
    return _dedupe(seeds)


def load_seed_file(
    path: str | Path, *, default_site: str | None = None, priority: int = 0
) -> list[Seed]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    source = f"file:{file_path.name}"
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return _seeds_from_json(data, source=source, priority=priority, default_site=default_site)
    if suffix == ".jsonl":
        seeds: list[Seed] = []
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                seeds.extend(
                    _seeds_from_json(
                        json.loads(line),
                        source=source,
                        priority=priority,
                        default_site=default_site,
                    )
                )
            except json.JSONDecodeError:
                continue
        return _dedupe(seeds)
    if suffix == ".csv":
        return _seeds_from_csv(
            file_path, source=source, priority=priority, default_site=default_site
        )
    return extract_seeds_from_text(
        file_path.read_text(encoding="utf-8"),
        default_site=default_site,
        source=source,
        priority=priority,
    )


def load_seed_dir(directory: str | Path, *, priority: int = 0) -> list[Seed]:
    root = Path(directory)
    if not root.exists():
        return []
    seeds: list[Seed] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            try:
                seeds.extend(load_seed_file(path, priority=priority))
            except Exception as exc:
                log.warning("Skipping seed file %s: %s", path, exc)
    return _dedupe(seeds)


def import_gallery_dl_metadata(
    directory: str | Path,
    *,
    source: str = "gallery-dl",
    priority: int = 20,
) -> list[Seed]:
    """Read gallery-dl JSON metadata and extract Skeb/Crepe profile links."""
    root = Path(directory)
    if not root.exists():
        return []
    seeds: list[Seed] = []
    files = sorted(root.rglob("*.json"))
    for index, path in enumerate(files, start=1):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        seeds.extend(_seeds_from_json(data, source=source, priority=priority, default_site=None))
        if index % 1000 == 0:
            log.info("Scanned %s/%s gallery-dl files (%s seeds)", index, len(files), len(seeds))
    return _dedupe(seeds)


def run_gallery_dl(config: TwitterConfig, *, workspace: Path) -> Path:
    """Run gallery-dl (optional) and return the metadata directory."""
    output_dir = workspace
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = Path(config.gallery_dl_config)
    if not config_path.exists():
        raise FileNotFoundError(f"gallery-dl config not found: {config_path}")
    command = ["gallery-dl", "-c", str(config_path.resolve())]
    cookies_path = Path(config.cookies_file)
    if cookies_path.exists():
        command.extend(["-C", str(cookies_path.resolve())])
    command.append(config.gallery_dl_url)
    log.info("Running gallery-dl: %s", " ".join(command))
    proc = subprocess.run(
        command,
        cwd=output_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout:
        log.info("gallery-dl stdout: %s", proc.stdout.strip()[-2000:])
    if proc.returncode != 0:
        log.warning("gallery-dl exited with %s: %s", proc.returncode, proc.stderr.strip()[-2000:])
    return output_dir


def _seeds_from_json(
    data: Any,
    *,
    source: str,
    priority: int,
    default_site: str | None,
) -> list[Seed]:
    texts: list[str] = []
    for value in _walk_strings(data):
        texts.append(value)
    # Common gallery-dl fields are included explicitly in case a future
    # gallery-dl version stores them as non-string objects.
    if isinstance(data, dict):
        author = data.get("author")
        if isinstance(author, dict):
            for key in ("description", "bio", "url", "name"):
                value = author.get(key)
                if isinstance(value, str):
                    texts.append(value)
        for key in ("content", "description", "full_text", "text"):
            value = data.get(key)
            if isinstance(value, str):
                texts.append(value)
    seeds: list[Seed] = []
    for text in texts:
        seeds.extend(
            extract_seeds_from_text(
                text,
                default_site=default_site,
                source=source,
                priority=priority,
            )
        )
    return _dedupe(seeds)


def _seeds_from_csv(
    path: Path,
    *,
    source: str,
    priority: int,
    default_site: str | None,
) -> list[Seed]:
    seeds: list[Seed] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return seeds
        for row in reader:
            for key, value in row.items():
                if not value:
                    continue
                key_lower = (key or "").lower()
                if key_lower in {"skeb_handle", "skeb"}:
                    seeds.append(
                        Seed(
                            site="skeb",
                            handle=normalize_handle(value),
                            source=source,
                            priority=priority,
                        )
                    )
                elif key_lower in {"crepe_handle", "crepe"}:
                    seeds.append(
                        Seed(
                            site="crepe",
                            handle=normalize_handle(value),
                            source=source,
                            priority=priority,
                        )
                    )
                elif (
                    "skeb" in key_lower
                    and "url" in key_lower
                    or "crepe" in key_lower
                    and "url" in key_lower
                    or key_lower in {"url", "profile_url"}
                ):
                    seeds.extend(extract_seeds_from_text(value, source=source, priority=priority))
                elif key_lower in {"handle", "username"} and default_site:
                    seeds.append(
                        Seed(
                            site=default_site,
                            handle=normalize_handle(value),
                            source=source,
                            priority=priority,
                        )
                    )
    return _dedupe(seeds)


def _walk_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _dedupe(seeds: Iterable[Seed]) -> list[Seed]:
    result: dict[tuple[str, str], Seed] = {}
    for seed in seeds:
        handle = normalize_handle(seed.handle)
        if not handle:
            continue
        key = (seed.site, handle.casefold())
        existing = result.get(key)
        if existing is None:
            seed.handle = handle
            result[key] = seed
        else:
            existing.priority = max(existing.priority, seed.priority)
            if not existing.url and seed.url:
                existing.url = seed.url
    return sorted(
        result.values(), key=lambda item: (-item.priority, item.site, item.handle.casefold())
    )
