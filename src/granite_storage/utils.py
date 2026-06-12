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
    entity_id: uuid.UUID | str | None = None,
    field_name: str | None = None,
    original_filename: str | None = None,
) -> str:
    """Generate a storage key using a dedicated UUID subdirectory.

    Layout: ``{model_name}/{file_uuid}/{file_uuid}{ext}``

    The UUID subfolder isolates each stored object so that a CloudFront
    wildcard policy (``{model_name}/{file_uuid}/*``) can cover the file and
    any future derivatives (thumbnails, transcoded variants, etc.) with a
    single signed credential.

    If *entity_id* is provided it is used as the UUID segment; otherwise a
    fresh UUID is generated.
    """
    file_uuid = str(entity_id) if entity_id is not None else str(uuid.uuid4())
    suffix = safe_suffix(original_filename)
    return posixpath.join(model_name, file_uuid, f"{file_uuid}{suffix}")
