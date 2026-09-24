# -*- coding: utf-8 -*-
"""
Testes unitários e de integração para a funcionalidade do iFood e Add-on Stripe.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import pytz
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app as flask_app
from models import db, User, UserSettings, IFoodMerchant, Review
from ifood_auto import (
    usuario_tem_addon_ifood,
    parse_jwt_merchant_ids,
    generate_ifood_ai_reply,
    sync_merchant_reviews,
)


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ifood_setup(app):
    """Configura um usuário de teste e loja do iFood no banco."""
    with app.app_context():
        user = User.query.filter_by(id="test_ifood_user").first()
        if not user:
            user = User(id="test_ifood_user", email="ifood_tester@comentsia.com.br", nome="Tester iFood")
            db.session.add(user)

        settings = UserSettings.query.filter_by(user_id="test_ifood_user").first()
        if not settings:
            settings = UserSettings(
                user_id="test_ifood_user",
                has_addon_ifood=True,
                terms_accepted=True,
                business_name="Pizzaria Teste",
                contact_info="contato@pizzaria.com",
                plano="pro"
            )
            db.session.add(settings)
        else:
            settings.has_addon_ifood = True
            settings.terms_accepted = True
            settings.business_name = "Pizzaria Teste"
            settings.contact_info = "contato@pizzaria.com"

        from utils.crypto import encrypt as crypto_encrypt

        merchant = IFoodMerchant.query.filter_by(user_id="test_ifood_user", merchant_id="m-uuid-12345").first()
        if not merchant:
            merchant = IFoodMerchant(
                user_id="test_ifood_user",
                merchant_id="m-uuid-12345",
                name="Hamburgueria Teste iFood",
                auto_reply_enabled=True,
                tone="amigavel",
                access_token=crypto_encrypt("fake_token_jwt"),
                token_expires_at=datetime.now(pytz.utc) + timedelta(hours=6)
            )
            db.session.add(merchant)
        else:
            merchant.access_token = crypto_encrypt("fake_token_jwt")
            merchant.token_expires_at = datetime.now(pytz.utc) + timedelta(hours=6)

        db.session.commit()
        yield user, settings, merchant


def test_usuario_tem_addon_ifood(app, ifood_setup):
    with app.app_context():
        # Usuário com addon ativado
        assert usuario_tem_addon_ifood("test_ifood_user") is True

        # Usuário inexistente
        assert usuario_tem_addon_ifood("user_inexistente_999") is False


def test_plano_pro_business_nao_libera_ifood_sem_addon(app):
    """
    Regressão: o plano do Google (Free/Pro/Business) nunca deve liberar o
    iFood sozinho — é sempre um add-on pago à parte, independente do plano.
    """
    with app.app_context():
        for plano in ("free", "pro", "pro_anual", "business", "business_anual"):
            user_id = f"test_ifood_sem_addon_{plano}"
            settings = UserSettings.query.filter_by(user_id=user_id).first()
            if not settings:
                settings = UserSettings(user_id=user_id, plano=plano, has_addon_ifood=False)
                db.session.add(settings)
            else:
                settings.plano = plano
                settings.has_addon_ifood = False
            db.session.commit()

            assert usuario_tem_addon_ifood(user_id) is False, f"plano={plano} não deveria liberar iFood sem addon"


def test_parse_jwt_merchant_ids():
    # Cria um JWT simulado com merchant_scope
    import base64
    import json

    header = base64.b64encode(json.dumps({"alg": "RS512"}).encode()).decode()
    payload = base64.b64encode(json.dumps({
        "merchant_scope": [
            "6962d289-5f03-4131-9056-52a3342cf059:review",
            "6962d289-5f03-4131-9056-52a3342cf059:order",
            "11111111-2222-3333-4444-555555555555:review"
        ]
    }).encode()).decode()
    fake_jwt = f"{header}.{payload}.signature"

    merchant_ids = parse_jwt_merchant_ids(fake_jwt)
    assert "6962d289-5f03-4131-9056-52a3342cf059" in merchant_ids
    assert "11111111-2222-3333-4444-555555555555" in merchant_ids
    assert len(merchant_ids) == 2


def test_generate_ifood_ai_reply(app, ifood_setup):
    with app.app_context():
        user, settings, merchant = ifood_setup
        
        # Teste com avaliação 5 estrelas
        reply = generate_ifood_ai_reply(
            merchant=merchant,
            stars=5,
            review_text="Hambúrguer delicioso e chegou super rápido e quentinho!",
            reviewer_name="Lucas Pereira"
        )
        assert reply is not None
        assert len(reply) > 20
        assert "Lucas" in reply or "Olá" in reply


def test_sync_merchant_reviews_mock(app, ifood_setup):
    with app.app_context():
        user, settings, merchant = ifood_setup

        # Limpa review de teste anterior se existir
        Review.query.filter_by(external_id="rev-ifood-001", source="ifood").delete()
        db.session.commit()

        mock_api_response = {
            "page": 1,
            "size": 10,
            "reviews": [
                {
                    "id": "rev-ifood-001",
                    "score": 5,
                    "comment": "Melhor lanche da cidade!",
                    "customer": {"name": "Mariana Souza"},
                    "createdAt": "2026-08-15T19:00:00Z",
                    "answers": []
                }
            ]
        }

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            # Mock GET reviews
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_api_response

            # Mock POST reply
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"success": True}

            result = sync_merchant_reviews(merchant.id, auto_reply=True)
            assert result["success"] is True
            assert result["novas_avaliacoes"] >= 1

            # Verifica se o Review foi gravado no banco
            saved_rev = Review.query.filter_by(external_id="rev-ifood-001", source="ifood").first()
            assert saved_rev is not None
            assert saved_rev.reviewer_name == "Mariana Souza"
            assert saved_rev.rating == 5
            assert saved_rev.replied is True
            assert saved_rev.reply is not None


def test_rota_integracoes_logado(client, ifood_setup):
    with client.session_transaction() as sess:
        sess["user_info"] = {"id": "test_ifood_user", "email": "ifood_tester@comentsia.com.br", "name": "Tester iFood"}
        sess["credentials"] = {"token": "dummy"}

    response = client.get("/integracoes")
    assert response.status_code == 200
    assert b"iFood Delivery" in response.data
    assert b"Google Meu Neg" in response.data


def test_ver_loja_ifood_dashboard_nao_consulta_financeiro(client, ifood_setup):
    _, _, merchant = ifood_setup
    with client.session_transaction() as sess:
        sess["user_info"] = {"id": "test_ifood_user", "email": "ifood_tester@comentsia.com.br", "name": "Tester iFood"}
        sess["credentials"] = {"token": "dummy"}

    with patch("ifood_auto.requests.get", side_effect=AssertionError("Consulta iFood inesperada")):
        response = client.get(f"/ifood/loja/{merchant.id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Avaliações Recentes no iFood" in html
    assert "Distribuição de Avaliações" in html
    assert "Respondidas" in html
    assert "Faturamento" not in html
    assert "Ticket Médio" not in html
    assert "Dados financeiros indisponíveis" not in html


def test_metricas_ifood_usam_apenas_avaliacoes(app, ifood_setup):
    from ifood_auto import calcular_metricas_loja_ifood

    with app.app_context():
        _, _, merchant = ifood_setup
        with patch("ifood_auto.requests.get", side_effect=AssertionError("Consulta iFood inesperada")):
            metrics = calcular_metricas_loja_ifood(merchant)
        assert metrics["total_reviews"] == metrics["respondidas"] + metrics["pendentes"]
        assert set(metrics) == {
            "total_reviews", "respondidas", "pendentes", "avg_rating",
            "taxa_resposta", "dist_estrelas",
        }
        assert set(metrics["dist_estrelas"]) == {1, 2, 3, 4, 5}


def test_cron_ifood_sincroniza_avaliacoes_sem_consultar_financeiro(app, ifood_setup):
    from ifood_auto import run_ifood_daily_sync

    with app.app_context():
        _, _, merchant = ifood_setup
        with patch("ifood_auto.sync_merchant_reviews", return_value={"success": True}) as sync, \
             patch("ifood_auto.get_valid_merchant_token", side_effect=AssertionError("Token financeiro inesperado")), \
             patch("ifood_auto.requests.get", side_effect=AssertionError("Consulta iFood inesperada")):
            run_ifood_daily_sync(app)
        sync.assert_any_call(merchant.id, auto_reply=merchant.auto_reply_enabled)


def test_reviews_filter_ifood(client, ifood_setup):
    user, settings, merchant = ifood_setup
    with client.session_transaction() as sess:
        sess["user_id"] = "test_ifood_user"
        sess["_user_id"] = "test_ifood_user"
        sess["user_info"] = {"id": "test_ifood_user", "email": "ifood_tester@comentsia.com.br", "name": "Tester iFood"}
        sess["credentials"] = {"token": "dummy"}
        sess["terms_accepted"] = True

    response = client.get(f"/reviews?origem=ifood", follow_redirects=True)
    assert response.status_code == 200


def test_sync_diario_cobre_lojas_ativas_e_ignora_desconectadas(app, ifood_setup):
    """
    O job periodico varre as lojas com is_active=True. Uma loja desconectada
    continua no banco (para preservar historico), mas nao pode ser sincronizada.
    """
    user, settings, merchant = ifood_setup
    merchant_db_id = merchant.id

    with app.app_context():
        ativas = {m.id for m in IFoodMerchant.query.filter_by(is_active=True).all()}
        assert merchant_db_id in ativas

        m = IFoodMerchant.query.get(merchant_db_id)
        m.is_active = False
        db.session.commit()

        ativas = {m.id for m in IFoodMerchant.query.filter_by(is_active=True).all()}
        assert merchant_db_id not in ativas, "loja desconectada nao pode entrar no sync"

        m = IFoodMerchant.query.get(merchant_db_id)
        m.is_active = True
        db.session.commit()


def test_desconectar_preserva_registro_e_historico(client, ifood_setup):
    """
    Regressao: a rota de desconectar chamava db.session.delete(), o que apagava
    a loja. Como o vinculo das avaliacoes e as configuracoes ficam presos ao id
    interno, reconectar criava uma loja nova e o cliente perdia tudo.
    Desconectar tem que ser soft: mantem a linha, zera os tokens.
    """
    user, settings, merchant = ifood_setup
    merchant_db_id = merchant.id
    merchant_uuid = merchant.merchant_id

    with client.session_transaction() as sess:
        sess["user_info"] = {"id": "test_ifood_user", "email": "ifood_tester@comentsia.com.br", "name": "Tester iFood"}
        sess["credentials"] = {"token": "dummy"}

    with flask_app.app_context():
        # Personalizacao do cliente e uma avaliacao ja sincronizada.
        m = IFoodMerchant.query.get(merchant_db_id)
        m.tone = "luxo"
        m.default_greeting = "Prezado"
        rev = Review.query.filter_by(external_id="rev-desconexao-001", source="ifood").first()
        if not rev:
            rev = Review(
                user_id="test_ifood_user",
                external_id="rev-desconexao-001",
                source="ifood",
                ifood_merchant_id=merchant_db_id,
                reviewer_name="Cliente Antigo",
                rating=5,
                text="Tudo certo!",
                date=datetime.now(pytz.utc),
            )
            db.session.add(rev)
        db.session.commit()

    resp = client.post(f"/ifood/desconectar/{merchant_db_id}")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with flask_app.app_context():
        m = IFoodMerchant.query.get(merchant_db_id)
        assert m is not None, "a loja foi apagada; reconectar criaria um registro novo"
        assert m.is_active is False
        assert m.auto_reply_enabled is False
        # Desconexao precisa valer: sem token nao ha acesso a API do iFood.
        assert m.access_token is None
        assert m.refresh_token is None
        assert m.token_expires_at is None
        # E o que era do cliente continua ali.
        assert m.merchant_id == merchant_uuid
        assert m.tone == "luxo"
        assert m.default_greeting == "Prezado"
        assert Review.query.filter_by(ifood_merchant_id=merchant_db_id).count() >= 1


def test_reconectar_reaproveita_loja_existente(app, ifood_setup):
    """
    A busca no fluxo de reconexao e por (user_id, merchant_id) do iFood, sem
    filtrar is_active — entao uma loja desconectada e reencontrada e reativada
    com o mesmo id interno, em vez de virar uma loja nova.
    """
    user, settings, merchant = ifood_setup
    merchant_db_id = merchant.id
    merchant_uuid = merchant.merchant_id

    with app.app_context():
        m = IFoodMerchant.query.get(merchant_db_id)
        m.is_active = False
        m.access_token = None
        m.tone = "luxo"
        db.session.commit()

        antes = IFoodMerchant.query.filter_by(user_id="test_ifood_user").count()

        # Mesma consulta que os dois fluxos de OAuth fazem ao reconectar.
        achada = IFoodMerchant.query.filter_by(
            user_id="test_ifood_user", merchant_id=merchant_uuid
        ).first()
        assert achada is not None, "loja desconectada precisa ser reencontrada"
        assert achada.id == merchant_db_id, "o id interno tem que ser o mesmo"

        from utils.crypto import encrypt as crypto_encrypt
        achada.access_token = crypto_encrypt("novo_token")
        achada.is_active = True
        db.session.commit()

        depois = IFoodMerchant.query.filter_by(user_id="test_ifood_user").count()
        assert depois == antes, "reconectar nao pode criar uma segunda linha"

        m = IFoodMerchant.query.get(merchant_db_id)
        assert m.is_active is True
        assert m.tone == "luxo", "configuracao do cliente foi perdida na reconexao"


def test_integracoes_nao_lista_loja_desconectada(client, ifood_setup):
    """Loja desconectada continua no banco, mas nao pode aparecer como conectada."""
    user, settings, merchant = ifood_setup
    merchant_db_id = merchant.id

    with client.session_transaction() as sess:
        sess["user_info"] = {"id": "test_ifood_user", "email": "ifood_tester@comentsia.com.br", "name": "Tester iFood"}
        sess["credentials"] = {"token": "dummy"}

    resp = client.get("/integracoes")
    assert merchant.name.encode() in resp.data

    client.post(f"/ifood/desconectar/{merchant_db_id}")

    resp = client.get("/integracoes")
    assert merchant.name.encode() not in resp.data

    with flask_app.app_context():
        assert IFoodMerchant.query.get(merchant_db_id) is not None


def test_addon_expirado_perde_acesso(app):
    """
    Cortesia por tempo limitado precisa expirar sozinha: com data no passado,
    o add-on deixa de valer mesmo com o campo ligado.
    """
    from datetime import datetime, timedelta

    with app.app_context():
        casos = [
            ("test_addon_vencido", datetime.now() - timedelta(days=1), False),
            ("test_addon_vigente", datetime.now() + timedelta(days=30), True),
            ("test_addon_sem_prazo", None, True),
        ]
        for user_id, until, esperado in casos:
            s = UserSettings.query.filter_by(user_id=user_id).first()
            if not s:
                s = UserSettings(user_id=user_id, plano="free")
                db.session.add(s)
            s.has_addon_ifood = True
            s.addon_ifood_until = until
            db.session.commit()

            assert usuario_tem_addon_ifood(user_id) is esperado, \
                f"{user_id}: until={until} deveria dar {esperado}"
