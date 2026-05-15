"""Additional tests for S3StorageBackend covering uncovered paths."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from granite_storage.backends.s3 import S3StorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.models import StoredObjectRef


def _client_error(code: str, operation: str = "Operation") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "mock error"}}, operation)


def _make_ref(location: str, bucket: str = "test-bucket") -> StoredObjectRef:
    return StoredObjectRef(
        storage_key="",
        backend="s3",
        location=location,
        size=0,
        checksum="",
        extra={"bucket": bucket},
    )


@pytest.fixture
def s3_client():
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        yield client


def test_put_bytes_with_content_type(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = backend.put_bytes(
        key="file.txt",
        content=b"hello",
        content_type="text/plain",
        original_filename="file.txt",
        extra={"tag": "v1"},
    )
    assert ref.content_type == "text/plain"
    assert ref.original_filename == "file.txt"
    assert ref.size == 5


def test_put_bytes_without_content_type(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = backend.put_bytes(key="bare.bin", content=b"data")
    assert ref.content_type is None


def test_put_stream_with_content_type(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = backend.put_stream(
        key="stream.txt",
        stream=io.BytesIO(b"stream-data"),
        content_type="text/plain",
        original_filename="stream.txt",
    )
    assert ref.content_type == "text/plain"
    assert ref.size == 11


def test_put_stream_explicit_size_and_checksum(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = backend.put_stream(
        key="explicit.bin",
        stream=io.BytesIO(b"abc"),
        size=3,
        checksum="md5:xyz",
    )
    assert ref.size == 3
    assert ref.checksum == "md5:xyz"


def test_open_returns_bytes(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    backend.put_bytes(key="open_test.txt", content=b"open me")
    ref = _make_ref("open_test.txt")
    stream = backend.open(ref)
    assert stream.read() == b"open me"


def test_delete_removes_object(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    backend.put_bytes(key="del.txt", content=b"bye")
    ref = _make_ref("del.txt")
    assert backend.exists(ref)
    backend.delete(ref)
    assert not backend.exists(ref)


def test_exists_false_for_missing_key(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    assert not backend.exists(_make_ref("nope.txt"))


def test_iter_locations_no_prefix(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    backend.put_bytes(key="a.txt", content=b"1")
    backend.put_bytes(key="b.txt", content=b"2")
    locations = set(backend.iter_locations())
    assert "a.txt" in locations
    assert "b.txt" in locations


def test_iter_locations_with_prefix(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", prefix="dev", client=s3_client)
    backend.put_bytes(key="sub/file.txt", content=b"x")
    backend.put_bytes(key="other.txt", content=b"y")
    locations = list(backend.iter_locations(prefix="sub"))
    assert any("file.txt" in loc for loc in locations)


def test_iter_locations_strips_prefix(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", prefix="pfx", client=s3_client)
    backend.put_bytes(key="item.txt", content=b"z")
    locations = list(backend.iter_locations())
    assert "item.txt" in locations


def test_strip_prefix_no_match() -> None:
    backend = S3StorageBackend(bucket="test-bucket", prefix="pfx")
    # Key that does NOT start with the prefix — should return as-is
    result = backend._strip_prefix("other/key.txt")
    assert result == "other/key.txt"


def test_put_with_extra_put_kwargs(s3_client) -> None:
    backend = S3StorageBackend(
        bucket="test-bucket",
        client=s3_client,
        extra_put_kwargs={"StorageClass": "STANDARD"},
    )
    ref = backend.put_bytes(key="tagged.txt", content=b"ok")
    assert ref.size == 2


# ---------------------------------------------------------------------------
# Error handling — StorageError wrapping
# ---------------------------------------------------------------------------


def test_get_raises_storage_error_for_missing_key(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = _make_ref("nonexistent.txt")
    with pytest.raises(StorageError, match="not found"):
        backend.get(ref)


def test_open_raises_storage_error_for_missing_key(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = _make_ref("nonexistent.txt")
    with pytest.raises(StorageError, match="not found"):
        backend.open(ref)


def test_get_raises_storage_error_on_other_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = _make_ref("file.txt")
    with patch.object(
        s3_client, "get_object", side_effect=_client_error("AccessDenied")
    ):
        with pytest.raises(StorageError, match="S3 get failed"):
            backend.get(ref)


def test_open_raises_storage_error_on_other_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = _make_ref("file.txt")
    with patch.object(
        s3_client, "get_object", side_effect=_client_error("AccessDenied")
    ):
        with pytest.raises(StorageError, match="S3 open failed"):
            backend.open(ref)


def test_put_bytes_raises_storage_error_on_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    with patch.object(
        s3_client, "put_object", side_effect=_client_error("NoSuchBucket")
    ):
        with pytest.raises(StorageError, match="S3 put_bytes failed"):
            backend.put_bytes(key="file.txt", content=b"data")


def test_put_stream_raises_storage_error_on_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    with patch.object(
        s3_client, "put_object", side_effect=_client_error("NoSuchBucket")
    ):
        with pytest.raises(StorageError, match="S3 put_stream failed"):
            backend.put_stream(key="file.txt", stream=io.BytesIO(b"data"))


def test_delete_raises_storage_error_on_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = _make_ref("file.txt")
    with patch.object(
        s3_client, "delete_object", side_effect=_client_error("AccessDenied")
    ):
        with pytest.raises(StorageError, match="S3 delete failed"):
            backend.delete(ref)


def test_exists_returns_false_for_missing_key(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    assert backend.exists(_make_ref("ghost.txt")) is False


def test_exists_raises_storage_error_on_non_404_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    ref = _make_ref("file.txt")
    with patch.object(
        s3_client, "head_object", side_effect=_client_error("AccessDenied")
    ):
        with pytest.raises(StorageError, match="S3 exists check failed"):
            backend.exists(ref)


def test_iter_locations_raises_storage_error_on_client_error(s3_client) -> None:
    backend = S3StorageBackend(bucket="test-bucket", client=s3_client)
    mock_paginator = MagicMock()
    mock_paginator.paginate.side_effect = _client_error("AccessDenied")
    with patch.object(s3_client, "get_paginator", return_value=mock_paginator):
        with pytest.raises(StorageError, match="S3 iter_locations failed"):
            list(backend.iter_locations())
