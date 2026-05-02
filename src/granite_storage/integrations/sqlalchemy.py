from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def iter_model_storage_refs(
    db: Session, model: Any, ref_attr_name: str
) -> Generator[Any]:
    ref_attr = getattr(model, ref_attr_name)
    stmt = select(ref_attr).where(ref_attr.is_not(None))
    yield from db.execute(stmt).scalars()
