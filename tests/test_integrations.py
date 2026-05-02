"""Tests for granite_storage.integrations.sqlalchemy."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from granite_storage.integrations.sqlalchemy import iter_model_storage_refs
from granite_storage.models import StoredObjectRef
from granite_storage.types import StoredObjectRefType


class Base(DeclarativeBase):
    pass


class Doc(Base):
    __tablename__ = "doc"
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
    body_ref: Mapped[StoredObjectRef | None] = mapped_column(
        StoredObjectRefType(), nullable=True
    )


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _ref(location: str) -> StoredObjectRef:
    return StoredObjectRef(
        storage_key="docs", backend="local", location=location, size=0, checksum=""
    )


def test_iter_model_storage_refs_yields_stored_refs(db_session: Session) -> None:
    db_session.add(Doc(id="1", body_ref=_ref("a.txt")))
    db_session.add(Doc(id="2", body_ref=_ref("b.txt")))
    db_session.commit()

    results = list(iter_model_storage_refs(db_session, Doc, "body_ref"))
    locations = {r.location for r in results if r is not None}
    assert "a.txt" in locations
    assert "b.txt" in locations


def test_iter_model_storage_refs_empty_table(db_session: Session) -> None:
    # No rows in the table at all → empty result
    results = list(iter_model_storage_refs(db_session, Doc, "body_ref"))
    assert results == []
