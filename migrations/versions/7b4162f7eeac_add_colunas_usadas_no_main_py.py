"""add colunas usadas no main.py"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "manual_add_cols_001"
down_revision = "92c1091975c7"
branch_labels = None
depends_on = None


def column_exists(inspector, table_name, column_name):
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    # ========== USER_SETTINGS ==========
    user_settings_cols = [
        ("business_name", sa.LargeBinary(), True),
        ("contact_info", sa.LargeBinary(), True),
        ("manager_name", sa.LargeBinary(), True),
        ("terms_accepted", sa.Boolean(), False, sa.text("0")),
        ("email_boas_vindas_enviado", sa.Boolean(), False, sa.text("0")),
        ("plano", sa.String(50), True),
        ("plano_ate", sa.DateTime(timezone=True), True),
        ("logo", sa.LargeBinary(), True),
    ]
    for name, coltype, nullable, *default in user_settings_cols:
        if not column_exists(inspector, "user_settings", name):
            col = sa.Column(
                name,
                coltype,
                nullable=nullable,
                server_default=default[0] if default else None,
            )
            op.add_column("user_settings", col)

    # ========== REVIEW ==========
    review_cols = [
        ("tags", sa.String(255), True),
        ("source", sa.String(50), True),
    ]
    for name, coltype, nullable in review_cols:
        if not column_exists(inspector, "review", name):
            with op.batch_alter_table("review") as batch_op:
                batch_op.add_column(sa.Column(name, coltype, nullable=nullable))

    # ========== TABELA resposta_especial_uso ==========
    if "resposta_especial_uso" not in inspector.get_table_names():
        op.create_table(
            "resposta_especial_uso",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("data_uso", sa.Date(), nullable=False),
            sa.Column(
                "quantidade_usos", sa.Integer(), server_default="0", nullable=False
            ),
        )
        op.create_index(
            "ix_resposta_especial_uso_user_data",
            "resposta_especial_uso",
            ["user_id", "data_uso"],
            unique=True,
        )

    # ========== TABELA consideracoes_uso ==========
    if "consideracoes_uso" not in inspector.get_table_names():
        op.create_table(
            "consideracoes_uso",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("data_uso", sa.Date(), nullable=False),
            sa.Column(
                "quantidade_usos", sa.Integer(), server_default="0", nullable=False
            ),
        )
        op.create_index(
            "ix_consideracoes_uso_user_data",
            "consideracoes_uso",
            ["user_id", "data_uso"],
            unique=True,
        )

    # ========== RELATORIO_HISTORICO ==========
    for col in ["arquivo_pdf", "data_criacao"]:
        if not column_exists(inspector, "relatorio_historico", col):
            with op.batch_alter_table("relatorio_historico") as batch_op:
                if col == "arquivo_pdf":
                    batch_op.add_column(
                        sa.Column("arquivo_pdf", sa.LargeBinary(), nullable=True)
                    )
                elif col == "data_criacao":
                    batch_op.add_column(
                        sa.Column(
                            "data_criacao",
                            sa.DateTime(timezone=True),
                            server_default=sa.text("CURRENT_TIMESTAMP"),
                            nullable=True,
                        )
                    )


def downgrade():
    with op.batch_alter_table("relatorio_historico") as batch_op:
        for col in ["data_criacao", "arquivo_pdf"]:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    for table, index in [
        ("consideracoes_uso", "ix_consideracoes_uso_user_data"),
        ("resposta_especial_uso", "ix_resposta_especial_uso_user_data"),
    ]:
        try:
            op.drop_index(index, table_name=table)
        except Exception:
            pass
        try:
            op.drop_table(table)
        except Exception:
            pass

    with op.batch_alter_table("review") as batch_op:
        for col in ["source", "tags"]:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    for col in [
        "logo",
        "plano_ate",
        "plano",
        "email_boas_vindas_enviado",
        "terms_accepted",
        "manager_name",
        "contact_info",
        "business_name",
    ]:
        try:
            op.drop_column("user_settings", col)
        except Exception:
            pass
