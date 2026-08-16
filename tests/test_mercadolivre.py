# -*- coding: utf-8 -*-
"""
Testes automatizados para a integração do Mercado Livre (ComentsIA - Analytics ML & Saúde da Conta).
Testa:
- Diagnóstico consolidado de Saúde da Conta (Score 0 a 100) e 4 Pilares de Desempenho
- Perguntas Pré-Venda e cálculo de tempo médio de resposta
- Agregação de avaliações globais da loja e distribuição de estrelas
- Parecer Estratégico da IA (GPT-4o / Gemini) para a conta do vendedor
- Sugestão de respostas inteligentes para perguntas pré-venda
- Geração e emissão de Relatório Executivo em PDF
- Conexão e sincronização pública de conta do vendedor
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import text
from main import app as flask_app
from models import db, User, UserSettings
from models_mercadolivre import MercadoLivreAccount, MercadoLivreItem, MercadoLivreAlert
from mercadolivre_auto import (
    extract_item_id,
    fetch_seller_reputation_data,
    resolve_seller_from_input,
    fetch_account_questions,
    fetch_account_store_ratings_and_items,
    generate_account_health_ai_report,
    sugerir_resposta_pergunta_ia,
    gerar_pdf_relatorio_mercadolivre,
    analyze_account_health_and_generate_alerts
)

@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    return flask_app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture(autouse=True)
def ml_setup(app):
    with app.app_context():
        db.session.rollback()
        # Migração das colunas se necessário
        cols = [
            "total_questions INTEGER DEFAULT 0",
            "unanswered_questions INTEGER DEFAULT 0",
            "avg_response_time_minutes FLOAT DEFAULT 0.0",
            "questions_response_rate FLOAT DEFAULT 1.0",
            "recent_questions_json TEXT",
            "total_active_items INTEGER DEFAULT 0",
            "store_rating_average FLOAT DEFAULT 0.0",
            "total_store_reviews INTEGER DEFAULT 0",
            "rating_breakdown_json TEXT",
            "quality_scores_json TEXT",
            "health_score INTEGER DEFAULT 100",
            "ai_health_report_json TEXT",
            "ai_report_generated_at TIMESTAMP WITH TIME ZONE"
        ]
        for col in cols:
            try:
                db.session.execute(text(f"ALTER TABLE mercadolivre_accounts ADD COLUMN IF NOT EXISTS {col}"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        user = User.query.filter_by(id="test_ml_user").first()
        if not user:
            user = User(id="test_ml_user", email="ml_user@example.com")
            db.session.add(user)

        settings = UserSettings.query.filter_by(user_id="test_ml_user").first()
        if not settings:
            settings = UserSettings(user_id="test_ml_user", plano="pro")
            db.session.add(settings)

        accounts = MercadoLivreAccount.query.filter_by(user_id="test_ml_user").all()
        for acc in accounts:
            db.session.delete(acc)
        db.session.commit()
        yield
        db.session.rollback()


def test_extract_item_id():
    """Valida extração de MLB de múltiplos formatos de URLs e textos."""
    assert extract_item_id("MLB1234567890") == "MLB1234567890"
    assert extract_item_id("MLB-1234567890") == "MLB1234567890"
    assert extract_item_id("1234567890") == "MLB1234567890"
    assert extract_item_id("https://produto.mercadolivre.com.br/MLB-9876543210-tenis-corrida-_JM") == "MLB9876543210"
    assert extract_item_id("https://articulo.mercadolibre.com.ar/MLA-1122334455-remera-_JM") is None


def test_account_health_calculation_and_pillars():
    """Testa o cálculo do Score de Saúde (0 a 100) e os 4 Pilares de Desempenho."""
    account = MercadoLivreAccount(
        user_id="test_user",
        seller_id="999888777",
        nickname="LOJA_OFICIAL_EXEMPLO",
        level_id="5_green",
        power_seller_status="platinum",
        claims_rate=0.012,       # 1.2% -> Excelente (teto 3.0%)
        delayed_rate=0.045,      # 4.5% -> 95.5% no prazo (teto 15.0%)
        cancellations_rate=0.005,# 0.5% -> Seguro (teto 2.5%)
        avg_response_time_minutes=18.0,
        questions_response_rate=0.98,
        store_rating_average=4.9,
        total_store_reviews=450
    )

    health = account.calculate_account_health()
    assert health["overall_score"] >= 75
    assert health["badge"]["label"] in ["Excelente", "Boa"]
    
    pillars = health["pillars"]
    assert pillars["logistics"]["on_time_pct"] == 95.5
    assert pillars["logistics"]["delay_pct"] == 4.5
    assert pillars["quality"]["claims_pct"] == 1.2
    assert pillars["operation"]["cancel_pct"] == 0.5
    assert pillars["service"]["avg_response_minutes"] == 18.0
    assert pillars["service"]["response_rate_pct"] == 98.0


def test_account_questions_and_response_time():
    """Testa busca de perguntas pré-venda e cálculo de métricas de atendimento."""
    mock_questions_response = {
        "total": 3,
        "questions": [
            {
                "id": "q1",
                "text": "Tem na cor azul?",
                "status": "ANSWERED",
                "date_created": "2026-08-16T10:00:00.000Z",
                "answer": {
                    "text": "Olá! Sim, temos a pronta entrega.",
                    "date_created": "2026-08-16T10:15:00.000Z"  # 15 min de resposta
                }
            },
            {
                "id": "q2",
                "text": "Vem com nota fiscal?",
                "status": "ANSWERED",
                "date_created": "2026-08-16T11:00:00.000Z",
                "answer": {
                    "text": "Sim, produto 100% original com NF-e.",
                    "date_created": "2026-08-16T11:25:00.000Z"  # 25 min de resposta
                }
            },
            {
                "id": "q3",
                "text": "Qual o prazo de envio?",
                "status": "UNANSWERED",
                "date_created": "2026-08-16T12:00:00.000Z",
                "answer": None
            }
        ]
    }

    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = mock_questions_response
        mock_get.return_value = mock_res

        q_info = fetch_account_questions("999888777")
        assert q_info["total_questions"] == 3
        assert q_info["unanswered_questions"] == 1
        assert q_info["avg_response_time_minutes"] == 20.0  # (15 + 25) / 2 = 20 min
        assert q_info["questions_response_rate"] == 0.667
        assert len(q_info["recent_questions"]) == 3


def test_ai_health_report_and_answer_suggestion(app):
    """Testa geração do Parecer Estratégico por IA e sugestão de resposta para pré-venda."""
    with app.app_context():
        account = MercadoLivreAccount(
            user_id="test_ml_user",
            seller_id="999888777",
            nickname="LOJA_TESTE_ML",
            level_id="5_green",
            power_seller_status="gold",
            claims_rate=0.015,
            delayed_rate=0.06,
            cancellations_rate=0.008,
            avg_response_time_minutes=25.0,
            questions_response_rate=0.99
        )
        db.session.add(account)
        db.session.commit()

        report = generate_account_health_ai_report(account)
        assert report is not None
        assert "diagnostico_geral" in report
        assert "status_pilares" in report
        assert len(report["pontos_fortes"]) > 0
        assert len(report["plano_de_acao_prioritario"]) >= 1

    # Sugestão de resposta rápida para dúvida
    sugestao = sugerir_resposta_pergunta_ia("Tem estoque na cor preta?", "Tênis Esportivo")
    assert sugestao is not None
    assert len(sugestao) > 10


def test_gerar_pdf_relatorio_mercadolivre(app):
    """Testa a emissão do Relatório Executivo da Conta em PDF."""
    with app.app_context():
        account = MercadoLivreAccount(
            user_id="test_ml_user",
            seller_id="999888777",
            nickname="LOJA_OFICIAL_CALCADOS",
            level_id="5_green",
            power_seller_status="gold",
            claims_rate=0.015,
            delayed_rate=0.07,
            cancellations_rate=0.005,
            avg_response_time_minutes=20.0,
            questions_response_rate=0.98,
            store_rating_average=4.85,
            total_store_reviews=120
        )
        db.session.add(account)
        db.session.commit()

        pdf_buffer = gerar_pdf_relatorio_mercadolivre(account)
        assert pdf_buffer is not None
        pdf_bytes = pdf_buffer.getvalue()
        assert len(pdf_bytes) > 1000
        assert pdf_bytes.startswith(b"%PDF")


def test_conectar_publico_and_dashboard_flow(app, client):
    """Testa fluxo de conexão pública de conta e carregamento do Dashboard."""
    mock_seller_response = {
        "id": 123456789,
        "nickname": "LOJA_OFICIAL_CALCADOS",
        "site_id": "MLB",
        "permalink": "https://www.mercadolivre.com.br/perfil/LOJA_OFICIAL_CALCADOS",
        "seller_reputation": {
            "level_id": "5_green",
            "power_seller_status": "gold",
            "metrics": {
                "claims": {"rate": 0.015},
                "delayed_handling_time": {"rate": 0.08},
                "cancellations": {"rate": 0.005}
            },
            "transactions": {
                "completed": 4500,
                "canceled": 50,
                "total": 4550,
                "ratings": {"positive": 0.98, "negative": 0.01, "neutral": 0.01}
            }
        }
    }

    with patch("mercadolivre_auto.requests.get") as mock_get:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = dict(mock_seller_response)
        mock_get.return_value = mock_res

        with client.session_transaction() as sess:
            sess["user_id"] = "test_ml_user"
            sess["user_info"] = {"id": "test_ml_user", "email": "ml_user@example.com"}

        res_post = client.post("/mercadolivre/conectar_publico", data={"identifier": "123456789"}, follow_redirects=True)
        assert res_post.status_code == 200
        html = res_post.data.decode("utf-8")
        assert "LOJA_OFICIAL_CALCADOS" in html
        assert "Saúde & Performance da Loja" in html or "Saúde" in html

        with app.app_context():
            acc = MercadoLivreAccount.query.filter_by(user_id="test_ml_user", seller_id="123456789").first()
            assert acc is not None
            assert acc.level_id == "5_green"
            assert acc.power_seller_status == "gold"
            assert acc.health_score > 0
