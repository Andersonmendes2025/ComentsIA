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
