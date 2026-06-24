"""add pgvector general chatbot store

Revision ID: 7c4a2e9d8f10
Revises: 412915beef01
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7c4a2e9d8f10"
down_revision: Union[str, None] = "412915beef01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "general_chatbot_vectors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("file_type", sa.String(length=32), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.execute(
        """
        ALTER TABLE general_chatbot_vectors
        ALTER COLUMN embedding TYPE vector(3072)
        USING embedding::vector(3072)
        """
    )

    op.create_index(
        "ix_general_chatbot_vectors_org_id",
        "general_chatbot_vectors",
        ["org_id"],
    )
    op.create_index(
        "ix_general_chatbot_vectors_source_path",
        "general_chatbot_vectors",
        ["source_path"],
    )
    op.create_index(
        "ix_general_chatbot_vectors_file_type",
        "general_chatbot_vectors",
        ["file_type"],
    )
    op.create_index(
        "ix_general_chatbot_vectors_org_source_path",
        "general_chatbot_vectors",
        ["org_id", "source_path"],
    )
    op.create_index(
        "ix_general_chatbot_vectors_org_source",
        "general_chatbot_vectors",
        ["org_id", "source"],
    )

    op.execute(
        """
        CREATE INDEX ix_general_chatbot_vectors_embedding_hnsw
        ON general_chatbot_vectors
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_general_chatbot_vectors_embedding_hnsw",
        table_name="general_chatbot_vectors",
    )
    op.drop_index(
        "ix_general_chatbot_vectors_org_source",
        table_name="general_chatbot_vectors",
    )
    op.drop_index(
        "ix_general_chatbot_vectors_org_source_path",
        table_name="general_chatbot_vectors",
    )
    op.drop_index(
        "ix_general_chatbot_vectors_file_type",
        table_name="general_chatbot_vectors",
    )
    op.drop_index(
        "ix_general_chatbot_vectors_source_path",
        table_name="general_chatbot_vectors",
    )
    op.drop_index(
        "ix_general_chatbot_vectors_org_id",
        table_name="general_chatbot_vectors",
    )
    op.drop_table("general_chatbot_vectors")
