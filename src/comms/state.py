from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from comms.logging import get_logger
from comms.timeutil import iso_utc, now_ts

log = get_logger("state")

STATE_FORMAT = "sqlite-gzip-chunks"
STATE_SCHEMA_VERSION = "1"
MANIFEST_NAME = "manifest.json"
COUNT_TABLES = ("artists", "offerings", "works", "price_history")


class StateError(RuntimeError):
    pass


class StateNotFound(StateError):
    pass


def pack_state(
    db_path: str | Path,
    out_dir: str | Path,
    *,
    chunk_size_mb: int = 40,
) -> dict[str, Any]:
    """Compress and chunk the SQLite database into the data snapshot."""
    database = Path(db_path)
    target = Path(out_dir)
    if not database.exists():
        raise FileNotFoundError(f"SQLite database not found: {database}")
    _checkpoint(database)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="comms-state-", dir=str(target.parent)))
    try:
        compressed = temp_dir / "state.gz"
        with (
            database.open("rb") as source,
            gzip.open(compressed, "wb", compresslevel=6) as destination,
        ):
            shutil.copyfileobj(source, destination, length=1024 * 1024)

        compressed_sha = _sha256(compressed)
        compressed_bytes = compressed.stat().st_size
        chunk_size = max(1, chunk_size_mb) * 1024 * 1024
        chunks: list[dict[str, Any]] = []
        with compressed.open("rb") as source:
            index = 0
            while True:
                data = source.read(chunk_size)
                if not data:
                    break
                part = temp_dir / f"part-{index:05d}.bin"
                part.write_bytes(data)
                chunks.append(
                    {
                        "path": part.name,
                        "bytes": len(data),
                        "sha256": _sha256(part),
                    }
                )
                index += 1

        manifest = {
            "format": STATE_FORMAT,
            "schema_version": STATE_SCHEMA_VERSION,
            "created_at": iso_utc(),
            "created_ts": now_ts(),
            "database": database.name,
            "uncompressed_bytes": database.stat().st_size,
            "uncompressed_sha256": _sha256(database),
            "compressed_bytes": compressed_bytes,
            "compressed_sha256": compressed_sha,
            "chunks": chunks,
            "counts": _counts(database),
        }
        (temp_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        compressed.unlink(missing_ok=True)
        if target.exists():
            shutil.rmtree(target)
        temp_dir.rename(target)
        log.info(
            "Packed state %s into %s (%s chunk(s), %.1f MB compressed)",
            database,
            target,
            len(chunks),
            compressed_bytes / 1024 / 1024,
        )
        return manifest
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def unpack_state(state_dir: str | Path, output_db: str | Path) -> dict[str, Any]:
    directory = Path(state_dir)
    output = Path(output_db)
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        raise StateNotFound(f"State manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid state manifest: {exc}") from exc
    if manifest.get("format") != STATE_FORMAT:
        raise StateError(f"Unsupported state format: {manifest.get('format')}")

    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise StateError("State manifest has no chunks")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="comms-unpack-", dir=str(output.parent)))
    compressed = temp_dir / "state.gz"
    database = temp_dir / "state.sqlite3"
    try:
        with compressed.open("wb") as destination:
            for chunk in chunks:
                part_path = directory / str(chunk["path"])
                if not part_path.exists():
                    raise StateError(f"Missing state chunk: {part_path}")
                data = part_path.read_bytes()
                if len(data) != int(chunk.get("bytes", -1)):
                    raise StateError(f"State chunk size mismatch: {part_path}")
                if _sha256_bytes(data) != chunk.get("sha256"):
                    raise StateError(f"State chunk checksum mismatch: {part_path}")
                destination.write(data)

        if _sha256(compressed) != manifest.get("compressed_sha256"):
            raise StateError("Compressed state checksum mismatch")
        with gzip.open(compressed, "rb") as source, database.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        if database.stat().st_size != int(manifest.get("uncompressed_bytes", -1)):
            raise StateError("Uncompressed state size mismatch")
        if _sha256(database) != manifest.get("uncompressed_sha256"):
            raise StateError("Uncompressed state checksum mismatch")

        for suffix in ("-wal", "-shm"):
            stale = Path(str(output) + suffix)
            if stale.exists():
                stale.unlink()
        os.replace(database, output)
        log.info("Unpacked state snapshot into %s", output)
        return manifest
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def fetch_state_manifest(
    repo: str,
    branch: str = "data",
    *,
    data_base: str | None = None,
) -> dict[str, Any] | None:
    base = _state_base(repo, branch, data_base)
    try:
        raw = _fetch_bytes(base + MANIFEST_NAME)
    except StateNotFound:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid remote state manifest: {exc}") from exc


def download_state(
    repo: str,
    branch: str = "data",
    output_db: str | Path = "work/comms.sqlite3",
    *,
    data_base: str | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Download the full state snapshot from the data branch.

    Returns ``None`` when the branch has no state snapshot yet, allowing a
    fresh Colab session to start an empty archive.
    """
    base = _state_base(repo, branch, data_base)
    try:
        manifest_raw = _fetch_bytes(base + MANIFEST_NAME, token=token)
    except StateNotFound:
        log.info("No state snapshot found at %s; starting fresh", base)
        return None
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid remote state manifest: {exc}") from exc

    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise StateError("Remote state manifest has no chunks")

    temp_dir = Path(tempfile.mkdtemp(prefix="comms-download-"))
    try:
        for index, chunk in enumerate(chunks, start=1):
            path = str(chunk["path"])
            log.info("Downloading state chunk %s/%s: %s", index, len(chunks), path)
            data = _fetch_bytes(base + path, token=token)
            (temp_dir / path).write_bytes(data)
        (temp_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        unpacked = unpack_state(temp_dir, output_db)
        return unpacked
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _data_base(repo: str, branch: str, data_base: str | None) -> str:
    base = data_base or f"https://raw.githubusercontent.com/{repo.strip('/')}/{branch}/"
    return base if base.endswith("/") else base + "/"


def _state_base(repo: str, branch: str, data_base: str | None) -> str:
    return _data_base(repo, branch, data_base) + "state/"


def _fetch_bytes(url: str, *, token: str | None = None) -> bytes:
    headers = {
        "User-Agent": "comms.io-state/0.1",
        "Accept": "*/*",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise StateNotFound(f"State file not found: {url}") from exc
        raise StateError(f"State download failed (HTTP {exc.code}): {url}") from exc
    except urllib.error.URLError as exc:
        raise StateError(f"State download failed: {url}: {exc}") from exc


def _checkpoint(db_path: Path) -> None:
    connection = sqlite3.connect(db_path, timeout=30)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.commit()
    finally:
        connection.close()


def _counts(db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    connection = sqlite3.connect(db_path, timeout=30)
    try:
        for table in COUNT_TABLES:
            try:
                row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = int(row[0]) if row else 0
            except sqlite3.Error:
                counts[table] = 0
    finally:
        connection.close()
    return counts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
