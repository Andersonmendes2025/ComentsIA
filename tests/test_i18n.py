# -*- coding: utf-8 -*-
"""
Testes unitários para o motor de Internacionalização (i18n) e detecção por navegador.
"""

import pytest
from flask import session
from services.i18n import (
    get_current_locale,
    t,
    load_translations,
    SUPPORTED_LANGUAGES,
    _normalize_lang_code
)
from main import app as flask_app


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_normalize_lang_code():
    assert _normalize_lang_code("pt-BR") == "pt_BR"
    assert _normalize_lang_code("pt_br") == "pt_BR"
    assert _normalize_lang_code("pt-PT") == "pt_PT"
    assert _normalize_lang_code("pt_pt") == "pt_PT"
    assert _normalize_lang_code("en-US") == "en"
    assert _normalize_lang_code("en-GB") == "en"
    assert _normalize_lang_code("es-ES") == "es"
    assert _normalize_lang_code("es-419") == "es"
    assert _normalize_lang_code("de-DE") is None


def test_load_all_supported_translation_files():
    for code in SUPPORTED_LANGUAGES:
        translations = load_translations(code)
        assert translations is not None
        assert "navbar" in translations
        assert "footer" in translations
        assert "integrations" in translations
        assert "help" in translations


def test_translations_content(app):
    with app.test_request_context("/?lang=pt_BR"):
        assert t("navbar.reviews") == "Avaliações"
        assert t("integrations.ifood.name") == "iFood Delivery"
        assert t("home.logged_header_title") == "Gerenciador de Avaliações Google"
        assert t("dashboard.total_reviews") == "Total de Avaliações"
        assert t("about_page.hero_title") == "Quem Somos"

    with app.test_request_context("/?lang=en"):
        assert t("navbar.reviews") == "Reviews"
        assert t("navbar.pricing") == "Pricing"
        assert t("home.logged_header_title") == "Google Reviews Manager"
        assert t("dashboard.total_reviews") == "Total Reviews"
        assert t("about_page.hero_title") == "About Us"

    with app.test_request_context("/?lang=es"):
        assert t("navbar.reviews") == "Reseñas"
        assert t("navbar.pricing") == "Planes"
        assert t("home.logged_header_title") == "Gestor de Reseñas de Google"
        assert t("dashboard.total_reviews") == "Total de Reseñas"
        assert t("about_page.hero_title") == "Quiénes Somos"

    with app.test_request_context("/?lang=pt_PT"):
        assert t("navbar.dashboard") == "Painel"
        assert t("navbar.logout") == "Terminar Sessão"
        assert t("home.logged_header_title") == "Gestor de Avaliações Google"
        assert t("dashboard.total_reviews") == "Total de Avaliações"
        assert t("about_page.hero_title") == "Quem Somos"


def test_browser_accept_language_detection(app):
    # Simula navegador em Inglês Americano
    with app.test_request_context("/", headers={"Accept-Language": "en-US,en;q=0.9"}):
        locale = get_current_locale()
        assert locale == "en"
        assert t("navbar.reviews") == "Reviews"

    # Simula navegador em Espanhol
    with app.test_request_context("/", headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}):
        locale = get_current_locale()
        assert locale == "es"
        assert t("navbar.reviews") == "Reseñas"

    # Simula navegador em Português de Portugal
    with app.test_request_context("/", headers={"Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"}):
        locale = get_current_locale()
        assert locale == "pt_PT"

    # Simula navegador em Português do Brasil
    with app.test_request_context("/", headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}):
        locale = get_current_locale()
        assert locale == "pt_BR"


def test_route_set_language(client):
    # Muda para Espanhol via rota
    res = client.get("/set-lang/es", follow_redirects=False)
    assert res.status_code == 302
    # Verifica se o cookie foi configurado
    assert "coments_lang=es" in res.headers.get("Set-Cookie", "")

    # Muda para Inglês via rota
    res_en = client.get("/set-lang/en", follow_redirects=False)
    assert res_en.status_code == 302
    assert "coments_lang=en" in res_en.headers.get("Set-Cookie", "")
