"""Extended tests for StoredContentMixin covering uncovered paths."""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock

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
from granite_storage.exceptions import StorageError


class Base(DeclarativeBase):
    pass


class Article(StoredContentMixin, Base):
    __tablename__: str = "article"
    __stored_content_field_name__: str = "_body_ref"
    __stored_content_storage_key__: str = "docs"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
    _body_ref: Mapped[StoredObjectRef | None] = mapped_column(
        StoredObjectRefType(), nullable=True
    )


@pytest.fixture
def manager(tmp_path: Path) -> StorageManager:
    m = StorageManager(
        backends={"local": LocalStorageBackend(tmp_path)},
        policies={
            "docs": StoragePolicy(
                storage_key="docs",
                backend_key="local",
                max_size=None,
            )
        },
    )
    Article.configure_storage_manager(m)
    return m


# ---------------------------------------------------------------------------
# _require_storage_manager
# ---------------------------------------------------------------------------

def test_require_storage_manager_raises_when_not_configured() -> None:
    class Orphan(StoredContentMixin):
        __tablename__ = "orphan"
        __stored_content_field_name__ = "_ref"
        __stored_content_storage_key__ = "x"
        __storage_manager__ = None

    obj = Orphan()
    with pytest.raises(StorageError, match="Storage manager not configured"):
        obj._require_storage_manager()


# ---------------------------------------------------------------------------
# set_content – string input
# ---------------------------------------------------------------------------

def test_set_content_string(manager) -> None:
    obj = Article(id=str(uuid.uuid4()))
    ref = obj.set_content("hello text")
    assert ref.content_type == "text/plain; charset=utf-8"
    assert obj.get_content_text() == "hello text"


# ---------------------------------------------------------------------------
# set_content – missing id
# ---------------------------------------------------------------------------

def test_set_content_without_id_raises(manager) -> None:
    obj = Article()
    obj.id = None  # type: ignore[assignment]
    with pytest.raises(StorageError, match="must have an id"):
        obj.set_content(b"data")


# ---------------------------------------------------------------------------
# set_content_from_stream – missing id
# ---------------------------------------------------------------------------

def test_set_content_from_stream_without_id_raises(manager) -> None:
    obj = Article()
    obj.id = None  # type: ignore[assignment]
    with pytest.raises(StorageError, match="must have an id"):
        obj.set_content_from_stream(io.BytesIO(b"data"))


# ---------------------------------------------------------------------------
# set_content_from_uploadfile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_content_from_uploadfile(manager) -> None:
    upload = MagicMock()
    upload.file = io.BytesIO(b"upload content")
    upload.filename = "doc.txt"
    upload.content_type = "text/plain"

    obj = Article(id=str(uuid.uuid4()))
    ref = await obj.set_content_from_uploadfile(upload)
    assert obj.get_content() == b"upload content"
    assert ref.original_filename == "doc.txt"


# ---------------------------------------------------------------------------
# open_content
# ---------------------------------------------------------------------------

def test_open_content_returns_none_when_empty(manager) -> None:
    obj = Article(id=str(uuid.uuid4()))
    assert obj.open_content() is None


def test_open_content_returns_stream(manager) -> None:
    obj = Article(id=str(uuid.uuid4()))
    obj.set_content(b"read me")
    stream = obj.open_content()
    assert stream is not None
    assert stream.read() == b"read me"


# ---------------------------------------------------------------------------
# get_content_text
# ---------------------------------------------------------------------------

def test_get_content_text_returns_none_when_empty(manager) -> None:
    obj = Article(id=str(uuid.uuid4()))
    assert obj.get_content_text() is None


# ---------------------------------------------------------------------------
# clear_content_reference
# ---------------------------------------------------------------------------

def test_clear_content_reference(manager) -> None:
    obj = Article(id=str(uuid.uuid4()))
    ref = obj.set_content(b"data")
    returned = obj.clear_content_reference()
    assert returned == ref
    assert obj._get_existing_ref() is None


def test_clear_content_reference_when_empty(manager) -> None:
    obj = Article(id=str(uuid.uuid4()))
    assert obj.clear_content_reference() is None
