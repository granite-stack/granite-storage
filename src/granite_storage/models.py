from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StoredObjectRef:
    storage_key: str
    backend: str
    location: str
    size: int
    checksum: str
    content_type: str | None = None
    original_filename: str | None = None
    created_at: str | None = None
    extra: dict[str, Any] | None = None

    def to_uri(self) -> str | None:
        """Return a ``scheme://host/path`` URI for this object.

        - S3:    ``s3://<bucket>/<location>``  (requires ``extra["bucket"]``)
        - local: ``file:///<location>``
        - unknown backend: ``None``
        """
        if self.backend == "s3":
            bucket = (self.extra or {}).get("bucket")
            if not bucket:
                return None
            return f"s3://{bucket}/{self.location}"
        if self.backend == "local":
            return f"file:///{self.location.lstrip('/')}"
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredObjectRef:
        return cls(**data)
