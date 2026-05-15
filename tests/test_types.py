"""Tests for StoredObjectRefType SQLAlchemy type decorator."""

from __future__ import annotations

from unittest.mock import MagicMock

from granite_storage.models import StoredObjectRef
from granite_storage.types import StoredObjectRefType


def _make_ref() -> StoredObjectRef:
    return StoredObjectRef(
        storage_key="docs",
        backend="local",
        location="test/file.txt",
        size=10,
        checksum="sha256:abc",
        content_type="text/plain",
        original_filename="file.txt",
    )


def test_process_bind_param_none() -> None:
    t = StoredObjectRefType()
    assert t.process_bind_param(None, MagicMock()) is None


def test_process_bind_param_stored_object_ref() -> None:
    t = StoredObjectRefType()
    ref = _make_ref()
    result = t.process_bind_param(ref, MagicMock())
    assert isinstance(result, dict)
    assert result["location"] == "test/file.txt"
    assert result["backend"] == "local"


def test_process_bind_param_dict_passthrough() -> None:
    t = StoredObjectRefType()
    raw = {
        "storage_key": "x",
        "backend": "local",
        "location": "a.txt",
        "size": 1,
        "checksum": "",
    }
    result = t.process_bind_param(raw, MagicMock())
    assert result is raw


def test_process_result_value_none() -> None:
    t = StoredObjectRefType()
    assert t.process_result_value(None, MagicMock()) is None


def test_process_result_value_dict() -> None:
    t = StoredObjectRefType()
    data = {
        "storage_key": "docs",
        "backend": "local",
        "location": "test/file.txt",
        "size": 10,
        "checksum": "sha256:abc",
        "content_type": "text/plain",
        "original_filename": "file.txt",
        "created_at": None,
        "extra": None,
    }
    ref = t.process_result_value(data, MagicMock())
    assert isinstance(ref, StoredObjectRef)
    assert ref.location == "test/file.txt"
    assert ref.backend == "local"
