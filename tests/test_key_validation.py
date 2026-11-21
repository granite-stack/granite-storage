"""Security tests: storage key validation and path traversal."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from granite_storage.backends.local import LocalStorageBackend
from granite_storage.backends.s3 import S3StorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.models import StoredObjectRef
from granite_storage.utils import build_storage_object_key, validate_storage_key

BAD_KEYS = [
    "../../outside.txt",
    "a/../../outside.txt",
    "a/../b.txt",
    "/etc/passwd",
    "a\\b.txt",
    "a\x00b.txt",
    "",
    "a//b.txt",
    "./a.txt",
    "C:\\windows\\x",
    "..",
]


def _ref(location: str, backend: str = "local") -> StoredObjectRef:
    return StoredObjectRef(
        storage_key="", backend=backend, location=location, size=0, checksum=""
    )


@pytest.mark.parametrize("key", BAD_KEYS)
def test_validate_storage_key_rejects(key: str) -> None:
    with pytest.raises(StorageError):
        validate_storage_key(key)


def test_validate_storage_key_accepts_legitimate() -> None:
    for key in ("activities/Model/abc/abc.pdf", "a/b..c/d.txt", "x.tar.gz"):
        assert validate_storage_key(key) == key
    assert validate_storage_key("activities/", is_prefix=True) == "activities/"


# --- local backend ---------------------------------------------------------


@pytest.mark.parametrize("key", BAD_KEYS)
def test_local_rejects_bad_keys_in_all_operations(tmp_path: Path, key: str) -> None:
    root = tmp_path / "root"
    backend = LocalStorageBackend(root)
    with pytest.raises(StorageError):
        backend.put_bytes(key=key, content=b"x")
    with pytest.raises(StorageError):
        backend.put_stream(key=key, stream=io.BytesIO(b"x"))
    with pytest.raises(StorageError):
        backend.get(_ref(key))
    with pytest.raises(StorageError):
        backend.open(_ref(key))
    with pytest.raises(StorageError):
        backend.delete(_ref(key))
    with pytest.raises(StorageError):
        backend.exists(_ref(key))
    assert not (tmp_path / "outside.txt").exists()


def test_local_iter_locations_rejects_traversal_prefix(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path / "root")
    with pytest.raises(StorageError):
        list(backend.iter_locations("../"))


def test_local_symlink_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    backend = LocalStorageBackend(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "s.txt").write_text("secret")
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError):
        backend.get(_ref("link/s.txt"))
    with pytest.raises(StorageError):
        backend.put_bytes(key="link/new.txt", content=b"x")
    with pytest.raises(StorageError):
        backend.delete(_ref("link/s.txt"))
    assert (outside / "s.txt").read_text() == "secret"
    assert not (outside / "new.txt").exists()


def test_local_legitimate_nested_key_roundtrip(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    key = "activities/Activity/abc-123/abc-123.pdf"
    ref = backend.put_bytes(key=key, content=b"data")
    assert backend.get(ref) == b"data"
    assert backend.exists(ref)
    assert key in list(backend.iter_locations("activities/"))
    backend.delete(ref)
    assert not backend.exists(ref)


# --- S3 backend ------------------------------------------------------------


@pytest.mark.parametrize("key", BAD_KEYS)
def test_s3_rejects_bad_keys_without_calling_client(key: str) -> None:
    client = MagicMock()
    backend = S3StorageBackend(bucket="b", prefix="pre", client=client)
    with pytest.raises(StorageError):
        backend.put_bytes(key=key, content=b"x")
    with pytest.raises(StorageError):
        backend.put_stream(key=key, stream=io.BytesIO(b"x"))
    with pytest.raises(StorageError):
        backend.get(_ref(key, "s3"))
    with pytest.raises(StorageError):
        backend.open(_ref(key, "s3"))
    with pytest.raises(StorageError):
        backend.delete(_ref(key, "s3"))
    with pytest.raises(StorageError):
        backend.exists(_ref(key, "s3"))
    for method in ("put_object", "get_object", "delete_object", "head_object"):
        getattr(client, method).assert_not_called()


def test_s3_absolute_location_cannot_drop_prefix() -> None:
    client = MagicMock()
    backend = S3StorageBackend(bucket="b", prefix="pre", client=client)
    with pytest.raises(StorageError):
        backend.get(_ref("/abs/k", "s3"))
    client.get_object.assert_not_called()


def test_s3_iter_locations_rejects_bad_prefix() -> None:
    backend = S3StorageBackend(bucket="b", prefix="pre", client=MagicMock())
    with pytest.raises(StorageError):
        list(backend.iter_locations("../other"))


def test_s3_legitimate_key_keeps_prefix() -> None:
    client = MagicMock()
    backend = S3StorageBackend(bucket="b", prefix="pre", client=client)
    backend.put_bytes(key="activities/M/abc/abc.pdf", content=b"x")
    assert client.put_object.call_args.kwargs["Key"] == "pre/activities/M/abc/abc.pdf"
    no_prefix = S3StorageBackend(bucket="b", client=client)
    no_prefix.put_bytes(key="a/b.txt", content=b"x")
    assert client.put_object.call_args.kwargs["Key"] == "a/b.txt"


# --- key building ----------------------------------------------------------


def test_build_key_rejects_traversal_components() -> None:
    with pytest.raises(StorageError):
        build_storage_object_key(model_name="m", entity_id="../x")
    with pytest.raises(StorageError):
        build_storage_object_key(model_name="m", entity_id="a/b")
    with pytest.raises(StorageError):
        build_storage_object_key(model_name="../m", entity_id="abc")
    with pytest.raises(StorageError):
        build_storage_object_key(model_name="/m", entity_id="abc")


def test_build_key_legitimate() -> None:
    key = build_storage_object_key(
        model_name="activities/Activity",
        entity_id="0b1c2d3e-0000-4000-8000-000000000001",
        original_filename="doc.PDF",
    )
    assert key.startswith("activities/Activity/0b1c")
    assert key.endswith(".PDF")
