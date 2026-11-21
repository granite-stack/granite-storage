"""Reference/policy validation, client metadata and ref deserialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from granite_storage import StorageManager, StoragePolicy, StoredObjectRef
from granite_storage.backends.local import LocalStorageBackend
from granite_storage.exceptions import ContentTypeNotAllowedError, StorageError
from granite_storage.utils import safe_suffix, sanitize_filename


def _manager(tmp_path: Path, **policy_kwargs) -> StorageManager:
    return StorageManager(
        backends={"local": LocalStorageBackend(tmp_path)},
        policies={
            "docs": StoragePolicy(
                storage_key="docs",
                backend_key="local",
                key_prefix="docs",
                **policy_kwargs,
            )
        },
    )


def _put(manager: StorageManager, **kwargs) -> StoredObjectRef:
    return manager.put_bytes(
        storage_key="docs",
        model_name="m",
        entity_id="e",
        field_name="f",
        content=b"x",
        **kwargs,
    )


# GS-010 ---------------------------------------------------------------------


def test_ref_with_wrong_backend_is_rejected(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ref = _put(manager)
    ref.backend = "s3"
    for op in (manager.get, manager.open, manager.delete, manager.exists):
        with pytest.raises(StorageError, match="backend"):
            op(ref)


def test_ref_outside_policy_prefix_is_rejected(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    backend = manager.backends["local"]
    backend.put_bytes(key="secret/other.txt", content=b"nope")
    ref = StoredObjectRef("docs", "local", "secret/other.txt", 4, "")
    with pytest.raises(StorageError, match="outside"):
        manager.get(ref)
    with pytest.raises(StorageError, match="outside"):
        manager.delete(ref)
    # sibling prefix ("docs2") must not pass a naive startswith
    backend.put_bytes(key="docs2/x.txt", content=b"nope")
    with pytest.raises(StorageError, match="outside"):
        manager.get(StoredObjectRef("docs", "local", "docs2/x.txt", 4, ""))


def test_legacy_prefix_keeps_old_refs_readable(tmp_path: Path) -> None:
    old = _manager(tmp_path)  # prefix "docs"
    ref = _put(old)
    moved = StorageManager(
        backends=old.backends,
        policies={
            "docs": StoragePolicy(
                "docs", "local", key_prefix="docs_v2", legacy_key_prefixes=("docs",)
            )
        },
    )
    assert moved.get(ref) == b"x"
    new_ref = _put(moved)
    assert new_ref.location.startswith("docs_v2/")
    assert moved.get(new_ref) == b"x"


def test_policy_without_prefix_does_not_check_location(tmp_path: Path) -> None:
    manager = StorageManager(
        backends={"local": LocalStorageBackend(tmp_path)},
        policies={"bare": StoragePolicy("bare", "local")},
    )
    ref = manager.put_bytes(
        storage_key="bare", model_name="m", entity_id="e", field_name="f", content=b"x"
    )
    assert manager.get(ref) == b"x"


def test_invalid_policy_prefix_is_rejected() -> None:
    with pytest.raises(StorageError):
        StoragePolicy("a", "b", key_prefix="../x")
    with pytest.raises(StorageError):
        StoragePolicy("a", "b", legacy_key_prefixes=("/abs",))


def test_verify_checksum_on_read(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ref = _put(manager)
    assert manager.get(ref, verify_checksum=True) == b"x"
    (tmp_path / ref.location).write_bytes(b"tampered")
    assert manager.get(ref) == b"tampered"  # default: unchanged behaviour
    with pytest.raises(StorageError, match="checksum"):
        manager.get(ref, verify_checksum=True)


# GS-007 ---------------------------------------------------------------------


def test_allowed_content_types(tmp_path: Path) -> None:
    manager = _manager(tmp_path, allowed_content_types=("image/*", "application/pdf"))
    _put(manager, content_type="image/png")
    _put(manager, content_type="Application/PDF; charset=binary")
    for bad in ("text/html", "image/svg+xml-evil/../x", None):
        with pytest.raises(ContentTypeNotAllowedError):
            _put(manager, content_type=bad)


def test_malformed_content_type_is_rejected(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    for bad in ("text/html\r\nX-Evil: 1", "nonsense", "a/b; c=\x00"):
        with pytest.raises(ContentTypeNotAllowedError):
            _put(manager, content_type=bad)
    _put(manager, content_type="text/plain; charset=utf-8")


def test_filename_is_sanitized_in_ref(tmp_path: Path) -> None:
    ref = _put(_manager(tmp_path), original_filename="../../etc/pass\r\nwd.txt")
    assert ref.original_filename == "passwd.txt"
    assert ".." not in ref.location


def test_sanitize_filename_and_suffix() -> None:
    assert sanitize_filename("a\\b\\c.pdf") == "c.pdf"
    assert sanitize_filename("..") is None
    assert sanitize_filename("x" * 1000) == "x" * 255
    assert safe_suffix("a.pdf") == ".pdf"
    assert safe_suffix("a.p hp") == ""
    assert safe_suffix("a.ünï") == ""
    assert safe_suffix("a." + "b" * 11) == ""


# GS-011 ---------------------------------------------------------------------


def test_from_dict_ignores_unknown_keys() -> None:
    data = StoredObjectRef("k", "local", "a/b", 1, "sha256:x").to_dict()
    data["version"] = 2
    data["future_field"] = {"a": 1}
    ref = StoredObjectRef.from_dict(data)
    assert ref.location == "a/b"


def test_from_dict_still_requires_mandatory_fields() -> None:
    with pytest.raises(TypeError):
        StoredObjectRef.from_dict({"storage_key": "k"})
