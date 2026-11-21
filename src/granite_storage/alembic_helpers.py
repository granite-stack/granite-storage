from typing import Any

from sqlalchemy.types import TypeEngine

from granite_storage.types import StorageJSONType


def portable_storage_ref_type() -> TypeEngine[Any]:
    """Column type for refs in migrations (same definition as the ORM type)."""
    return StorageJSONType.copy()


EXAMPLE_POSTGRESQL_TEXT_TO_STORAGE_REF = """
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    op.alter_column(
        "section_item",
        "content_markdown",
        existing_type=sa.Text(),
        type_=sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        postgresql_using=(
            "CASE WHEN content_markdown IS NULL THEN NULL "
            "ELSE jsonb_build_object('legacy_inline_text', content_markdown) END"
        ),
        existing_nullable=True,
    )
"""
