"""merge field intelligence and icon migrations

Revision ID: 412915beef01
Revises: 522e2d5dbe71, e15cb41018ff
Create Date: 2026-06-22 16:25:14.919867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '412915beef01'
down_revision: Union[str, None] = ('522e2d5dbe71', 'e15cb41018ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
