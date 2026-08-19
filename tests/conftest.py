# -*- coding: utf-8 -*-
"""
Isolamento de banco de dados para a suite de testes.

IMPORTANTE: sem isso, `pytest` roda contra o Postgres de PRODUCAO (o
DATABASE_URL configurado no .env), porque os testes fazem `from main import
app` diretamente. Isso ja causou incidentes reais (ex.: test_admin.py dispara
um broadcast de verdade para todos os clientes toda vez que roda localmente).

Este conftest.py e carregado pelo pytest ANTES de qualquer teste importar
main.py, entao definimos aqui um DATABASE_URL isolado (SQLite em arquivo
temporario) se ninguem tiver setado um explicitamente no ambiente. Como o
main.py usa `load_dotenv()` (que nunca sobrescreve uma env var ja definida),
o valor de producao do .env nunca chega a ser usado pelos testes.

Para rodar os testes de propósito contra outro banco (ex.: um Postgres de
homologação), basta exportar DATABASE_URL antes de chamar o pytest — este
conftest respeita qualquer valor já presente no ambiente.
"""
import os
import tempfile

_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "comentsia_pytest.sqlite3")

if "DATABASE_URL" not in os.environ:
    if os.path.exists(_TEST_DB_PATH):
        try:
            os.remove(_TEST_DB_PATH)
        except OSError:
            pass
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

os.environ.setdefault("FLASK_SECRET_KEY", "pytest-isolated-secret-key")
os.environ.setdefault("SENTRY_DSN", "")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_isolated_schema():
    """Garante que o banco isolado tem todas as tabelas antes de qualquer teste rodar."""
    from main import app as flask_app
    from models import db

    with flask_app.app_context():
        db.create_all()
    yield
