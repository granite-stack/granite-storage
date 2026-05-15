from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO, ClassVar

try:
    from fastapi import UploadFile
except Exception:  # pragma: no cover

    class UploadFile:  # type: ignore
        pass


from granite_storage.exceptions import StorageError
from granite_storage.manager import StorageManager
from granite_storage.models import StoredObjectRef
from granite_storage.utils import guess_content_type


@dataclass
class ReplaceContentResult:
    previous_ref: StoredObjectRef | None
    new_ref: StoredObjectRef


class StoredContentMixin:
    __stored_content_field_name__: ClassVar[str]
    __stored_content_storage_key__: ClassVar[str]
    __storage_manager__: ClassVar[StorageManager | None] = None
    __tablename__: ClassVar[str]

    def _require_storage_manager(self) -> StorageManager:
        manager: StorageManager | None = getattr(
            self.__class__, "__storage_manager__", None
        )
        if manager is None:
            raise StorageError(
                f"Storage manager not configured for {self.__class__.__name__}"
            )
        return manager

    def _get_existing_ref(self) -> StoredObjectRef | None:
        ref: StoredObjectRef | None = getattr(
            self, self.__stored_content_field_name__, None
        )
        return ref

    def _set_ref(self, ref: StoredObjectRef | None) -> None:
        setattr(self, self.__stored_content_field_name__, ref)

    def set_content(
        self,
        content: bytes | str,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        storage_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        if isinstance(content, str):
            payload = content.encode("utf-8")
            content_type = content_type or "text/plain; charset=utf-8"
        else:
            payload = content
            content_type = content_type or guess_content_type(filename)
        entity_id = getattr(self, "id", None)
        if entity_id is None:
            raise StorageError("Model instance must have an id before set_content().")
        ref = self._require_storage_manager().put_bytes(
            storage_key=storage_key or self.__stored_content_storage_key__,
            model_name=self.__tablename__,
            entity_id=entity_id,
            field_name=self.__stored_content_field_name__.lstrip("_"),
            content=payload,
            content_type=content_type,
            original_filename=filename,
            extra=extra,
        )
        self._set_ref(ref)
        return ref

    def set_content_from_stream(
        self,
        stream: BinaryIO,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        storage_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        entity_id = getattr(self, "id", None)
        if entity_id is None:
            raise StorageError(
                "Model instance must have an id before set_content_from_stream()."
            )
        ref = self._require_storage_manager().put_stream(
            storage_key=storage_key or self.__stored_content_storage_key__,
            model_name=self.__tablename__,
            entity_id=entity_id,
            field_name=self.__stored_content_field_name__.lstrip("_"),
            stream=stream,
            content_type=content_type or guess_content_type(filename),
            original_filename=filename,
            extra=extra,
        )
        self._set_ref(ref)
        return ref

    async def set_content_from_uploadfile(
        self,
        upload_file: UploadFile,
        *,
        storage_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        upload_file.file.seek(0)
        return self.set_content_from_stream(
            upload_file.file,
            filename=upload_file.filename,
            content_type=upload_file.content_type,
            storage_key=storage_key,
            extra=extra,
        )

    def replace_content(
        self,
        content: bytes | str,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        storage_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ReplaceContentResult:
        previous_ref = self._get_existing_ref()
        new_ref = self.set_content(
            content,
            filename=filename,
            content_type=content_type,
            storage_key=storage_key,
            extra=extra,
        )
        return ReplaceContentResult(previous_ref=previous_ref, new_ref=new_ref)

    def get_content(self) -> bytes | None:
        ref = self._get_existing_ref()
        return None if ref is None else self._require_storage_manager().get(ref)

    def open_content(self) -> BinaryIO | None:
        ref = self._get_existing_ref()
        return None if ref is None else self._require_storage_manager().open(ref)

    def get_content_text(self, encoding: str = "utf-8") -> str | None:
        content = self.get_content()
        return None if content is None else content.decode(encoding)

    def clear_content_reference(self) -> StoredObjectRef | None:
        previous_ref = self._get_existing_ref()
        self._set_ref(None)
        return previous_ref

    @classmethod
    def configure_storage_manager(cls, manager: StorageManager) -> None:
        cls.__storage_manager__ = manager
