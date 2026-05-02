from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine


def portable_storage_ref_type() -> TypeEngine[dict[str, object]]:
    return JSON().with_variant(JSONB(), "postgresql")


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
        postgresql_using="CASE WHEN content_markdown IS NULL THEN NULL ELSE jsonb_build_object('legacy_inline_text', content_markdown) END",
        existing_nullable=True,
    )
"""
