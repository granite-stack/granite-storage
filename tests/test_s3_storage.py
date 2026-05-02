import io
import uuid

import boto3
from moto import mock_aws
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from granite_storage import (
    StorageManager,
    StoragePolicy,
    StoredContentMixin,
    StoredObjectRef,
    StoredObjectRefType,
)
from granite_storage.backends.s3 import S3StorageBackend


class Base(DeclarativeBase):
    pass


class DummyModel(StoredContentMixin, Base):
    __tablename__ = "dummy_model"
    __stored_content_field_name__ = "_content_ref"
    __stored_content_storage_key__ = "dummy_content"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
    _content_ref: Mapped[StoredObjectRef | None] = mapped_column(
        StoredObjectRefType(), nullable=True
    )


@mock_aws
def test_s3_stream_roundtrip():
    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    manager = StorageManager(
        backends={
            "s3": S3StorageBackend(bucket="test-bucket", prefix="dev", client=s3)
        },
        policies={
            "dummy_content": StoragePolicy(
                storage_key="dummy_content",
                backend_key="s3",
                max_size=1024,
                key_prefix="tests",
            )
        },
    )
    DummyModel.configure_storage_manager(manager)
    obj = DummyModel(id=str(uuid.uuid4()))
    obj.set_content_from_stream(io.BytesIO(b"hola-s3"), filename="demo.txt")
    assert obj.get_content() == b"hola-s3"
