"""remove unused knowledge base columns

Revision ID: 6ab4cce73f3c
Revises: 287c8c97ea68
Create Date: 2026-06-03 14:54:52.526570

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ab4cce73f3c'
down_revision: Union[str, None] = '287c8c97ea68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
