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


def test_replace_content_does_not_overwrite_previous_object(manager):
    """GS-001: deleting the previous ref must not delete the new content."""
    DummyModel.configure_storage_manager(manager)
    obj = DummyModel(id=str(uuid.uuid4()))
    obj.set_content(b"uno", filename="a.txt")
    result = obj.replace_content(b"dos", filename="b.txt")
    assert result.previous_ref is not None
    assert result.previous_ref.location != result.new_ref.location
    assert manager.get(result.previous_ref) == b"uno"
    manager.delete(result.previous_ref)
    assert manager.get(result.new_ref) == b"dos"


def test_two_fields_of_same_entity_do_not_collide(manager):
    """GS-001: field_name takes part in the key."""
    a = manager.put_bytes(
        storage_key="dummy_content",
        model_name="m",
        entity_id="e1",
        field_name="f",
        content=b"aaa",
        original_filename="x.txt",
    )
    b = manager.put_bytes(
        storage_key="dummy_content",
        model_name="m",
        entity_id="e1",
        field_name="g",
        content=b"bbb",
        original_filename="x.txt",
    )
    assert a.location != b.location
    assert manager.get(a) == b"aaa"
    assert manager.get(b) == b"bbb"


def test_entity_id_and_field_name_must_be_single_segments(manager):
    from granite_storage.exceptions import StorageError

    for kwargs in (
        {"entity_id": "a/b", "field_name": "f"},
        {"entity_id": "e", "field_name": "f/../g"},
    ):
        with pytest.raises(StorageError):
            manager.put_bytes(
                storage_key="dummy_content", model_name="m", content=b"x", **kwargs
            )
