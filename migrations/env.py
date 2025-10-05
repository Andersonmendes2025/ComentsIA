# migrations/env.py
from __future__ import annotations
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import os, sys

# --- garanta que a raiz do projeto está no PYTHONPATH ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 1) Importe seu app e o db
# Se você usa app "global" em main.py:
from main import app            # <- ajuste se usa create_app()
from models import db           # seu SQLAlchemy()

# Se você usa factory:
# from main import create_app
# app = create_app()

# Alembic config
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 2) Metadados do SQLAlchemy para autogenerate
target_metadata = db.metadata

def get_url() -> str:
    # 3) Leia a URL direto da config do Flask
    return str(app.config["SQLALCHEMY_DATABASE_URI"])

def run_migrations_offline():
    url = get_url()
    # compare_type=True para detectar mudanças de tipo/length
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    # 4) Garanta o app_context também no offline para macros/custom types
    with app.app_context():
        with context.begin_transaction():
            context.run_migrations()

def run_migrations_online():
    with app.app_context():
        cfg_section = config.get_section(config.config_ini_section) or {}
        cfg_section["sqlalchemy.url"] = get_url()

        connectable = engine_from_config(
            cfg_section, prefix="sqlalchemy.", poolclass=pool.NullPool
        )

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
