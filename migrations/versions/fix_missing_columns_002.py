"""corrige colunas faltantes em user_settings"""

import sqlalchemy as sa
from alembic import op

revision = "fix_missing_columns_002"
down_revision = "manual_add_cols_001"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Lista de colunas faltantes
    missing_columns = {
        "business_name": sa.Column("business_name", sa.LargeBinary(), nullable=True),
        "contact_info": sa.Column("contact_info", sa.LargeBinary(), nullable=True),
        "terms_accepted": sa.Column(
            "terms_accepted", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
    }

    for col_name, column in missing_columns.items():
        if col_name not in [
            col["name"] for col in inspector.get_columns("user_settings")
        ]:
            op.add_column("user_settings", column)


def downgrade():
    for col_name in ["business_name", "contact_info", "terms_accepted"]:
        try:
            op.drop_column("user_settings", col_name)
        except Exception:
            pass
