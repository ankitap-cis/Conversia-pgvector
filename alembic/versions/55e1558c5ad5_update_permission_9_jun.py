"""update permission 9 jun

Revision ID: 55e1558c5ad5
Revises: e31028acf02b
Create Date: 2026-06-09 13:34:19.163120

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55e1558c5ad5'
down_revision: Union[str, None] = 'e31028acf02b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        INSERT INTO role_permissions (id, role_id, permission_id)
        VALUES
            ((SELECT COALESCE(MAX(id), 0) + 1 FROM role_permissions), 4, 24),
            ((SELECT COALESCE(MAX(id), 0) + 2 FROM role_permissions), 5, 24)
        ON CONFLICT (role_id, permission_id) DO NOTHING;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        DELETE FROM role_permissions
        WHERE permission_id = 24
          AND role_id IN (4, 5);
    """)
