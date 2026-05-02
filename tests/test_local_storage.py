import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from granite_storage import (
    StorageManager,
    StoragePolicy,
    StoredContentMixin,
    StoredObjectRef,
    StoredObjectRefType,
)
from granite_storage.backends.local import LocalStorageBackend
from granite_storage.exceptions import ContentTooLargeError


class Base(DeclarativeBase):
    pass


class DummyModel(StoredContentMixin, Base):
    __tablename__: str = "dummy_model"
    __stored_content_field_name__: str = "_content_ref"
    __stored_content_storage_key__: str = "dummy_content"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
    _content_ref: Mapped[StoredObjectRef | None] = mapped_column(
        StoredObjectRefType(), nullable=True
    )


@pytest.fixture
def manager(tmp_path: Path) -> StorageManager:
    return StorageManager(
        backends={"local": LocalStorageBackend(tmp_path)},
        policies={
            "dummy_content": StoragePolicy(
                storage_key="dummy_content",
                backend_key="local",
                max_size=10,
                key_prefix="tests",
            )
        },
    )


def test_set_and_get_content(manager):
    DummyModel.configure_storage_manager(manager)
    obj = DummyModel(id=str(uuid.uuid4()))
    obj.set_content(b"hola")
    assert obj.get_content() == b"hola"


def test_stream_size_validation(manager):
    DummyModel.configure_storage_manager(manager)
    obj = DummyModel(id=str(uuid.uuid4()))
    with pytest.raises(ContentTooLargeError):
        obj.set_content_from_stream(io.BytesIO(b"01234567890"))


def test_replace_content_returns_previous_ref(manager):
    DummyModel.configure_storage_manager(manager)
    obj = DummyModel(id=str(uuid.uuid4()))
    first = obj.set_content(b"uno")
    result = obj.replace_content(b"dos")
    assert result.previous_ref == first
    assert result.new_ref.location != first.location
    assert obj.get_content() == b"dos"
