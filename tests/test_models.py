"""Tests for StoredObjectRef."""

from __future__ import annotations

import pytest

from granite_storage.models import StoredObjectRef


def _make_ref(**kwargs) -> StoredObjectRef:
    defaults = dict(
        storage_key="policy",
        backend="local",
        location="activity/abc/abc.md",
        size=100,
        checksum="sha256:aaa",
    )
    defaults.update(kwargs)
    return StoredObjectRef(**defaults)


class TestToUri:
    def test_local_backend(self):
        ref = _make_ref(backend="local", location="activity/abc/abc.md")
        assert ref.to_uri() == "file:///activity/abc/abc.md"

    def test_local_strips_leading_slash(self):
        ref = _make_ref(backend="local", location="/srv/data/abc.md")
        assert ref.to_uri() == "file:///srv/data/abc.md"

    def test_s3_backend(self):
        ref = _make_ref(backend="s3", location="activity/abc/abc.md", extra={"bucket": "my-bucket"})
        assert ref.to_uri() == "s3://my-bucket/activity/abc/abc.md"

    def test_s3_missing_bucket_returns_none(self):
        ref = _make_ref(backend="s3", location="activity/abc/abc.md", extra={})
        assert ref.to_uri() is None

    def test_s3_no_extra_returns_none(self):
        ref = _make_ref(backend="s3", location="activity/abc/abc.md", extra=None)
        assert ref.to_uri() is None

    def test_unknown_backend_returns_none(self):
        ref = _make_ref(backend="gcs", location="bucket/file.md")
        assert ref.to_uri() is None
