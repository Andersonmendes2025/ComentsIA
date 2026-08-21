# -*- coding: utf-8 -*-
"""
Testes das metricas financeiras do Mercado Livre.

Regressao: o faturamento exibido era inventado. O codigo pegava o ticket
medio dos ultimos 50 pedidos e multiplicava pelo total de vendas de todos os
tempos; se a API nao respondesse, usava o preco medio dos anuncios (ou
R$119,90 fixo) e uma comissao "estimada" de 16%, tudo apresentado como
financeiro real.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mercadolivre_auto import calcular_metricas_financeiras, PERIODOS_FINANCEIROS


def _resposta(status=200, payload=None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload or {}
    m.text = ""
    return m


def test_faturamento_soma_valor_real_dos_pedidos():
    """Faturamento tem que ser a soma real, nunca ticket medio x total."""
    pedidos = {
        "paging": {"total": 3},
        "results": [
            {"status": "paid", "total_amount": 100.0},
            {"status": "delivered", "total_amount": 250.50},
            {"status": "cancelled", "total_amount": 999.0},  # nao entra
        ],
    }
    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_get.side_effect = [_resposta(200, pedidos), _resposta(200, {"total_visits": 700})]
        r = calcular_metricas_financeiras("123", "token", dias=30)

    assert r["dados_disponiveis"] is True
    assert r["faturamento"] == 350.50, "deve somar apenas os pagos, valor real"
    assert r["pedidos_pagos"] == 2
    assert r["pedidos_cancelados"] == 1
    assert r["ticket_medio"] == 175.25


def test_taxa_de_conversao():
    """Conversao = pedidos pagos / visitas."""
    pedidos = {
        "paging": {"total": 2},
        "results": [
            {"status": "paid", "total_amount": 50.0},
            {"status": "paid", "total_amount": 50.0},
        ],
    }
    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_get.side_effect = [_resposta(200, pedidos), _resposta(200, {"total_visits": 200})]
        r = calcular_metricas_financeiras("123", "token", dias=30)

    assert r["visitas"] == 200
    assert r["taxa_conversao"] == 1.0  # 2/200 = 1%


def test_sem_visitas_nao_divide_por_zero():
    pedidos = {"paging": {"total": 1}, "results": [{"status": "paid", "total_amount": 10.0}]}
    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_get.side_effect = [_resposta(200, pedidos), _resposta(200, {"total_visits": 0})]
        r = calcular_metricas_financeiras("123", "token", dias=30)
    assert r["taxa_conversao"] == 0.0


def test_api_falhando_nao_inventa_numero():
    """Sem dado da API, retorna vazio e sinaliza — nao estima faturamento."""
    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_get.return_value = _resposta(401, {})
        r = calcular_metricas_financeiras("123", "token", dias=30)

    assert r["dados_disponiveis"] is False
    assert r["faturamento"] == 0.0
    assert r["ticket_medio"] == 0.0
    assert r["erro"] == "HTTP 401"


def test_periodo_vai_na_consulta():
    """O filtro de periodo precisa chegar na URL da API."""
    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_get.side_effect = [
            _resposta(200, {"paging": {"total": 0}, "results": []}),
            _resposta(200, {"total_visits": 0}),
        ]
        calcular_metricas_financeiras("123", "token", dias=7)
        url = mock_get.call_args_list[0].args[0]

    assert "order.date_created.from=" in url
    assert "order.date_created.to=" in url


def test_periodos_disponiveis():
    assert set(PERIODOS_FINANCEIROS) == {7, 30, 90, 180}


def test_bloqueio_do_policyagent_e_identificado():
    """
    403 do PolicyAgent significa que o Mercado Livre bloqueia o app naquele
    endpoint — situacao diferente de token invalido, e com acao diferente
    para resolver. A tela precisa saber distinguir para orientar direito.
    """
    corpo = {
        "message": "At least one policy returned UNAUTHORIZED.",
        "blocked_by": "PolicyAgent",
        "code": "PA_UNAUTHORIZED_RESULT_FROM_POLICIES",
        "status": 403,
    }
    resp = MagicMock()
    resp.status_code = 403
    resp.json.return_value = corpo
    resp.text = str(corpo)

    with patch("mercadolivre_auto.requests.get", return_value=resp):
        r = calcular_metricas_financeiras("123", "token", dias=30)

    assert r["dados_disponiveis"] is False
    assert r["erro"] == "sem_permissao_ml"
    assert r["faturamento"] == 0.0


@pytest.fixture
def client_ml():
    """Sessao logada com conta ML e add-on ativo, para renderizar o painel."""
    from main import app as flask_app
    from models import db, User, UserSettings
    from models_mercadolivre import MercadoLivreAccount

    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    uid = "test_ml_painel"

    with flask_app.app_context():
        if not User.query.filter_by(id=uid).first():
            db.session.add(User(id=uid, email="painel@example.com"))
        s = UserSettings.query.filter_by(user_id=uid).first()
        if not s:
            s = UserSettings(user_id=uid, plano="pro")
            db.session.add(s)
        s.has_addon_mercadolivre = True
        s.addon_mercadolivre_until = None
        MercadoLivreAccount.query.filter_by(user_id=uid).delete()
        db.session.add(MercadoLivreAccount(
            user_id=uid, seller_id="999888", nickname="LOJA_TESTE",
        ))
        db.session.commit()

    c = flask_app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = uid
        sess["user_info"] = {"id": uid, "email": "painel@example.com"}
    return c


BLOQUEADO = {"dias": 30, "dados_disponiveis": False, "erro": "sem_permissao_ml",
             "pedidos_pagos": 0, "pedidos_cancelados": 0, "pedidos_total": 0,
             "faturamento": 0.0, "ticket_medio": 0.0, "visitas": 0, "taxa_conversao": 0.0}

LIBERADO = {"dias": 30, "dados_disponiveis": True, "erro": None,
            "pedidos_pagos": 10, "pedidos_cancelados": 1, "pedidos_total": 11,
            "faturamento": 1500.0, "ticket_medio": 150.0, "visitas": 3000, "taxa_conversao": 0.33}


def test_painel_financeiro_some_quando_ml_bloqueia(client_ml):
    """Sem dado liberado, o bloco financeiro nao deve aparecer na tela."""
    with patch("mercadolivre_auto.calcular_metricas_financeiras", return_value=BLOQUEADO),          patch("mercadolivre_auto.get_fresh_ml_token", return_value="tok"):
        html = client_ml.get("/mercadolivre/").data.decode("utf-8")

    assert "Visão Financeira" not in html
    assert "Taxa de Conversão" not in html


def test_painel_financeiro_aparece_quando_ha_dados(client_ml):
    with patch("mercadolivre_auto.calcular_metricas_financeiras", return_value=LIBERADO),          patch("mercadolivre_auto.get_fresh_ml_token", return_value="tok"):
        html = client_ml.get("/mercadolivre/").data.decode("utf-8")

    assert "Visão Financeira" in html
    assert "Taxa de Conversão" in html


def test_avaliacoes_da_loja_somem_sem_anuncios(client_ml):
    """Avaliacoes de produto dependem de /items, hoje bloqueado."""
    with patch("mercadolivre_auto.calcular_metricas_financeiras", return_value=BLOQUEADO),          patch("mercadolivre_auto.get_fresh_ml_token", return_value="tok"):
        html = client_ml.get("/mercadolivre/").data.decode("utf-8")

    assert "Avaliações da Loja" not in html
