# -*- coding: utf-8 -*-
"""
Testes abrangentes de renderização de templates em todos os idiomas suportados (pt_BR, pt_PT, en, es).
Garante que nenhum template quebre ou contenha erros de sintaxe Jinja2 ou chaves i18n ausentes.
"""

import pytest
from main import app as flask_app, limiter
from models import db, User, UserSettings, Review
from services.i18n import SUPPORTED_LANGUAGES

@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['RATELIMIT_ENABLED'] = False
    limiter.enabled = False
    return flask_app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture(autouse=True)
def setup_db(app):
    with app.app_context():
        db.session.rollback()
        user = User.query.filter_by(id="test_i18n_user").first()
        if not user:
            from datetime import datetime
            user = User(id="test_i18n_user", email="i18n_user@example.com", terms_accepted_at=datetime.utcnow(), is_admin=True)
            db.session.add(user)
        else:
            from datetime import datetime
            user.terms_accepted_at = datetime.utcnow()
            user.is_admin = True
        
        from datetime import datetime, timedelta
        from utils.crypto import encrypt
        settings = UserSettings.query.filter_by(user_id="test_i18n_user").first()
        if not settings:
            settings = UserSettings(
                user_id="test_i18n_user",
                plano="pro",
                plano_ate=datetime.utcnow() + timedelta(days=365),
                business_name=encrypt("Empresa Teste"),
                contact_info=encrypt("contato@empresa.com"),
                terms_accepted=True
            )
            db.session.add(settings)
        else:
            settings.business_name = encrypt("Empresa Teste")
            settings.contact_info = encrypt("contato@empresa.com")
            settings.terms_accepted = True
            settings.plano = "pro"
            settings.plano_ate = datetime.utcnow() + timedelta(days=365)
            
        db.session.commit()
        yield
        db.session.rollback()

def test_render_all_public_routes_in_all_languages(client):
    """Testa todas as páginas públicas em pt_BR, pt_PT, en, es."""
    routes = [
        "/",
        "/planos",
        "/quem-somos",
        "/privacy-policy",
        "/terms",
    ]
    
    for lang_code in SUPPORTED_LANGUAGES:
        for route in routes:
            url = f"{route}?lang={lang_code}"
            res = client.get(url)
            assert res.status_code == 200, f"Erro ao renderizar {url}: status {res.status_code}"
            html = res.data.decode("utf-8")
            assert len(html) > 500, f"Página {url} retornou conteúdo vazio ou truncado"

def test_render_all_authenticated_routes_in_all_languages(app, client):
    """Testa todas as páginas logadas em pt_BR, pt_PT, en, es."""
    with client.session_transaction() as sess:
        sess["user_id"] = "test_i18n_user"
        sess["_user_id"] = "test_i18n_user"
        sess["credentials"] = {"token": "mock_token"}
        sess["terms_accepted"] = True
        sess["user_info"] = {
            "id": "test_i18n_user",
            "email": "i18n_user@example.com",
            "name": "Usuário Teste",
            "picture": "https://example.com/pic.png"
        }
        
    auth_routes = [
        "/",
        "/reviews",
        "/integracoes",
        "/planos",
        "/ajuda",
        "/mercadolivre/dashboard"
    ]
    
    for lang_code in SUPPORTED_LANGUAGES:
        for route in auth_routes:
            url = f"{route}?lang={lang_code}"
            res = client.get(url)
            assert res.status_code == 200, f"Erro ao renderizar rota logada {url}: status {res.status_code}"
            html = res.data.decode("utf-8")
            assert len(html) > 500, f"Página {url} retornou conteúdo vazio ou truncado"
