"""adiciona coluna plano em user_settings

Revision ID: 2d0c7f683875
Revises: deeef990cf96
Create Date: 2025-08-02 15:55:06.347519

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d0c7f683875'
down_revision = 'deeef990cf96'
branch_labels = None
depends_on = None


def upgrade():
    # Comando para Postgres
    op.add_column('user_settings', sa.Column('plano', sa.String(length=32), nullable=True))

def downgrade():
    op.drop_column('user_settings', 'plano')