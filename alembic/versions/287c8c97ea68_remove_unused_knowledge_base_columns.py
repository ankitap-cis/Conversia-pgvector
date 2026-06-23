"""remove unused knowledge base columns

Revision ID: 287c8c97ea68
Revises: c866ec93bf2c
Create Date: 2026-06-03 14:49:44.116367

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '287c8c97ea68'
down_revision: Union[str, None] = 'c866ec93bf2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
