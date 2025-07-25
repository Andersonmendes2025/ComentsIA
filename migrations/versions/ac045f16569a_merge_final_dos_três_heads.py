"""merge final dos três heads

Revision ID: ac045f16569a
Revises: 3250fe5b431c, 3ccbe3b1b60c, 750d9d162c0a
Create Date: 2025-07-25 19:51:37.647962

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ac045f16569a'
down_revision = ('3250fe5b431c', '3ccbe3b1b60c', '750d9d162c0a')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
