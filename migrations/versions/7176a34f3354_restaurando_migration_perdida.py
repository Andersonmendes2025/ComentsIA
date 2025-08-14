"""Restaurando migration perdida

Revision ID: 7176a34f3354
Revises: 5d22c8582c4b
Create Date: 2025-08-14 10:05:57.266822

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7176a34f3354'
down_revision = '5d22c8582c4b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'filial_vinculo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('parent_user_id', sa.String(), nullable=False),
        sa.Column('child_user_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), default='pendente'),
        sa.Column('data_convite', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_aceite', sa.DateTime(timezone=True), nullable=True),
    )



def downgrade():
    pass
