"""creating organizations table

Revision ID: 7a4be0f4df4a
Revises: 068dffda2335
Create Date: 2025-04-29 15:39:36.627273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a4be0f4df4a'
down_revision: Union[str, None] = '068dffda2335'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Create the sequence first
    op.execute("CREATE SEQUENCE org_id_seq START WITH 1001 INCREMENT BY 1")

    # Then create the table using the sequence
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('org_id_seq')"), primary_key=True),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('master_prompt', sa.Text(), nullable=True),
        sa.Column('evaluation_prompt', sa.Text(), nullable=True),
        sa.Column('persona_prompt', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['user.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('admin_id')
    )

def downgrade():
    op.drop_table('organizations')
    op.execute("DROP SEQUENCE IF EXISTS org_id_seq")

