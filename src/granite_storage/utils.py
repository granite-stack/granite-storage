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


def verify_declared_checksum(declared: str | None, sha256_hex: str) -> None:
    """Check a caller-declared checksum against the computed SHA-256.

    Only ``sha256:<hex>`` declarations are accepted.

    Raises:
        StorageError: if the declaration uses another algorithm or differs.
    """
    if declared is None:
        return
    if not declared.startswith("sha256:"):
        raise StorageError("Unsupported declared checksum: only sha256 is accepted.")
    if declared != f"sha256:{sha256_hex}":
        raise StorageError("Declared checksum does not match content.")


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


def _require_segment(value: str, label: str) -> str:
    if not value or "/" in value or "\\" in value:
        raise StorageError(f"Invalid {label}: must be a single path segment.")
    return value


def build_storage_object_key(
    *,
    model_name: str,
    entity_id: uuid.UUID | str | None = None,
    field_name: str | None = None,
    original_filename: str | None = None,
) -> str:
    """Generate a unique storage key for one write of one field of an entity.

    Layout: ``{model_name}/{entity_id}/{field_name}/{object_uuid}{ext}``
    (the ``{field_name}`` segment is omitted when *field_name* is ``None``).

    ``object_uuid`` is a fresh UUID on EVERY call, so:

    * replacing the content of a field never overwrites the previous object
      (the previous reference stays valid until the caller deletes it), and
    * two fields of the same entity never collide.

    Everything an entity owns lives under ``{model_name}/{entity_id}/``, so a
    single CloudFront wildcard policy can cover it.

    Keys written by earlier versions (``{model}/{id}/{id}{ext}``) are not
    changed: readers always use the ``location`` stored in the reference.
    """
    entity_segment = (
        _require_segment(str(entity_id), "entity_id")
        if entity_id is not None
        else str(uuid.uuid4())
    )
    parts = [model_name, entity_segment]
    if field_name:
        parts.append(_require_segment(field_name, "field_name"))
    parts.append(f"{uuid.uuid4()}{safe_suffix(original_filename)}")
    return validate_storage_key(posixpath.join(*parts))
