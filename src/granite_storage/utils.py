from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import re
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath

from granite_storage.exceptions import ContentTypeNotAllowedError, StorageError

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


_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{1,10}")
_CONTENT_TYPE_RE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*(\s*;[^\x00-\x1f\x7f]*)?"
)
MAX_FILENAME_LENGTH = 255


def safe_suffix(filename: str | None) -> str:
    """Return the file extension, or ``""`` unless it is ``.`` + 1-10 alphanumerics."""
    if not filename:
        return ""
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.strip()
    return suffix if _SUFFIX_RE.fullmatch(suffix) else ""


def sanitize_filename(filename: str | None) -> str | None:
    """Reduce a client-supplied filename to a harmless display name.

    Keeps only the last path component, removes control characters and
    limits the length. Returns ``None`` if nothing is left.
    """
    if not filename:
        return None
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    name = name[:MAX_FILENAME_LENGTH]
    return name if name not in ("", ".", "..") else None


def normalize_content_type(content_type: str | None) -> str | None:
    """Validate the syntax of a content type and return it unchanged.

    Raises:
        ContentTypeNotAllowedError: if it is not ``type/subtype[; params]``
            (for example if it contains control characters).
    """
    if content_type is None:
        return None
    if not _CONTENT_TYPE_RE.fullmatch(content_type.strip().lower()):
        raise ContentTypeNotAllowedError("Invalid content type.")
    return content_type.strip()


def content_type_allowed(content_type: str | None, allowed: tuple[str, ...]) -> bool:
    """Match the media type (without parameters) against exact/``type/*`` rules."""
    if content_type is None:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    for rule in allowed:
        rule = rule.lower()
        if rule == media or (rule.endswith("/*") and media.startswith(rule[:-1])):
            return True
    return False


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
