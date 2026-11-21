from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import uuid
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from granite_storage.exceptions import StorageError

DEFAULT_STREAM_CHUNK_SIZE = 1024 * 1024


def validate_storage_key(key: str, *, is_prefix: bool = False) -> str:
    """Validate a storage key (or listing prefix) and return it unchanged.

    Rejects empty keys, NUL bytes, backslashes, absolute paths (POSIX or drive
    letters), and empty, ``.`` or ``..`` segments. A listing prefix may end
    with a single ``/``.

    Raises:
        StorageError: if the key is unsafe.
    """
    if not isinstance(key, str) or not key:
        raise StorageError("Invalid storage key: empty.")
    if "\x00" in key:
        raise StorageError("Invalid storage key: contains NUL byte.")
    if "\\" in key:
        raise StorageError("Invalid storage key: contains backslash.")
    if key.startswith("/") or PureWindowsPath(key).drive:
        raise StorageError("Invalid storage key: must be relative.")
    body = key[:-1] if is_prefix and key.endswith("/") else key
    if not body:
        raise StorageError("Invalid storage key: empty.")
    for segment in body.split("/"):
        if segment in ("", ".", ".."):
            raise StorageError(
                f"Invalid storage key: illegal path segment {segment!r}."
            )
    return key


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
    if "/" in file_uuid:
        raise StorageError("Invalid entity_id: must be a single path segment.")
    suffix = safe_suffix(original_filename)
    return validate_storage_key(
        posixpath.join(model_name, file_uuid, f"{file_uuid}{suffix}")
    )
