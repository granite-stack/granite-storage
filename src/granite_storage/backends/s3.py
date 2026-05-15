from __future__ import annotations

import posixpath
from collections.abc import Iterator
from typing import Any, BinaryIO, cast

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from granite_storage.contracts import StorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.models import StoredObjectRef
from granite_storage.utils import DEFAULT_STREAM_CHUNK_SIZE, sha256_bytes, utcnow_iso


class S3StorageBackend(StorageBackend):
    backend_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        client: BaseClient | None = None,
        extra_put_kwargs: dict[str, Any] | None = None,
    ):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client("s3")
        self.extra_put_kwargs = extra_put_kwargs or {}

    def _full_key(self, location: str) -> str:
        return posixpath.join(self.prefix, location) if self.prefix else location

    def _strip_prefix(self, key: str) -> str:
        if not self.prefix:
            return key
        prefix = f"{self.prefix}/"
        return key[len(prefix) :] if key.startswith(prefix) else key

    def put_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        put_kwargs = {
            "Bucket": self.bucket,
            "Key": self._full_key(key),
            "Body": content,
            **self.extra_put_kwargs,
        }
        if content_type:
            put_kwargs["ContentType"] = content_type
        try:
            self.client.put_object(**put_kwargs)
        except ClientError as exc:
            raise StorageError(f"S3 put_bytes failed for key '{key}': {exc}") from exc
        return StoredObjectRef(
            "",
            self.backend_name,
            key,
            len(content),
            sha256_bytes(content),
            content_type,
            original_filename,
            utcnow_iso(),
            {"bucket": self.bucket, **(extra or {})},
        )

    def put_stream(
        self,
        *,
        key: str,
        stream: BinaryIO,
        size: int | None = None,
        checksum: str | None = None,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        import hashlib
        import tempfile

        digest = hashlib.sha256()
        total = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as tmp:
            while True:
                chunk = stream.read(DEFAULT_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                tmp.write(chunk)
            tmp.seek(0)
            put_kwargs = {
                "Bucket": self.bucket,
                "Key": self._full_key(key),
                "Body": tmp,
                **self.extra_put_kwargs,
            }
            if content_type:
                put_kwargs["ContentType"] = content_type
            try:
                self.client.put_object(**put_kwargs)
            except ClientError as exc:
                raise StorageError(
                    f"S3 put_stream failed for key '{key}': {exc}"
                ) from exc
        return StoredObjectRef(
            "",
            self.backend_name,
            key,
            size if size is not None else total,
            checksum or f"sha256:{digest.hexdigest()}",
            content_type,
            original_filename,
            utcnow_iso(),
            {"bucket": self.bucket, **(extra or {})},
        )

    def get(self, ref: StoredObjectRef) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=self._full_key(ref.location)
            )
            return cast(bytes, response["Body"].read())
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise StorageError(f"S3 object not found: {ref.location}") from exc
            raise StorageError(f"S3 get failed for '{ref.location}': {exc}") from exc

    def open(self, ref: StoredObjectRef) -> BinaryIO:
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=self._full_key(ref.location)
            )
            return cast(BinaryIO, response["Body"])
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise StorageError(f"S3 object not found: {ref.location}") from exc
            raise StorageError(f"S3 open failed for '{ref.location}': {exc}") from exc

    def delete(self, ref: StoredObjectRef) -> None:
        try:
            self.client.delete_object(
                Bucket=self.bucket, Key=self._full_key(ref.location)
            )
        except ClientError as exc:
            raise StorageError(f"S3 delete failed for '{ref.location}': {exc}") from exc

    def exists(self, ref: StoredObjectRef) -> bool:
        try:
            self.client.head_object(
                Bucket=self.bucket, Key=self._full_key(ref.location)
            )
            return True
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return False
            raise StorageError(
                f"S3 exists check failed for '{ref.location}': {exc}"
            ) from exc

    def iter_locations(self, prefix: str | None = None) -> Iterator[str]:
        list_prefix = self.prefix
        if prefix:
            list_prefix = posixpath.join(list_prefix, prefix) if list_prefix else prefix
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self.bucket, Prefix=list_prefix or ""
            ):
                for item in page.get("Contents", []):
                    yield self._strip_prefix(item["Key"])
        except ClientError as exc:
            raise StorageError(
                f"S3 iter_locations failed for prefix '{list_prefix}': {exc}"
            ) from exc
