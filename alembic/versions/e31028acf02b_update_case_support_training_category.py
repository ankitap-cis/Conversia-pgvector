"""update case support training category

Revision ID: e31028acf02b
Revises: 2eb5216ab58b
Create Date: 2026-06-09 13:27:58.040101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e31028acf02b'
down_revision: Union[str, None] = '2eb5216ab58b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        UPDATE prompt_master
        SET category = 'CASE_SUPPORT_AND_TRAINING'
        WHERE category = 'CASE_SUPPORT_TRAINING';
    """)

    op.execute("""
        UPDATE prompt_user
        SET category = 'CASE_SUPPORT_AND_TRAINING'
        WHERE category = 'CASE_SUPPORT_TRAINING';
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        UPDATE prompt_master
        SET category = 'CASE_SUPPORT_TRAINING'
        WHERE category = 'CASE_SUPPORT_AND_TRAINING';
    """)

    op.execute("""
        UPDATE prompt_user
        SET category = 'CASE_SUPPORT_TRAINING'
        WHERE category = 'CASE_SUPPORT_AND_TRAINING';
    """)
