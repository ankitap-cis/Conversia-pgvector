"""make the status column nullable False

Revision ID: 5dc06fd213dd
Revises: 6ab4cce73f3c
Create Date: 2026-06-03 15:01:29.866862

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dc06fd213dd'
down_revision: Union[str, None] = '6ab4cce73f3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
