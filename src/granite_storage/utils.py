from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import uuid
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_STREAM_CHUNK_SIZE = 1024 * 1024


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def guess_content_type(
    filename: str | None, fallback: str = "application/octet-stream"
) -> str:
    if not filename:
        return fallback
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


def safe_suffix(filename: str | None) -> str:
    if not filename:
        return ""
    suffix = Path(filename).suffix.strip()
    if not suffix:
        return ""
    return suffix if suffix.startswith(".") else f".{suffix}"


def build_storage_object_key(
    *,
    model_name: str,
    entity_id: uuid.UUID | str,
    field_name: str,
    original_filename: str | None = None,
) -> str:
    entity_id_str = str(entity_id)
    version = uuid.uuid4().hex[:8]
    suffix = safe_suffix(original_filename)
    return posixpath.join(model_name, f"{entity_id_str}-{version}{suffix}")
