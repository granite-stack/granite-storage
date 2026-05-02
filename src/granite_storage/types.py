from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

from granite_storage.models import StoredObjectRef

StorageJSONType = JSON().with_variant(JSONB(), "postgresql")


class StoredObjectRefType(TypeDecorator[StoredObjectRef]):
    impl = StorageJSONType
    cache_ok = True

    def process_bind_param(
        self, value: StoredObjectRef | dict[str, Any] | None, dialect: Any
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, StoredObjectRef):
            return value.to_dict()
        return value

    def process_result_value(
        self, value: dict[str, Any] | None, dialect: Any
    ) -> StoredObjectRef | None:
        if value is None:
            return None
        return StoredObjectRef.from_dict(value)
