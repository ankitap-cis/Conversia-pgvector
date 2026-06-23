"""merge heads

Revision ID: 669297fcfc52
Revises: 50f1033d63b3, 651246f45397
Create Date: 2026-05-27 15:20:13.419462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '669297fcfc52'
down_revision: Union[str, None] = ('50f1033d63b3', '651246f45397')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
