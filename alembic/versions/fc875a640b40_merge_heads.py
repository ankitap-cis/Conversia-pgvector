"""merge heads

Revision ID: fc875a640b40
Revises: b5fcbcf28b02, 5dc06fd213dd
Create Date: 2026-06-03 15:32:32.428424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc875a640b40'
down_revision: Union[str, None] = ('b5fcbcf28b02', '5dc06fd213dd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
