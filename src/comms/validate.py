from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from comms.exporters.schema import TABLE_SCHEMAS


class ValidationError(RuntimeError):
    pass


def validate_data_dir(path: str | Path, *, max_data_mb: int = 900) -> dict[str, Any]:
    root = Path(path)
    manifest_path = root / "manifest.json"
    schema_path = root / "schema.json"
    if not manifest_path.exists():
        raise ValidationError(f"Missing manifest: {manifest_path}")
    if not schema_path.exists():
        raise ValidationError(f"Missing schema: {schema_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    if manifest.get("data_version") != schema_doc.get("data_version"):
        raise ValidationError("manifest.json and schema.json data_version mismatch")

    total_bytes = 0
    table_report: dict[str, Any] = {}
    for table_name, table_schema in TABLE_SCHEMAS.items():
        table_info = manifest.get("tables", {}).get(table_name)
        if not isinstance(table_info, dict):
            raise ValidationError(f"Manifest missing table: {table_name}")
        files = table_info.get("files", [])
        row_total = 0
        table_bytes = 0
        for file_info in files:
            relative = file_info.get("path")
            if not relative:
                raise ValidationError(f"File entry missing path in {table_name}")
            file_path = root / relative
            if not file_path.exists():
                raise ValidationError(f"Missing data file: {file_path}")
            actual_bytes = file_path.stat().st_size
            if actual_bytes != file_info.get("bytes"):
                raise ValidationError(f"Size mismatch for {file_path}")
            if actual_bytes > 95 * 1024 * 1024:
                raise ValidationError(
                    f"{file_path} is {actual_bytes / 1024 / 1024:.1f} MB; "
                    "GitHub blocks files above 100 MiB. Increase the table partition count."
                )
            digest = _sha256(file_path)
            if digest != file_info.get("sha256"):
                raise ValidationError(f"Checksum mismatch for {file_path}")
            parquet = pq.ParquetFile(file_path)
            if parquet.schema_arrow.names != table_schema.names:
                raise ValidationError(f"Schema mismatch for {file_path}")
            rows = parquet.metadata.num_rows
            if rows != file_info.get("rows"):
                raise ValidationError(f"Row count mismatch for {file_path}")
            row_total += rows
            table_bytes += actual_bytes
        if row_total != table_info.get("rows"):
            raise ValidationError(f"Table row total mismatch for {table_name}")
        total_bytes += table_bytes
        table_report[table_name] = {"rows": row_total, "bytes": table_bytes, "files": len(files)}

    state_report = _validate_state(root)
    if state_report:
        total_bytes += int(state_report["compressed_bytes"])

    if total_bytes > max_data_mb * 1024 * 1024:
        raise ValidationError(
            f"Data directory is {total_bytes / 1024 / 1024:.1f} MB, above {max_data_mb} MB"
        )
    report = {
        "path": str(root),
        "bytes": total_bytes,
        "mib": round(total_bytes / 1024 / 1024, 2),
        "tables": table_report,
        "generated_at": manifest.get("generated_at"),
        "build_id": manifest.get("build_id"),
    }
    if state_report:
        report["state"] = state_report
    return report


def _validate_state(root: Path) -> dict[str, Any] | None:
    state_dir = root / "state"
    manifest_path = state_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid state manifest: {exc}") from exc
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValidationError("State manifest has no chunks")
    compressed_bytes = 0
    for chunk in chunks:
        path = state_dir / str(chunk.get("path"))
        if not path.exists():
            raise ValidationError(f"Missing state chunk: {path}")
        size = path.stat().st_size
        if size != int(chunk.get("bytes", -1)):
            raise ValidationError(f"State chunk size mismatch: {path}")
        compressed_bytes += size
    if compressed_bytes != int(manifest.get("compressed_bytes", -1)):
        raise ValidationError("State compressed byte total mismatch")
    return {
        "chunks": len(chunks),
        "compressed_bytes": compressed_bytes,
        "uncompressed_bytes": manifest.get("uncompressed_bytes"),
        "counts": manifest.get("counts"),
        "created_at": manifest.get("created_at"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
