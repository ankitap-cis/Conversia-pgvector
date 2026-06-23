"""fixed default null values for personal use column

Revision ID: 52b25f260fa6
Revises: bf3522aad345
Create Date: 2026-05-07 19:20:41.291392
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52b25f260fa6'
down_revision: Union[str, None] = 'bf3522aad345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.alter_column(
        'debrief_reports',
        'ai_score',
        existing_type=sa.REAL(),
        type_=sa.Float(precision=2),
        existing_nullable=True
    )

    # -----------------------------
    # PERSONA
    # -----------------------------

    # Backfill NULLs
    op.execute("""
        UPDATE persona
        SET for_personal_use = false
        WHERE for_personal_use IS NULL
    """)

    # Add DB default + non-null
    op.alter_column(
        'persona',
        'for_personal_use',
        existing_type=sa.BOOLEAN(),
        nullable=False,
        server_default=sa.false()
    )

    # -----------------------------
    # SCENARIOS
    # -----------------------------

    # Backfill NULLs
    op.execute("""
        UPDATE scenarios
        SET for_personal_use = false
        WHERE for_personal_use IS NULL
    """)

    # Add DB default + non-null
    op.alter_column(
        'scenarios',
        'for_personal_use',
        existing_type=sa.BOOLEAN(),
        nullable=False,
        server_default=sa.false()
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.alter_column(
        'scenarios',
        'for_personal_use',
        existing_type=sa.BOOLEAN(),
        nullable=True,
        server_default=None
    )

    op.alter_column(
        'persona',
        'for_personal_use',
        existing_type=sa.BOOLEAN(),
        nullable=True,
        server_default=None
    )

    op.alter_column(
        'debrief_reports',
        'ai_score',
        existing_type=sa.Float(precision=2),
        type_=sa.REAL(),
        existing_nullable=True
    )